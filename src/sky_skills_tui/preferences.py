"""User agent defaults, separate from upstream installation locks."""

import json
import os
import tempfile
from pathlib import Path

from platformdirs import user_config_path

from .agents import agent_targets, selected_agents


class AgentPreferences:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else user_config_path("sky") / "preferences.json"

    def load(self) -> str:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1:
                return "codex"
            names = data.get("agents")
            if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
                return "codex"
            return agent_targets(selected_agents(" ".join(names))) or "codex"
        except (OSError, ValueError):
            return "codex"

    def save(self, agents: str) -> None:
        targets = agent_targets(selected_agents(agents))
        if not targets:
            raise ValueError("Choose at least one target agent.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, prefix=".agents-", delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump({"version": 1, "agents": targets.split()}, handle, indent=2)
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
