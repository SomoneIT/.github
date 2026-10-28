#!/usr/bin/env python3
"""Validate the target of a DAST (OWASP ZAP) scan before it runs.

Reads a ZAP context file, extracts every URL in scope (includes, authentication
endpoints, or a bare URL; excluded regexes are ignored) and refuses targets that are not https or that point at loopback, private
or link-local addresses. Optional --allowed-host (repeatable) restricts the
target to specific host names. Writes `target=<first url>` to $GITHUB_OUTPUT.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import socket
import sys
import urllib.parse
import xml.etree.ElementTree as ET  # noqa: S405
from collections.abc import Callable
from pathlib import Path


_NUMERIC_HOST = re.compile(r"(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+))*\.?")


class TargetError(ValueError):
    pass


def _decode_literal(text: str, start: int) -> str:
    """Read the literal URL prefix at `start`, decoding escaped punctuation (e.g. `\\.`)."""
    chars: list[str] = []
    i = start
    while i < len(text):
        char = text[i]
        if char == "\\":
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if not nxt or nxt.isalnum() or nxt.isspace():
                raise TargetError(f"unsupported regex escape in target: {text[start:i + 2]!r}")
            chars.append(nxt)
            i += 2
            continue
        if char.isspace() or char in "<>\"'":
            break
        if char in "^$()*?|[]{}+":
            if "/" not in "".join(chars)[len("https://") :] and char not in "*$":
                raise TargetError(f"unsupported regex pattern in target host: {text[start:i + 1]!r}")
            break
        chars.append(char)
        i += 1
    return "".join(chars).rstrip(".")


def extract_targets(context_text: str) -> list[str]:
    try:
        root = ET.fromstring(context_text)  # noqa: S314
        excluded = {id(el) for ex in root.iter("excregexes") for el in ex.iter()}
        candidates = [el.text or "" for el in root.iter() if id(el) not in excluded]
    except ET.ParseError:
        candidates = [context_text]
    targets = [
        _decode_literal(text, match.start())
        for text in candidates
        for match in re.finditer(r"https?://", text)
    ]
    if not targets:
        raise TargetError("no target URL found in context file")
    return targets


def extract_target(context_text: str) -> str:
    return extract_targets(context_text)[0]


def resolve_host(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
    except socket.gaierror as err:
        raise TargetError(f"target host does not resolve: {host}") from err


def validate_target(
    url: str,
    allowed_hosts: list[str] | None = None,
    resolver: Callable[[str], list[str]] = resolve_host,
) -> str:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        raise TargetError(f"target must be an https URL: {url}")
    if host == "localhost" or host.endswith((".local", ".internal")):
        raise TargetError(f"target host is not public: {host}")
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        if _NUMERIC_HOST.fullmatch(host):
            raise TargetError(f"target host is a noncanonical IP literal: {host}") from None
        addresses = resolver(host)
    if not addresses:
        raise TargetError(f"target host does not resolve: {host}")
    for text in addresses:
        if not ipaddress.ip_address(text.split("%")[0]).is_global:
            raise TargetError(f"target address is not public: {host} -> {text}")
    if allowed_hosts and host not in {h.lower() for h in allowed_hosts}:
        raise TargetError(f"target host {host} is not in the allowed hosts")
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--context-file", required=True)
    parser.add_argument("--allowed-host", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        targets = extract_targets(Path(args.context_file).read_text(encoding="utf-8"))
        validated = [validate_target(url, args.allowed_host) for url in targets]
        target = validated[0]
    except (TargetError, OSError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"target={target}\n")
    print(f"DAST target accepted: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
