#!/usr/bin/env python3
"""Keep the distributable Agent/Skill payload aligned with canonical sources."""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "packages" / "clinresearch-opencode-global" / "payload"
SKILL_EXCLUDES = {
    ".DS_Store",
    ".Rhistory",
    "POLISH_CHANGELOG.md",
    "report.json",
}


def excluded(path: Path) -> bool:
    name = path.name
    return (
        name in SKILL_EXCLUDES
        or name.startswith("eval_report_")
        or "_audit_result" in name
        or "__pycache__" in path.parts
        or name.endswith((".pyc", ".pyo"))
    )


def source_files() -> dict[Path, Path]:
    mappings: dict[Path, Path] = {}
    for folder in ("agents", "commands"):
        source = ROOT / ".opencode" / folder
        for path in sorted(source.glob("*.md")):
            mappings[Path(folder) / path.name] = path
    mappings[Path("plugins") / "medical-skill-receipts.mjs"] = (
        ROOT / ".opencode" / "plugins" / "medical-skill-receipts.mjs"
    )
    skills = ROOT / ".agents" / "skills"
    for path in sorted(skills.rglob("*")):
        if path.is_file() and not excluded(path.relative_to(skills)):
            mappings[Path("skills") / path.relative_to(skills)] = path
    return mappings


def package_files() -> set[Path]:
    return {
        path.relative_to(PACKAGE)
        for path in PACKAGE.rglob("*")
        if path.is_file() and not excluded(path.relative_to(PACKAGE))
    }


def check() -> list[str]:
    expected = source_files()
    actual = package_files()
    problems: list[str] = []
    for relative, source in expected.items():
        destination = PACKAGE / relative
        if relative not in actual:
            problems.append(f"missing from package: {relative}")
        elif not filecmp.cmp(source, destination, shallow=False):
            problems.append(f"content differs: {relative}")
    for relative in sorted(actual - set(expected)):
        problems.append(f"package-only file: {relative}")
    return problems


def sync() -> None:
    for folder in ("agents", "commands", "plugins", "skills"):
        shutil.rmtree(PACKAGE / folder, ignore_errors=True)
    for relative, source in source_files().items():
        destination = PACKAGE / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Synchronize the package payload.")
    args = parser.parse_args()
    if args.write:
        sync()
    problems = check()
    if problems:
        print("Global package payload is out of sync:", file=sys.stderr)
        print("\n".join(f"- {problem}" for problem in problems), file=sys.stderr)
        return 1
    print("Global package payload matches canonical Agent and Skill sources.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
