#!/usr/bin/env python3
"""Install the ClinResearch OpenCode integration without overwriting user files."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_ROOT = PACKAGE_ROOT / "payload"
INSTALL_MANIFEST_NAME = "clinresearch-global-install.json"
SKILL_RECEIPT_KEY_NAME = "clinresearch-skill-receipt-key"
APPROVAL_PERMISSIONS = {
    "literature_review_finalize_study_design": "ask",
    "literature_review_approve_study_design": "ask",
    "literature_review_confirm_systematic_evidence_phase_start": "ask",
    "literature_review_approve_systematic_evidence": "ask",
    "literature_review_approve_research_writing": "ask",
}
LEGACY_AGENT_FILENAMES = (
    "study-design-agent.md",
    "evidence-extraction-agent.md",
    "research-writing-agent.md",
    "search-agent.md",
    "screening-agent.md",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(item.relative_to(path).as_posix().encode("utf-8"))
            digest.update(sha256_file(item).encode("ascii"))
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"$schema": "https://opencode.ai/config.json"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{path} is not strict JSON. Preserve your JSONC file and install with "
            f"--config-dir pointing at a strict-JSON OpenCode configuration directory."
        ) from error
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return value


def copy_file(source: Path, destination: Path, installed: dict[str, str]) -> None:
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    installed[str(destination)] = sha256_file(destination)


def copy_tree(source: Path, destination: Path, installed: dict[str, str]) -> None:
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing directory: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    installed[str(destination)] = sha256_tree(destination)


def ensure_skill_receipt_key(config_dir: Path) -> Path:
    """Create the local-only signing key shared by the desktop plugin and backend."""
    path = config_dir / SKILL_RECEIPT_KEY_NAME
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{secrets.token_hex(32)}\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install ClinResearch Agents globally for OpenCode.")
    parser.add_argument(
        "--config-dir",
        default=str(Path.home() / ".config" / "opencode"),
        help="OpenCode global config directory (default: ~/.config/opencode).",
    )
    parser.add_argument(
        "--skills-dir",
        default=str(Path.home() / ".agents" / "skills"),
        help="Global Skills directory (default: ~/.agents/skills).",
    )
    parser.add_argument(
        "--backend-url",
        default="http://127.0.0.1:8010",
        help="ClinResearch backend URL, without /mcp (default: http://127.0.0.1:8010).",
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Back up conflicting ClinResearch files and replace them with this package version.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_dir = Path(args.config_dir).expanduser().resolve()
    skills_dir = Path(args.skills_dir).expanduser().resolve()
    config_path = config_dir / "opencode.json"
    install_manifest_path = config_dir / INSTALL_MANIFEST_NAME
    backend_url = args.backend_url.rstrip("/")
    if not backend_url.startswith(("http://", "https://")):
        raise ValueError("--backend-url must start with http:// or https://")
    if not (PAYLOAD_ROOT / "agents").is_dir() or not (PAYLOAD_ROOT / "skills").is_dir():
        raise ValueError("Package payload is incomplete. Rebuild or re-download the release package.")
    if install_manifest_path.exists():
        if not args.upgrade:
            raise FileExistsError(
                f"ClinResearch is already installed at {config_dir}. Run install.sh --upgrade to update it."
            )
        if args.dry_run:
            print(f"Existing ClinResearch installation at {config_dir} would be replaced safely.")
        else:
            uninstall = subprocess.run(
                [sys.executable, str(PACKAGE_ROOT / "scripts" / "uninstall.py"), "--config-dir", str(config_dir)],
                check=False,
            )
            if uninstall.returncode != 0:
                raise RuntimeError("Could not remove the existing ClinResearch installation for upgrade.")

    config = load_json(config_path)
    mcp = config.setdefault("mcp", {})
    permissions = config.setdefault("permission", {})
    plugins = config.setdefault("plugin", [])
    if not isinstance(mcp, dict) or not isinstance(permissions, dict) or not isinstance(plugins, list):
        raise ValueError("OpenCode config fields mcp, permission, and plugin must be object, object, and array.")
    if "literature_review" in mcp:
        raise ValueError("OpenCode config already defines mcp.literature_review; refusing to replace it.")
    for key in APPROVAL_PERMISSIONS:
        if key in permissions:
            raise ValueError(f"OpenCode config already defines permission.{key}; refusing to replace it.")

    plugin_destination = config_dir / "plugins" / "clinresearch-medical-skill-receipts.mjs"
    plugin_uri = plugin_destination.as_uri()
    if plugin_uri in plugins:
        raise ValueError("ClinResearch receipt plugin is already listed in OpenCode config.")

    files: dict[str, str] = {}
    directories: dict[str, str] = {}
    source_agents = sorted((PAYLOAD_ROOT / "agents").glob("*.md"))
    source_commands = sorted((PAYLOAD_ROOT / "commands").glob("*.md"))
    destinations = [
        *(config_dir / "agents" / source.name for source in source_agents),
        *(config_dir / "commands" / source.name for source in source_commands),
        plugin_destination,
        *(skills_dir / source.name for source in sorted((PAYLOAD_ROOT / "skills").iterdir()) if source.is_dir()),
    ]
    # Older releases used `*-agent.md` file names. Treat them as upgrade
    # conflicts so they are backed up instead of being loaded beside new IDs.
    legacy_destinations = [config_dir / "agents" / filename for filename in LEGACY_AGENT_FILENAMES]
    conflicts = [path for path in [*destinations, *legacy_destinations] if path.exists()]
    if conflicts:
        preview = "\n- ".join(str(path) for path in conflicts[:8])
        suffix = "\n- ..." if len(conflicts) > 8 else ""
        if not args.upgrade:
            raise FileExistsError(
                "Refusing to overwrite existing ClinResearch destination(s):\n- "
                f"{preview}{suffix}\nRun install.sh --upgrade to back up and replace them, or choose another target directory."
            )
    if args.dry_run:
        print("Dry run passed. No files were written.")
        print(f"Would install {len(source_agents)} agents, {len(source_commands)} commands, and global Skills.")
        return 0

    config_dir.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if config_path.exists():
        backup_path = config_dir / f"opencode.json.clinresearch-backup-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        shutil.copy2(config_path, backup_path)

    upgrade_backup_dir: Path | None = None
    if conflicts:
        upgrade_backup_dir = config_dir / f"backup-before-upgrade-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        for destination in conflicts:
            if destination.is_relative_to(config_dir):
                backup_destination = upgrade_backup_dir / "config" / destination.relative_to(config_dir)
            else:
                backup_destination = upgrade_backup_dir / "skills" / destination.relative_to(skills_dir)
            backup_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(backup_destination))

    try:
        skill_receipt_key_path = ensure_skill_receipt_key(config_dir)
        for source in source_agents:
            copy_file(source, config_dir / "agents" / source.name, files)
        for source in source_commands:
            copy_file(source, config_dir / "commands" / source.name, files)
        copy_file(PAYLOAD_ROOT / "plugins" / "medical-skill-receipts.mjs", plugin_destination, files)
        for source in sorted((PAYLOAD_ROOT / "skills").iterdir()):
            if source.is_dir():
                destination = skills_dir / source.name
                copy_tree(source, destination, directories)

        mcp["literature_review"] = {
            "type": "remote",
            "enabled": True,
            "url": f"{backend_url}/mcp/",
        }
        permissions.update(APPROVAL_PERMISSIONS)
        plugins.append(plugin_uri)
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        install_manifest_path.write_text(
            json.dumps(
                {
                    "package": json.loads((PACKAGE_ROOT / "manifest.json").read_text(encoding="utf-8")),
                    "installed_at": datetime.now(UTC).isoformat(),
                    "config_path": str(config_path),
                    "config_backup": str(backup_path) if backup_path else None,
                    "upgrade_backup": str(upgrade_backup_dir) if upgrade_backup_dir else None,
                    "installed_files": files,
                    "installed_directories": directories,
                    "mcp": mcp["literature_review"],
                    "permissions": APPROVAL_PERMISSIONS,
                    "plugin_uri": plugin_uri,
                    "skill_receipt_key_file": str(skill_receipt_key_path),
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    except Exception:
        raise

    print("ClinResearch OpenCode integration installed.")
    print(f"Agents: {config_dir / 'agents'}")
    print(f"Skills: {skills_dir}")
    print(f"MCP: {backend_url}/mcp/")
    print(f"Skill receipt key: {skill_receipt_key_path}")
    if upgrade_backup_dir:
        print(f"Previous conflicting files were backed up to: {upgrade_backup_dir}")
    print("Restart OpenCode, then type /literature-review followed by a research question.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileExistsError) as error:
        print(f"Install failed: {error}", file=sys.stderr)
        raise SystemExit(2)
