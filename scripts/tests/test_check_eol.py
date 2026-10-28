import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import check_eol as eol

TODAY = dt.date(2026, 1, 1)

UV_LOCK = """
[[package]]
name = "my_app"
version = "0.1.0"
source = { virtual = "." }

[[package]]
name = "Django"
version = "4.2.7"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "acme-core"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
"""

YARN_V1 = """# yarn lockfile v1

"@scope/pkg@^1.0.0", "@scope/pkg@^1.2.0":
  version "1.2.3"

react@^18.0.0:
  version "18.2.0"
"""

YARN_BERRY = """__metadata:
  version: 8

"lodash@npm:^4.17.0":
  version: 4.17.21
"""

CARGO_LOCK = """
[[package]]
name = "app"
version = "0.1.0"

[[package]]
name = "serde"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
"""


class ParserTests(unittest.TestCase):
    def test_uv_lock_skips_virtual_and_normalizes(self):
        pkgs = eol.parse_uv_lock(UV_LOCK)
        self.assertEqual([p.name for p in pkgs], ["django", "acme-core"])

    def test_pyproject(self):
        names, py = eol.parse_pyproject(
            '[project]\nrequires-python = ">=3.11"\ndependencies = ["Django>=4,<5"]\n'
            '[dependency-groups]\ndev = ["pytest"]\n'
        )
        self.assertEqual(names, {"django", "pytest"})
        self.assertEqual(py, "3.11")

    def test_pyproject_requires_python_forms(self):
        def cycle(spec):
            return eol.parse_pyproject(f'[project]\nrequires-python = "{spec}"\n')[1]

        self.assertEqual(cycle("==3.9.*"), "3.9")
        self.assertEqual(cycle("~=3.9.0"), "3.9")
        self.assertEqual(cycle(">=3.9,<4"), "3.9")
        self.assertEqual(cycle(">=3.9.1"), "3.9")
        with self.assertRaises(ValueError):
            cycle("<4")

    def test_yarn_v1_and_berry(self):
        v1 = {(p.name, p.version) for p in eol.parse_yarn_lock(YARN_V1)}
        self.assertEqual(v1, {("@scope/pkg", "1.2.3"), ("react", "18.2.0")})
        self.assertEqual([(p.name, p.version) for p in eol.parse_yarn_lock(YARN_BERRY)], [("lodash", "4.17.21")])

    def test_package_lock(self):
        text = json.dumps({"packages": {"": {}, "node_modules/a": {"version": "1.0.0"}}})
        self.assertEqual([(p.name, p.version) for p in eol.parse_package_lock(text)], [("a", "1.0.0")])

    def test_package_json(self):
        names, node = eol.parse_package_json(
            '{"dependencies":{"a":"1"},"devDependencies":{"b":"2"},"engines":{"node":">=20"}}'
        )
        self.assertEqual(names, {"a", "b"})
        self.assertEqual(node, "20")

    def test_cargo(self):
        self.assertEqual([p.name for p in eol.parse_cargo_lock(CARGO_LOCK)], ["serde"])
        deps = eol.parse_cargo_toml('[dependencies]\nserde = "1"\n[dev-dependencies]\nx = { package = "y", version = "1" }\n')
        self.assertEqual(deps, {"serde", "y"})


class LogicTests(unittest.TestCase):
    CYCLES = [{"cycle": "4.2", "eol": "2026-04-01"}, {"cycle": "4", "eol": False}, {"cycle": "3.2", "eol": True}]

    def test_match_cycle_prefers_longest(self):
        self.assertEqual(eol.match_cycle("4.2.7", self.CYCLES)["cycle"], "4.2")
        self.assertIsNone(eol.match_cycle("5.0", self.CYCLES))

    def test_status(self):
        self.assertEqual(eol.eol_status({"eol": True}, TODAY, 90), ("eol", None))
        self.assertEqual(eol.eol_status({"eol": "2025-12-01"}, TODAY, 90), ("eol", -31))
        self.assertEqual(eol.eol_status({"eol": "2026-02-01"}, TODAY, 90), ("warning", 31))
        self.assertIsNone(eol.eol_status({"eol": "2027-01-01"}, TODAY, 90))
        self.assertIsNone(eol.eol_status({"eol": False}, TODAY, 90))

    def test_first_party_and_ignore(self):
        self.assertTrue(eol.is_first_party("Acme-core", ["acme-"]))
        self.assertFalse(eol.is_first_party("django", ["acme-", ""]))
        finding = {"ecosystem": "pypi", "name": "django", "version": "4.2.7"}
        self.assertTrue(eol.is_ignored(finding, [{"name": "Django", "ecosystem": "pypi"}]))
        self.assertFalse(eol.is_ignored(finding, [{"name": "django", "version": "5.0"}]))

    def test_ignore_file(self):
        self.assertEqual(eol.load_ignore_rules(None), [])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "ignore.json")
            path.write_text(json.dumps({"ignored": ["django", {"name": "x"}]}))
            self.assertEqual(eol.load_ignore_rules(str(path)), [{"name": "django"}, {"name": "x"}])

    def test_report(self):
        report = eol.render_report([{"status": "yanked", "ecosystem": "crates.io", "name": "serde", "version": "1.0.0"}], 90)
        self.assertIn("| yanked | crates.io | serde | 1.0.0 |", report)


class CollectTests(unittest.TestCase):
    def test_end_to_end_with_stubbed_network(self):
        responses = {
            eol.EOL_API.format(product="django"): [{"cycle": "4.2", "eol": "2025-04-01"}],
            eol.CRATES_API.format(name="serde", version="1.0.0"): {"version": {"yanked": True}},
        }
        original = eol.Fetcher.get_json
        eol.Fetcher.get_json = lambda self, url: responses.get(url)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                py, cargo = Path(tmp, "uv.lock"), Path(tmp, "Cargo.lock")
                py.write_text(UV_LOCK)
                cargo.write_text(CARGO_LOCK)
                args = eol.build_parser().parse_args(
                    ["--python-lock", str(py), "--cargo-lock", str(cargo), "--first-party-prefix", "acme-"]
                )
                findings = eol.collect_findings(args, TODAY)
        finally:
            eol.Fetcher.get_json = original
        self.assertEqual([(f["name"], f["status"]) for f in findings], [("django", "eol"), ("serde", "yanked")])

    def test_requires_a_lock_file(self):
        with self.assertRaises(SystemExit):
            eol.main([])


if __name__ == "__main__":
    unittest.main()
