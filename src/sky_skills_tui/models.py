"""Read upstream locks without modifying, migrating, or silently discarding them."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


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


def read_inventory(project: Path, home: Path | None = None) -> Inventory:
    home = home or Path.home()
    skills: list[Skill] = []
    warnings: list[str] = []
    for scope, path, root, expected in (
        ("project", project / "skills-lock.json", project, 1),
        ("global", global_lock(home), home, 3),
    ):
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
        if type(version) is not int or version != expected:
            warnings.append(
                f"{path}: schema {version!r}, expected {expected}. "
                "Entries are shown; mutations are blocked until the schema is supported."
            )
        for name, entry in data["skills"].items():
            if not isinstance(entry, dict) or not isinstance(entry.get("source"), str):
                warnings.append(f"Invalid entry {name!r} in {path}")
                continue
            skill = Skill(name, entry["source"], scope, path, dict(entry))
            canonical = root / ".agents/skills" / sanitized_name(name)
            if (canonical / "SKILL.md").is_file():
                skill.installed_path = canonical
            skills.append(skill)
    return Inventory(sorted(skills, key=lambda s: (s.source, s.scope, s.name)), warnings)


def validate_lock_for_mutation(path: Path, scope: str) -> None:
    """Prevent upstream's old-lock migration from silently wiping tracked entries."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        expected = 3 if scope == "global" else 1
        if (
            not isinstance(data, dict)
            or type(data.get("version")) is not int
            or data["version"] != expected
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
