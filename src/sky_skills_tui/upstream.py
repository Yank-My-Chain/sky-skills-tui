"""The explicit, tested boundary with npm skills 1.7.0."""

from __future__ import annotations

import json
from typing import Any

from .runtime import CompatibilityError


def json_rows(output: str, command: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(output)
    except ValueError as error:
        raise CompatibilityError(
            f"skills {command}: expected one JSON array; output changed."
        ) from (error)
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise CompatibilityError(f"skills {command}: expected an array of objects.")
    for row in data:
        required = {"name": str, "path": str, "scope": str, "agents": list}
        if command == "add" and row.get("status") != "installed":
            # Failed/skipped rows have their own documented shape.
            if row.get("status") not in {"failed", "skipped"} or not isinstance(
                row.get("name"), str
            ):
                raise CompatibilityError("skills add: unrecognized result status or missing name.")
            continue
        for field, kind in required.items():
            if not isinstance(row.get(field), kind):
                raise CompatibilityError(f"skills {command}: {field!r} field changed or missing.")
        if row["scope"] not in {"project", "global"}:
            raise CompatibilityError(f"skills {command}: unrecognized scope {row['scope']!r}.")
        if any(not isinstance(agent, str) for agent in row["agents"]):
            raise CompatibilityError(f"skills {command}: agent list format changed.")
    return data
