"""Agent targets from the published skills@1.7.0 catalogue.

Source: https://registry.npmjs.org/skills/-/skills-1.7.0.tgz, package/dist/cli.mjs.
The live compatibility suite verifies this metadata against the managed CLI.
"""

COMMON_AGENTS = ("codex", "github-copilot", "cursor", "claude-code", "gemini-cli", "opencode")

# Common targets first; the remaining display names are alphabetical.
AGENTS: tuple[tuple[str, str], ...] = (
    ("codex", "Codex"),
    ("github-copilot", "GitHub Copilot"),
    ("cursor", "Cursor"),
    ("claude-code", "Claude Code"),
    ("gemini-cli", "Gemini CLI"),
    ("opencode", "OpenCode"),
    ("adal", "AdaL"),
    ("aider-desk", "AiderDesk"),
    ("amp", "Amp"),
    ("antigravity", "Antigravity"),
    ("antigravity-cli", "Antigravity CLI"),
    ("astrbot", "AstrBot"),
    ("augment", "Augment"),
    ("autohand-code", "Autohand Code CLI"),
    ("cline", "Cline"),
    ("codestudio", "Code Studio"),
    ("codearts-agent", "CodeArts Agent"),
    ("codebuddy", "CodeBuddy"),
    ("codemaker", "Codemaker"),
    ("command-code", "Command Code"),
    ("continue", "Continue"),
    ("cortex", "Cortex Code"),
    ("crush", "Crush"),
    ("deepagents", "Deep Agents"),
    ("devin", "Devin for Terminal"),
    ("dexto", "Dexto"),
    ("droid", "Droid"),
    ("eve", "Eve"),
    ("firebender", "Firebender"),
    ("forgecode", "ForgeCode"),
    ("fx", "fx"),
    ("goose", "Goose"),
    ("grok", "Grok Build"),
    ("hermes-agent", "Hermes Agent"),
    ("bob", "IBM Bob"),
    ("iflow-cli", "iFlow CLI"),
    ("inference-sh", "inference.sh"),
    ("jazz", "Jazz"),
    ("junie", "Junie"),
    ("kilo", "Kilo Code"),
    ("kimchi", "Kimchi"),
    ("kimi-code-cli", "Kimi Code CLI"),
    ("kiro-cli", "Kiro CLI"),
    ("kode", "Kode"),
    ("lingma", "Lingma"),
    ("loaf", "Loaf"),
    ("mcpjam", "MCPJam"),
    ("minimax-code", "MiniMax Code"),
    ("mistral-vibe", "Mistral Vibe"),
    ("moxby", "Moxby"),
    ("mux", "Mux"),
    ("neovate", "Neovate"),
    ("ona", "Ona"),
    ("openclaw", "OpenClaw"),
    ("openhands", "OpenHands"),
    ("pi", "Pi"),
    ("pochi", "Pochi"),
    ("posit-assistant", "Posit Assistant"),
    ("promptscript", "PromptScript"),
    ("qoder", "Qoder"),
    ("qoder-cn", "Qoder CN"),
    ("qwen-code", "Qwen Code"),
    ("reasonix", "Reasonix"),
    ("replit", "Replit"),
    ("roo", "Roo Code"),
    ("rovodev", "Rovo Dev"),
    ("sarvam-code", "Sarvam Code"),
    ("tabnine-cli", "Tabnine CLI"),
    ("terramind", "Terramind"),
    ("tinycloud", "Tinycloud"),
    ("trae", "Trae"),
    ("trae-cn", "Trae CN"),
    ("universal", "Universal"),
    ("warp", "Warp"),
    ("windsurf", "Windsurf"),
    ("zcode", "ZCode"),
    ("zed", "Zed"),
    ("zencoder", "Zencoder"),
    ("zenflow", "Zenflow"),
)
AGENT_IDS = frozenset(identifier for identifier, _ in AGENTS)


def selected_agents(value: str) -> set[str]:
    """Expand the upstream all-agents target and ignore obsolete identifiers."""
    names = set(value.replace(",", " ").split())
    return set(AGENT_IDS) if "*" in names else names & AGENT_IDS


def agent_targets(selected: set[str]) -> str:
    """Serialize a selection in catalogue order, preserving explicit all-agents intent."""
    if selected >= AGENT_IDS:
        return "*"
    return " ".join(identifier for identifier, _ in AGENTS if identifier in selected)


def agent_summary(value: str) -> str:
    selected = selected_agents(value)
    if selected == AGENT_IDS:
        return f"All {len(AGENTS)} agents"
    if len(selected) > 2:
        return f"{len(selected)} agents selected"
    names = [name for identifier, name in AGENTS if identifier in selected]
    return ", ".join(names) or "No agents selected"
