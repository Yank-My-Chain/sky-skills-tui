"""Read upstream locks without modifying, migrating, or silently discarding them."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .runtime import HASH_V2_RELEASE, SKILLS_VERSION, release


class Status(StrEnum):
    UNCHECKED = "unchecked"
    CURRENT = "current"
    OUTDATED = "outdated"
    DEPRECATED = "removed upstream"
    UNAVAILABLE = "source unavailable"
    UNSUPPORTED = "unverifiable"


@dataclass
class Skill:
    name: str
    source: str
    scope: str
    lock_path: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    installed_path: Path | None = None
    agents: list[str] = field(default_factory=list)
    status: Status = Status.UNCHECKED
    reason: str = "Run Check to compare with the source."
    description: str = ""
    lock_version: int | None = None

    @property
    def key(self) -> str:
        return f"{self.scope}:{self.name}"

    @property
    def source_type(self) -> str:
        return str(self.metadata.get("sourceType", "unknown"))

    @property
    def ref(self) -> str:
        return str(self.metadata.get("ref") or "")

    @property
    def source_input(self) -> str:
        source = str(self.metadata.get("sourceUrl") or self.source)
        if self.source_type == "local":
            path = Path(source).expanduser()
            if not path.is_absolute():
                path = self.lock_path.parent / path
            return str(path.resolve())
        if self.ref:
            from urllib.parse import quote

            source = source.split("#", 1)[0] + "#" + quote(self.ref, safe="/")
        return source


@dataclass
class Inventory:
    skills: list[Skill]
    warnings: list[str]


def global_lock(home: Path | None = None) -> Path:
    state = os.environ.get("XDG_STATE_HOME")
    return (
        Path(state) / "skills/.skill-lock.json"
        if state
        else (home or Path.home()) / (".agents/.skill-lock.json")
    )


def sanitized_name(name: str) -> str:
    return re.sub(r"[^a-z0-9._]+", "-", name.lower()).strip(".-")[:255] or "unnamed-skill"


def lock_schemas(scope: str, skills_version: str = SKILLS_VERSION) -> tuple[int, ...]:
    """Lock schema versions the given skills release reads without discarding entries.

    The global lock is schema 3 throughout; upstream empties older global locks.
    skills 1.8.0 moved the project lock to schema 2 and migrates schema 1 in place,
    re-deriving each computedHash only when the installed files still match it.
    """
    if scope == "global":
        return (3,)
    return (1, 2) if release(skills_version) >= HASH_V2_RELEASE else (1,)


def _expected(schemas: tuple[int, ...]) -> str:
    return " or ".join(map(str, schemas))


def read_inventory(
    project: Path, home: Path | None = None, skills_version: str = SKILLS_VERSION
) -> Inventory:
    home = home or Path.home()
    skills: list[Skill] = []
    warnings: list[str] = []
    for scope, path, root in (
        ("project", project / "skills-lock.json", project),
        ("global", global_lock(home), home),
    ):
        expected = lock_schemas(scope, skills_version)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as error:
            warnings.append(f"Cannot read {path}: {error}")
            continue
        if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
            warnings.append(f"Invalid lock structure: {path}")
            continue
        version = data.get("version")
        if type(version) is not int or version not in expected:
            warnings.append(
                f"{path}: schema {version!r}, expected {_expected(expected)}. "
                "Entries are shown; mutations are blocked until the schema is supported."
            )
        for name, entry in data["skills"].items():
            if not isinstance(entry, dict) or not isinstance(entry.get("source"), str):
                warnings.append(f"Invalid entry {name!r} in {path}")
                continue
            skill = Skill(name, entry["source"], scope, path, dict(entry))
            skill.lock_version = version if type(version) is int else None
            canonical = root / ".agents/skills" / sanitized_name(name)
            if (canonical / "SKILL.md").is_file():
                skill.installed_path = canonical
            skills.append(skill)
    return Inventory(sorted(skills, key=lambda s: (s.source, s.scope, s.name)), warnings)


def validate_lock_for_mutation(
    path: Path, scope: str, skills_version: str = SKILLS_VERSION
) -> None:
    """Prevent upstream's old-lock migration from silently wiping tracked entries."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        expected = lock_schemas(scope, skills_version)
        if (
            not isinstance(data, dict)
            or type(data.get("version")) is not int
            or data["version"] not in expected
            or not isinstance(data.get("skills"), dict)
            or any(
                not isinstance(entry, dict) or not isinstance(entry.get("source"), str)
                for entry in data["skills"].values()
            )
        ):
            raise ValueError("unsupported schema or invalid entries")
    except (OSError, ValueError) as error:
        raise ValueError(
            f"Refusing to modify {path}: {error}. Repair or back it up first."
        ) from error
