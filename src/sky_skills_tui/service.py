"""Skills operations: the upstream CLI owns all installation and lock writes."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from collections import defaultdict
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlparse

import yaml

from .models import (
    Inventory,
    Skill,
    Status,
    global_lock,
    read_inventory,
    validate_lock_for_mutation,
)
from .runtime import CommandError, CompatibilityError, Runtime
from .upstream import json_rows

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# Sources are cloned and hashed in parallel, bounded to stay polite to Git hosts.
CHECK_CONCURRENCY = 4
T = TypeVar("T")
CheckProgress = Callable[[int, int, list[Skill]], None]


async def gather_all(*operations: Awaitable[T]) -> list[T]:
    """Run concurrently; on failure, cancel the rest and raise the first error."""
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(_awaited(operation)) for operation in operations]
    except ExceptionGroup as errors:
        raise errors.exceptions[0] from None
    return [task.result() for task in tasks]


async def _awaited(operation: Awaitable[T]) -> T:
    return await operation


def parse_available(output: str) -> list[tuple[str, str]]:
    """Parse the pinned CLI's list output; it explicitly rejects --list --json."""
    clean = ANSI.sub("", output)
    names: list[tuple[str, str]] = []
    in_list = False
    for line in clean.splitlines():
        if "Available Skills" in line:
            in_list = True
            continue
        if not in_list:
            continue
        match = re.match(r"^│ {4}(\S.*)$", line)
        if match:
            names.append((match[1].strip(), ""))
        elif names and (description := re.match(r"^│ {6}(\S.*)$", line)):
            name, old = names[-1]
            names[-1] = (name, (old + " " + description[1]).strip())
    if not names:
        raise CompatibilityError(
            "No skills found, or unsupported upstream list output. " + clean[-1500:]
        )
    return names


