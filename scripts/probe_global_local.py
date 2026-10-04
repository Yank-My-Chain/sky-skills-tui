"""Explore local-folder global installs in an isolated home, without changing Sky's policy."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sky_skills_tui.models import Skill
from sky_skills_tui.runtime import SKILLS_VERSION, Runtime
from sky_skills_tui.service import SkillsService
from sky_skills_tui.upstream import json_rows


class BuiltCLIRuntime(Runtime):
    """Research-only runtime for an explicitly supplied, already built upstream CLI."""

    def __init__(self, cli: Path, prefix: Path, env: dict[str, str]):
        super().__init__(prefix, env)
        self.entry = cli.resolve()
        self.reported_version: str | None = None

    async def ensure(self, *, upgrade: bool = False) -> str:
        if self.reported_version is None:
            self.reported_version = (
                await self.process(
                    [str(self.node), str(self.entry), "--version"], self.entry.parent
                )
            ).strip()
        return self.reported_version


def read_lock(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Global lock is not an object")
    return data


async def probe(
    version: str = SKILLS_VERSION, *, cli: Path | None = None, copy: bool = False
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="sky-global-local-probe-") as directory:
        root = Path(directory)
        home, project, source = root / "home", root / "project", root / "source"
        for path in (home, project, source / "probe-skill/references"):
            path.mkdir(parents=True)
        skill_md = source / "probe-skill/SKILL.md"
        skill_md.write_text(
            "---\nname: probe-skill\ndescription: Isolated global local-source probe\n---\n"
            "\n# Probe skill\n"
        )
        reference = source / "probe-skill/references/guide.txt"
        reference.write_text("original reference\n")
        env = dict(os.environ)
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "CODEX_HOME": str(home / ".codex"),
                "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                "XDG_STATE_HOME": str(home / ".local/state"),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local/share"),
            }
        )
        runtime = (
            BuiltCLIRuntime(cli, root / "npm", env)
            if cli
            else Runtime(root / "npm", env, version=version, allow_unverified=True)
        )
        reported_version = await runtime.ensure()
        lock_path = home / ".local/state/skills/.skill-lock.json"
        args = [
            "add",
            str(source),
            "--skill",
            "probe-skill",
            "--agent",
            "codex",
            "claude-code",
            "--global",
            "--yes",
            "--json",
            "--full-depth",
        ]
        if copy:
            args.append("--copy")
        installed = json_rows(await runtime.run(args, project), "add")
        assert len(installed) == 1 and installed[0]["status"] == "installed"
        canonical = Path(installed[0]["path"])
        assert (canonical / "references/guide.txt").read_text() == reference.read_text()
        agent_path = home / ".claude/skills/probe-skill"
        assert agent_path.is_symlink() is (not copy)
        listing = json_rows(await runtime.run(["list", "--global", "--json"], project), "list")
        assert any(row["name"] == "probe-skill" and row["scope"] == "global" for row in listing)
        lock = read_lock(lock_path)
        entry = lock.get("skills", {}).get("probe-skill")
        bundle = runtime.entry.parent.parent / "dist/cli.mjs"
        report: dict[str, Any] = {
            "cliVersion": reported_version,
            "cliBundleSha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
            "copy": copy,
            "installedAndListed": True,
            "globalLocalLockWritten": entry is not None,
            "globalLockVersion": lock.get("version"),
        }
        if cli and (runtime.entry.parent.parent / ".git").exists():
            report["upstreamGitCommit"] = (
                await runtime.process(["git", "rev-parse", "HEAD"], runtime.entry.parent.parent)
            ).strip()
        if entry:
            assert lock["version"] == 3
            assert entry["sourceType"] == "local"
            assert Path(entry["sourceUrl"]).resolve() == source.resolve()
            original_hash = await runtime.folder_hash(source / "probe-skill")
            assert entry["skillFolderHash"] == original_hash
            report.update(
                {
                    "sourceType": entry["sourceType"],
                    "hashMatchesSource": True,
                    "hashLength": len(original_hash),
                }
            )
            service = SkillsService(project, runtime, home)
            skill = Skill(
                "probe-skill", entry["source"], "global", lock_path, dict(entry), canonical
            )
            await service.check([skill])
            assert str(skill.status) == "current"
            reference.write_text("updated reference only\n")
            await service.check([skill])
            assert str(skill.status) == "outdated"
            await runtime.run(args, project)
            assert (canonical / "references/guide.txt").read_text() == reference.read_text()
            assert (agent_path / "references/guide.txt").read_text() == reference.read_text()
            updated_entry = read_lock(lock_path)["skills"]["probe-skill"]
            assert updated_entry["skillFolderHash"] != original_hash
            assert updated_entry["skillFolderHash"] == await runtime.folder_hash(
                source / "probe-skill"
            )
            assert updated_entry["installedAt"] == entry["installedAt"]
            report["referenceOnlyUpdateTracked"] = True
            report["originalInstallTimestampPreserved"] = True
            shutil.rmtree(canonical)
            await runtime.run(args, project)
            assert (canonical / "SKILL.md").is_file()
            report["missingInstallationRestored"] = True
            shutil.rmtree(source / "probe-skill")
            await service.check([skill])
            assert str(skill.status) == "removed upstream"
            report["sourceSkillRemovalDetected"] = True
        await runtime.run(["remove", "probe-skill", "--global", "--yes"], project)
        assert not canonical.exists()
        assert not agent_path.exists() and not agent_path.is_symlink()
        assert "probe-skill" not in read_lock(lock_path).get("skills", {})
        report["removedAndUntracked"] = True
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-version", default=SKILLS_VERSION)
    parser.add_argument("--cli", type=Path, help="Research an already built upstream bin/cli.mjs")
    parser.add_argument("--copy", action="store_true")
    parser.add_argument(
        "--require-lock", action="store_true", help="Fail unless global tracking works"
    )
    parser.add_argument("--report", type=Path, help="Write the JSON report to a file")
    args = parser.parse_args()
    report = asyncio.run(probe(args.skills_version, cli=args.cli, copy=args.copy))
    output = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.write_text(output)
    print(output, end="")
    if args.require_lock and not report["globalLocalLockWritten"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
