#!/usr/bin/env python3
"""The project version, which is recorded in five files.

    python3 scripts/version.py show            print where it is recorded
    python3 scripts/version.py set 0.2.0       write a new version everywhere
    python3 scripts/version.py check v0.2.0    fail unless every file says 0.2.0

`set` is how a release is started (see "Releasing" in README.md); `check` is what
the release workflow runs against the pushed tag before it publishes anything.

Versions look like 1.2.3, or 1.2.3-rc.1 (also -alpha.N, -beta.N) for a pre-release.
Needs Python 3.11+ and nothing else.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "backend/pyproject.toml"
UV_LOCK = ROOT / "backend/uv.lock"
INIT_PY = ROOT / "backend/app/__init__.py"
PACKAGE_JSON = ROOT / "frontend/package.json"
PACKAGE_LOCK = ROOT / "frontend/package-lock.json"

VERSION_RE = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(alpha|beta|rc)\.(0|[1-9]\d*))?"
)


def lock_form(version: str) -> str:
    """How uv.lock spells a version: 0.2.0-rc.1 is stored as 0.2.0rc1 (PEP 440)."""
    major, minor, patch, stage, number = VERSION_RE.fullmatch(version).groups()
    release = f"{major}.{minor}.{patch}"
    if stage is None:
        return release
    return release + {"alpha": "a", "beta": "b", "rc": "rc"}[stage] + number


def recorded() -> dict[str, str]:
    """The version each place holds, read with real parsers rather than regexes."""
    uv_lock = tomllib.loads(UV_LOCK.read_text())
    package_lock = json.loads(PACKAGE_LOCK.read_text())
    init_py = re.search(r'^__version__ = "([^"]*)"$', INIT_PY.read_text(), re.M)
    return {
        "backend/pyproject.toml": tomllib.loads(PYPROJECT.read_text())["project"]["version"],
        "backend/uv.lock": next(
            p["version"] for p in uv_lock["package"] if p["name"] == "grocy-assistant"
        ),
        "backend/app/__init__.py": init_py.group(1) if init_py else "(not found)",
        "frontend/package.json": json.loads(PACKAGE_JSON.read_text())["version"],
        "frontend/package-lock.json": package_lock["version"],
        "frontend/package-lock.json (root package)": package_lock["packages"][""]["version"],
    }


def mismatches(version: str) -> list[str]:
    wrong = []
    for place, found in recorded().items():
        expected = lock_form(version) if place.endswith("uv.lock") else version
        if found != expected:
            wrong.append(f"{place} says {found}, expected {expected}")
    return wrong


def replace_once(path: Path, pattern: str, replacement: str) -> None:
    text, count = re.subn(pattern, replacement, path.read_text(), flags=re.M)
    if count != 1:
        fail(f"expected exactly one version line in {path.relative_to(ROOT)}, found {count}")
    path.write_text(text)


def set_version(version: str) -> None:
    quoted = f'"{version}"'
    replace_once(PYPROJECT, r'^version = "[^"]*"$', f"version = {quoted}")
    replace_once(
        UV_LOCK,
        r'^(name = "grocy-assistant"\nversion = )"[^"]*"$',
        rf'\g<1>"{lock_form(version)}"',
    )
    replace_once(INIT_PY, r'^__version__ = "[^"]*"$', f"__version__ = {quoted}")
    replace_once(PACKAGE_JSON, r'^  "version": "[^"]*"', f'  "version": {quoted}')
    replace_once(PACKAGE_LOCK, r'^  "version": "[^"]*"', f'  "version": {quoted}')
    replace_once(
        PACKAGE_LOCK,
        r'^(    "": \{\n      "name": "[^"]*",\n      "version": )"[^"]*"',
        rf"\g<1>{quoted}",
    )


def fail(*messages: str) -> None:
    for message in messages:
        # GitHub Actions shows "::error::" lines on the run's summary page.
        print(f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"error: {message}")
    raise SystemExit(1)


def main(argv: list[str]) -> None:
    match argv:
        case ["show"]:
            for place, found in recorded().items():
                print(f"{found:<12} {place}")
        case ["set", version] if VERSION_RE.fullmatch(version):
            set_version(version)
            if wrong := mismatches(version):
                fail(*wrong)
            print(f"Version is now {version}. Next: commit, then tag v{version} (see README).")
        case ["check", tag] if tag.startswith("v") and VERSION_RE.fullmatch(tag[1:]):
            if wrong := mismatches(tag[1:]):
                fail(f"tag {tag} does not match the version in the code", *wrong)
            print(f"Tag {tag} matches the version recorded in all {len(recorded())} places.")
        case ["set" | "check", bad]:
            fail(f"{bad!r} is not a version like 1.2.3 or 1.2.3-rc.1 (tags add a leading v)")
        case _:
            print(__doc__.strip())
            raise SystemExit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