def discover(root: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for path in root.rglob("SKILL.md"):
        if any(part in {".git", "node_modules"} for part in path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            data = yaml.safe_load(text.split("---", 2)[1])
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                found.append((data["name"], path))
        except (OSError, ValueError, IndexError, yaml.YAMLError):
            continue
    return found


class SkillsService:
    def __init__(self, project: Path, runtime: Runtime | None = None, home: Path | None = None):
        self.project = project.resolve()
        self.home = home or Path.home()
        self.runtime = runtime or Runtime()
        self.mutation_lock = asyncio.Lock()

    def inventory(self) -> Inventory:
        return read_inventory(self.project, self.home)

    async def installed(self, skills: list[Skill]) -> None:
        """Enrich lock entries with the upstream CLI's actual placement information."""
        scopes = sorted({s.scope for s in skills} & {"project", "global"})
        outputs = await gather_all(
            *(
                self.runtime.run(
                    ["list", "--json"] + (["--global"] if scope == "global" else []),
                    self.project,
                )
                for scope in scopes
            )
        )
        for scope, output in zip(scopes, outputs, strict=True):
            entries = {entry["name"]: entry for entry in json_rows(output, "list")}
            for skill in skills:
                if skill.scope != scope:
                    continue
                entry = entries.get(skill.name)
                skill.installed_path = Path(entry["path"]) if entry else None
                skill.agents = entry.get("agents", []) if entry else []

    async def browse(self, source: str, scope: str) -> list[Skill]:
        if not source.strip() or source.startswith("-"):
            raise ValueError("Enter a repository URL, owner/repo, or local path.")
        output = await self.runtime.run(["add", source, "--list", "--full-depth"], self.project)
        lock = self.lock_path(scope)
        return [
            Skill(
                name,
                source,
                "available",
                lock,
                {"sourceType": "available", "targetScope": scope},
                description=description,
            )
            for name, description in parse_available(output)
        ]

    def lock_path(self, scope: str) -> Path:
        return global_lock(self.home) if scope == "global" else self.project / "skills-lock.json"

    async def install(self, skills: list[Skill], agents: list[str], *, copy: bool = False) -> str:
        if not agents or any(a.startswith("-") for a in agents):
            raise ValueError("Choose at least one valid target agent.")
        groups: dict[tuple[str, str], list[Skill]] = defaultdict(list)
        for skill in skills:
            scope = (
                str(skill.metadata.get("targetScope", "project"))
                if (skill.scope == "available")
                else skill.scope
            )
            if skill.name.startswith("-") or skill.source_input.startswith("-"):
                raise ValueError("Skill names and sources must not begin with '-'.")
            if skill.source_type in {"git", "gitlab"} and not skill.metadata.get("sourceUrl"):
                if not urlparse(skill.source).scheme and not skill.source.startswith("git@"):
                    raise ValueError(f"{skill.name}: original Git source URL missing from lock.")
            groups[(scope, skill.source_input)].append(skill)
        messages = []
        async with self.mutation_lock:
            for (scope, source), group in groups.items():
                validate_lock_for_mutation(self.lock_path(scope), scope)
                source_path = Path(source).expanduser()
                if not source_path.is_absolute():
                    source_path = self.project / source_path
                if scope == "global" and source_path.exists():
                    raise CompatibilityError(
                        "npm skills 1.7.0 does not track global local-path installs in its lock. "
                        "Use project scope or a Git URL."
                    )
                args = [
                    "add",
                    source,
                    "--skill",
                    *[s.name for s in group],
                    "--agent",
                    *agents,
                    "--yes",
                    "--json",
                    "--full-depth",
                ]
                if scope == "global":
                    args.append("--global")
                if copy:
                    args.append("--copy")
                data = json_rows(await self.runtime.run(args, self.project), "add")
                failed = [row for row in data if row.get("status") != "installed"]
                if failed or not data:
                    raise CommandError(f"Installation incomplete: {json.dumps(data)}")
                if {row["name"] for row in data} != {skill.name for skill in group}:
                    raise CompatibilityError(
                        "skills add returned different skill names than requested."
                    )
                tracked = {s.name for s in self.inventory().skills if s.scope == scope}
                if not {s.name for s in group}.issubset(tracked):
                    raise CompatibilityError(
                        "skills installed files but did not write the expected lock entries. "
                        "This source is not fully supported by the upstream lock mechanism."
                    )
                messages.append(f"Installed {len(group)} skill(s) from {source} ({scope}).")
        return "\n".join(messages)

    async def remove(self, skills: list[Skill]) -> str:
        groups: dict[str, list[str]] = defaultdict(list)
        for skill in skills:
            if skill.scope == "available" or skill.name.startswith("-") or skill.name == "*":
                raise ValueError("Only named installed skills can be removed.")
            groups[skill.scope].append(skill.name)
        messages = []
        async with self.mutation_lock:
            for scope, names in groups.items():
                validate_lock_for_mutation(self.lock_path(scope), scope)
                args = ["remove", *names, "--yes"]
                if scope == "global":
                    args.append("--global")
                output = await self.runtime.run(args, self.project)
                remaining = {s.name for s in self.inventory().skills if s.scope == scope}
                if remaining.intersection(names):
                    raise CommandError("Removal incomplete: " + ANSI.sub("", output)[-2000:])
                messages.append(f"Removed {len(names)} skill(s) ({scope}).")
        return "\n".join(messages)

    async def check(self, skills: list[Skill], progress: CheckProgress | None = None) -> None:
        groups: dict[tuple[str, str, str], list[Skill]] = defaultdict(list)
        for skill in skills:
            groups[(skill.source_type, skill.source_input, skill.ref)].append(skill)
        limit = asyncio.Semaphore(CHECK_CONCURRENCY)
        done = 0

        async def check_group(kind: str, source: str, ref: str, group: list[Skill]) -> None:
            nonlocal done
            async with limit:
                await self._check_source(kind, source, ref, group)
            done += 1
            if progress is not None:
                progress(done, len(groups), group)

        # One snapshot per source/ref: check every selected skill against the same tree.
        await gather_all(*(check_group(*key, group) for key, group in groups.items()))

    async def _check_source(self, kind: str, source: str, ref: str, group: list[Skill]) -> None:
        try:
            if kind == "local":
                root = Path(source)
                if not root.exists():
                    for skill in group:
                        skill.status = Status.DEPRECATED
                        skill.reason = "Recorded local source no longer exists."
                    return
                await self._compare(root, group, git=False)
            elif kind in {"github", "gitlab", "git"}:
                url = source.split("#", 1)[0]
                if kind == "github" and not urlparse(url).scheme and not url.startswith("git@"):
                    url = f"https://github.com/{url}.git"
                elif kind in {"git", "gitlab"} and not (
                    urlparse(url).scheme or url.startswith("git@")
                ):
                    for skill in group:
                        skill.status = Status.UNSUPPORTED
                        skill.reason = "Original Git URL missing from lock; cannot infer host."
                    return
                directory = tempfile.TemporaryDirectory(prefix="sky-check-")
                try:
                    root = Path(directory.name) / "repo"
                    args = ["git", "clone", "--depth", "1", "--single-branch"]
                    if ref:
                        args.extend(["--branch", ref])
                    args.extend(["--", url, str(root)])
                    await self.runtime.process(args, self.project)
                    await self._compare(root, group, git=True)
                finally:
                    # Deleting a large clone can take a while; keep it off the UI thread.
                    await asyncio.to_thread(directory.cleanup)
            else:
                for skill in group:
                    skill.status = Status.UNSUPPORTED
                    skill.reason = f"{kind} sources do not support folder comparison here."
        except (CommandError, TimeoutError, OSError) as error:
            for skill in group:
                skill.status = Status.UNAVAILABLE
                skill.reason = (
                    "Source could not be read (removed, private, offline, or authentication "
                    f"required). Deprecation is unconfirmed. {error}"
                )

    async def _compare(self, root: Path, skills: list[Skill], *, git: bool) -> None:
        # macOS temporary directories may use /var, an alias of /private/var.
        # Keep discovery, recorded paths and relative Git paths in the same namespace.
        root = root.resolve()
        found = await asyncio.to_thread(discover, root)
        comparable: list[tuple[Skill, Path, str, bool]] = []
        for skill in skills:
            recorded = skill.metadata.get("skillPath")
            candidates = [path for name, path in found if name == skill.name]
            if recorded:
                exact = (root / str(recorded)).resolve()
                if not exact.is_relative_to(root.resolve()):
                    skill.status, skill.reason = Status.UNSUPPORTED, "Unsafe skillPath in lock."
                    continue
                if exact.is_file():
                    candidates = [exact]
            if not candidates:
                skill.status = Status.DEPRECATED
                skill.reason = "Source is readable, but the recorded skill no longer exists."
                continue
            if len(candidates) > 1:
                skill.status, skill.reason = Status.UNSUPPORTED, "Ambiguous skill name at source."
                continue
            expected = str(
                skill.metadata.get("computedHash") or (skill.metadata.get("skillFolderHash") or "")
            )
            if not expected:
                skill.status, skill.reason = Status.UNSUPPORTED, "No comparable hash in lock."
                continue
            moved = bool(recorded and candidates[0].relative_to(root).as_posix() != recorded)
            comparable.append((skill, candidates[0].parent, expected, moved))

        def tree_hash(skill: Skill, expected: str) -> bool:
            # Global locks record Git tree SHAs; project locks record folder hashes.
            sha = re.fullmatch(r"[0-9a-fA-F]{40}", expected)
            return git and skill.scope == "global" and sha is not None

        async def revision(folder: Path) -> str:
            relative = folder.relative_to(root).as_posix()
            spec = "HEAD^{tree}" if relative == "." else "HEAD:" + relative
            return (await self.runtime.process(["git", "rev-parse", spec], root)).strip()

        trees = [(skill, folder) for skill, folder, sha, _ in comparable if tree_hash(skill, sha)]
        folders = [
            (skill, folder) for skill, folder, sha, _ in comparable if not tree_hash(skill, sha)
        ]
        tree_hashes, folder_hashes = await gather_all(
            gather_all(*(revision(folder) for _, folder in trees)),
            self.runtime.folder_hashes([folder for _, folder in folders]),
        )
        actual = {
            id(skill): value
            for (skill, _), value in zip(trees + folders, tree_hashes + folder_hashes, strict=True)
        }
        for skill, _, expected, moved in comparable:
            changed = actual[id(skill)] != expected
            skill.status = Status.OUTDATED if changed or moved else Status.CURRENT
            skill.reason = (
                "Skill moved upstream."
                if moved
                else (
                    "Source folder differs from the locked version."
                    if changed
                    else "Source folder matches the locked version."
                )
            )
