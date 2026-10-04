"""Command entry point, diagnostics, and unattended npm setup."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .app import SkillsApp
from .runtime import SUPPORTED_VERSIONS, Runtime
from .service import SkillsService


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="sky", description="A Textual manager for npm skills lock files."
    )
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--project", type=Path, default=Path.cwd(), help="Project directory")
    commands = result.add_subparsers(dest="command")
    setup = commands.add_parser("setup", help="Install or repair the managed npm skills runtime")
    setup.add_argument(
        "--upgrade", action="store_true", help="Reinstall the supported skills release"
    )
    commands.add_parser("doctor", help="Report Node, npm, Git, runtime and lock diagnostics")
    listing = commands.add_parser(
        "list", help="Read installed skill locks without launching the TUI"
    )
    listing.add_argument("--json", action="store_true", help="Machine-readable inventory")
    return result


def main() -> None:
    args = parser().parse_args()
    project = args.project.expanduser().resolve()
    if not project.is_dir():
        parser().error(f"Project directory does not exist: {project}")
    runtime = Runtime()
    service = SkillsService(project, runtime)
    try:
        if args.command == "setup":
            version = asyncio.run(runtime.ensure(upgrade=args.upgrade))
            print(f"skills {version} ready at {runtime.prefix}")
        elif args.command == "doctor":
            print(f"Python: {sys.version.split()[0]}")
            print(f"Node: {runtime.node}")
            print(f"npm: {runtime.npm}")
            print(
                f"Git: {shutil.which('git') or 'missing — install Git to use repository sources'}"
            )
            print(f"skills: {runtime.version() or 'not installed (prepared on first launch)'}")
            print(f"Runtime: {runtime.prefix}")
            inventory = service.inventory()
            print(f"Tracked skills: {len(inventory.skills)}")
            for warning in inventory.warnings:
                print(warning)
            installed_version = runtime.version()
            if installed_version and installed_version not in SUPPORTED_VERSIONS:
                print(
                    f"INCOMPATIBLE/UNVERIFIED skills version: {installed_version}. "
                    f"Supported: {', '.join(sorted(SUPPORTED_VERSIONS))}. "
                    "Run sky setup --upgrade."
                )
                raise SystemExit(1)
        elif args.command == "list":
            inventory = service.inventory()
            if args.json:
                print(
                    json.dumps(
                        [
                            {
                                "name": s.name,
                                "scope": s.scope,
                                "source": s.source,
                                "lockPath": str(s.lock_path),
                                "metadata": s.metadata,
                                "installedPath": str(s.installed_path)
                                if s.installed_path
                                else None,
                            }
                            for s in inventory.skills
                        ],
                        indent=2,
                    )
                )
            else:
                for skill in inventory.skills:
                    print(f"{skill.scope:7} {skill.name:30} {skill.source}")
            for warning in inventory.warnings:
                print(warning, file=sys.stderr)
        else:
            SkillsApp(service).run()
    except (RuntimeError, OSError, ValueError, TimeoutError) as error:
        print(f"sky: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
