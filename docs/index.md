# Sky

Sky brings installed skill management into a terminal interface. It wraps the published npm `skills` CLI and reads the lock files that CLI already generates.

The library shows each skill's source, scope, ref, locked hash, installation path, agent links, and update status. The details pane preserves all lock metadata, and its **SKILL.md** tab reads the installed instructions.

Use a source catalog to discover a repository's skills without installing them. Select several, select a whole source, or select every visible row, then install them together. Project and global installations have separate identities even when their skill names match.

```bash
uv tool install 'git+https://github.com/Yank-My-Chain/sky-skills-tui.git'
sky
```

Start with [installation](installation.md), then [the TUI guide](usage.md). The [compatibility guide](compatibility.md) describes which sources support checks, how deprecation is determined, and how upstream changes are detected.
