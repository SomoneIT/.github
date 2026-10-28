#!/usr/bin/env python3
"""Report end-of-life, soon-to-be-EOL and yanked dependencies found in lock files.

Supported inputs (all optional, at least one lock file is required):
  --python-lock / --python-project   uv.lock and its pyproject.toml
  --npm-lock / --npm-package-json    yarn.lock (v1 or berry) or package-lock.json
  --cargo-lock / --cargo-toml        Cargo.lock (crates.io yanked check)

Lifecycle data comes from https://endoflife.date, yanked crates from crates.io.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

EOL_API = "https://endoflife.date/api/{product}.json"
CRATES_API = "https://crates.io/api/v1/crates/{name}/{version}"
DEFAULT_USER_AGENT = "org-eol-check"
HTTP_TIMEOUT = 20


@dataclass(frozen=True)
class Package:
    ecosystem: str
    name: str
    version: str


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_uv_lock(text: str) -> list[Package]:
    data = tomllib.loads(text)
    packages = []
    for pkg in data.get("package", []):
        source = pkg.get("source", {})
        if "virtual" in source or "editable" in source:
            continue
        if pkg.get("name") and pkg.get("version"):
            packages.append(Package("pypi", normalize(pkg["name"]), pkg["version"]))
    return packages


def _requirement_name(requirement: str) -> str | None:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return normalize(match.group(1)) if match else None


def _python_cycle(specifier: str) -> str | None:
    """Return the lowest Python cycle allowed by a requires-python specifier."""
    if not specifier.strip():
        return None
    cycles = []
    for clause in specifier.split(","):
        match = re.fullmatch(r"\s*(>=|>|==|===|~=)\s*v?(\d+\.\d+)(?:\.[\w*]+)*\s*", clause)
        if match:
            cycles.append(match.group(2))
    if not cycles:
        raise ValueError(f"Cannot determine a Python version from requires-python {specifier!r}")
    return max(cycles, key=lambda c: tuple(map(int, c.split("."))))


def parse_pyproject(text: str) -> tuple[set[str], str | None]:
    """Return (direct dependency names, minimum Python cycle such as '3.11')."""
    data = tomllib.loads(text)
    project = data.get("project", {})
    requirements = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        requirements.extend(group)
    for group in data.get("dependency-groups", {}).values():
        requirements.extend(item for item in group if isinstance(item, str))
    names = {n for n in map(_requirement_name, requirements) if n}
    return names, _python_cycle(project.get("requires-python", ""))


def parse_yarn_lock(text: str) -> list[Package]:
    packages: dict[tuple[str, str], Package] = {}
    name: str | None = None
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if not line.startswith(" "):
            spec = line.rstrip(":").split(",")[0].strip().strip('"')
            name = spec[: spec.rindex("@")] if "@" in spec[1:] else None
            continue
        match = re.match(r'\s+version:?\s+"?([^"\s]+)"?\s*$', line)
        if name and match:
            packages[(name, match.group(1))] = Package("npm", name, match.group(1))
            name = None
    return list(packages.values())


def parse_package_lock(text: str) -> list[Package]:
    data = json.loads(text)
    packages = []
    if data.get("lockfileVersion") == 1:
        def collect_legacy(dependencies: dict) -> None:
            for name, info in dependencies.items():
                if info.get("version"):
                    packages.append(Package("npm", name, info["version"]))
                collect_legacy(info.get("dependencies", {}))

        collect_legacy(data.get("dependencies", {}))
        return packages
    for path, info in data.get("packages", {}).items():
        if "node_modules/" not in path or not info.get("version") or info.get("link"):
            continue
        packages.append(Package("npm", path.rsplit("node_modules/", 1)[1], info["version"]))
    return packages


def parse_npm_lock(path: Path) -> list[Package]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return parse_package_lock(text)
    return parse_yarn_lock(text)


def parse_package_json(text: str) -> tuple[set[str], str | None]:
    """Return (direct dependency names, minimum Node cycle such as '20')."""
    data = json.loads(text)
    names = {
        name
        for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
        for name in data.get(key, {})
    }
    match = re.search(r">=\s*v?(\d+)", data.get("engines", {}).get("node", ""))
    return names, match.group(1) if match else None


def parse_cargo_lock(text: str) -> list[Package]:
    data = tomllib.loads(text)
    return [
        Package("crates.io", pkg["name"], pkg["version"])
        for pkg in data.get("package", [])
        if pkg.get("source") == "registry+https://github.com/rust-lang/crates.io-index"
    ]


def parse_cargo_toml(text: str) -> set[str]:
    data = tomllib.loads(text)
    names: set[str] = set()
    sections = [data, data.get("workspace", {}), *data.get("target", {}).values()]
    for section in sections:
        for key in ("dependencies", "dev-dependencies", "build-dependencies"):
            for dep, spec in section.get(key, {}).items():
                names.add(spec["package"] if isinstance(spec, dict) and "package" in spec else dep)
    return names


class Fetcher:
    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._cache: dict[str, object] = {}

    def get_json(self, url: str) -> object | None:
        if url in self._cache:
            return self._cache[url]
        request = urllib.request.Request(
            url, headers={"User-Agent": self.user_agent, "Accept": "application/json"}
        )
        result: object | None = None
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:  # noqa: S310
                result = json.load(response)
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
        self._cache[url] = result
        return result


def match_cycle(version: str, cycles: list[dict]) -> dict | None:
    best = None
    for cycle in cycles:
        label = str(cycle.get("cycle", ""))
        if version == label or version.startswith(label + "."):
            if best is None or len(label) > len(str(best["cycle"])):
                best = cycle
    return best


def eol_status(cycle: dict, today: dt.date, warn_days: int) -> tuple[str, int | None] | None:
    """Return ('eol'|'warning', days_left) or None when the cycle is supported."""
    eol = cycle.get("eol")
    if eol is True:
        return "eol", None
    if not eol:
        return None
    try:
        days_left = (dt.date.fromisoformat(str(eol)) - today).days
    except ValueError:
        return None
    if days_left < 0:
        return "eol", days_left
    if days_left <= warn_days:
        return "warning", days_left
    return None


def lookup_eol(
    fetcher: Fetcher, product: str, version: str, today: dt.date, warn_days: int
) -> dict | None:
    cycles = fetcher.get_json(EOL_API.format(product=urllib.parse.quote(product, safe="")))
    if not isinstance(cycles, list):
        return None
    cycle = match_cycle(version, cycles)
    if cycle is None:
        return None
    status = eol_status(cycle, today, warn_days)
    if status is None:
        return None
    return {
        "product": product,
        "version": version,
        "cycle": str(cycle["cycle"]),
        "eol": cycle["eol"],
        "status": status[0],
        "days_left": status[1],
    }


def is_yanked(fetcher: Fetcher, package: Package) -> bool:
    url = CRATES_API.format(
        name=urllib.parse.quote(package.name, safe=""),
        version=urllib.parse.quote(package.version, safe=""),
    )
    data = fetcher.get_json(url)
    return bool(isinstance(data, dict) and data.get("version", {}).get("yanked"))


def load_ignore_rules(path: str | None) -> list[dict]:
    if not path:
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("ignored", [])
    rules = []
    for item in data:
        rules.append({"name": item} if isinstance(item, str) else dict(item))
    return rules


def is_ignored(finding: dict, rules: list[dict]) -> bool:
    for rule in rules:
        if normalize(str(rule.get("name", ""))) != normalize(finding["name"]):
            continue
        if rule.get("ecosystem") not in (None, finding["ecosystem"]):
            continue
        if rule.get("version") not in (None, finding["version"]):
            continue
        return True
    return False


def is_first_party(name: str, prefixes: list[str]) -> bool:
    lowered = name.lower()
    return any(lowered.startswith(prefix.lower()) for prefix in prefixes if prefix)


def collect_findings(args: argparse.Namespace, today: dt.date) -> list[dict]:
    fetcher = Fetcher(args.user_agent)
    findings: list[dict] = []
    prefixes = args.first_party_prefix or []
    rules = load_ignore_rules(args.ignore_file)

    def add(ecosystem: str, name: str, version: str, info: dict) -> None:
        finding = {"ecosystem": ecosystem, "name": name, **info, "version": version}
        if not is_ignored(finding, rules):
            findings.append(finding)

    def check_packages(
        packages: list[Package], direct: set[str] | None, runtime: tuple[str, str | None]
    ) -> None:
        product, runtime_version = runtime
        if runtime_version:
            info = lookup_eol(fetcher, product, runtime_version, today, args.warn_days)
            if info:
                add("runtime", product, runtime_version, info)
        for pkg in packages:
            if is_first_party(pkg.name, prefixes):
                continue
            if direct is not None and pkg.name not in direct:
                continue
            info = lookup_eol(fetcher, normalize(pkg.name), pkg.version, today, args.warn_days)
            if info:
                add(pkg.ecosystem, pkg.name, pkg.version, info)

    if args.python_lock:
        packages = parse_uv_lock(Path(args.python_lock).read_text(encoding="utf-8"))
        direct, runtime_version = None, None
        if args.python_project:
            project = Path(args.python_project)
            project = project / "pyproject.toml" if project.is_dir() else project
            direct, runtime_version = parse_pyproject(project.read_text(encoding="utf-8"))
        check_packages(packages, direct, ("python", runtime_version))

    if args.npm_lock:
        packages = parse_npm_lock(Path(args.npm_lock))
        direct, runtime_version = None, None
        if args.npm_package_json:
            direct, runtime_version = parse_package_json(
                Path(args.npm_package_json).read_text(encoding="utf-8")
            )
        check_packages(packages, direct, ("nodejs", runtime_version))

    if args.cargo_lock:
        packages = parse_cargo_lock(Path(args.cargo_lock).read_text(encoding="utf-8"))
        direct = None
        if args.cargo_toml:
            direct = parse_cargo_toml(Path(args.cargo_toml).read_text(encoding="utf-8"))
        packages = [p for p in packages if not is_first_party(p.name, prefixes)]
        for pkg in packages:
            if is_yanked(fetcher, pkg):
                add(pkg.ecosystem, pkg.name, pkg.version, {"status": "yanked"})
        if direct is not None:
            check_packages(packages, direct, ("rust", None))

    return findings


def render_report(findings: list[dict], warn_days: int) -> str:
    lines = [
        "Automated dependency lifecycle report.",
        "",
        f"Warning threshold: {warn_days} days before end of life.",
        "",
        "| Status | Ecosystem | Package | Version | Detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in findings:
        if item["status"] == "yanked":
            detail = "version yanked from crates.io"
        elif item["status"] == "eol":
            detail = f"cycle {item['cycle']} reached end of life ({item['eol']})"
        else:
            detail = f"cycle {item['cycle']} ends on {item['eol']} ({item['days_left']} days)"
        lines.append(
            f"| {item['status']} | {item['ecosystem']} | {item['name']} | {item['version']} | {detail} |"
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python-lock", help="Path to uv.lock")
    parser.add_argument("--python-project", help="pyproject.toml (or its directory)")
    parser.add_argument("--npm-lock", help="Path to yarn.lock or package-lock.json")
    parser.add_argument("--npm-package-json", help="Path to package.json")
    parser.add_argument("--cargo-lock", help="Path to Cargo.lock")
    parser.add_argument("--cargo-toml", help="Path to Cargo.toml (restricts EOL checks to direct deps)")
    parser.add_argument(
        "--first-party-prefix",
        action="append",
        default=[],
        help="Package name prefix to skip (repeatable)",
    )
    parser.add_argument("--ignore-file", help="Optional JSON file listing findings to ignore")
    parser.add_argument("--warn-days", type=int, default=90)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--output", help="Write the markdown report here (default: stdout)")
    parser.add_argument("--fail-on-findings", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (args.python_lock or args.npm_lock or args.cargo_lock):
        parser.error("at least one of --python-lock, --npm-lock, --cargo-lock is required")

    findings = collect_findings(args, dt.date.today())
    report = render_report(findings, args.warn_days) if findings else ""
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    elif report:
        print(report, end="")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"count={len(findings)}\n")
    print(f"{len(findings)} finding(s)", file=sys.stderr)
    return 1 if findings and args.fail_on_findings else 0


if __name__ == "__main__":
    sys.exit(main())
