# Installation

Requirements: Python 3.11 or later, [uv](https://docs.astral.sh/uv/), and Git for repository sources. Supported deployment targets are platforms with a compatible `nodejs-wheel` binary wheel. The end-to-end suite is exercised on Linux; other platforms can run the same contracts before deployment.

From a checkout:

```bash
uv tool install .
sky-skills
```

From a built wheel:

```bash
uv tool install dist/sky_skills_tui-0.1.0-py3-none-any.whl
```

From a Git repository, use `uv tool install 'git+https://HOST/OWNER/sky-skills-tui.git'`, replacing the URL with your checkout's remote. This project is not yet published to PyPI.

`uv tool install` installs the Python app together with Node and npm as dependencies. On first launch, the app installs and verifies npm `skills` in its private data directory. Python wheel installers do not run npm post-install hooks, so runtime preparation happens automatically at launch, or explicitly with:

```bash
sky-skills setup
```

Preparation needs access to the npm registry. Once prepared, viewing the library works offline. Browsing local sources and checking them also work offline. Remote operations need access to their source. Preparation failures appear in the activity log and can be retried after correcting the connection.

The managed npm directory follows platformdirs: typically `~/.local/share/sky-skills-tui/npm` on Linux. It is separate from agent skill folders and from global npm packages. Removing the Python tool does not remove your installed skills.

## Updates and diagnostics

```bash
uv tool upgrade sky-skills-tui
sky-skills setup --upgrade
sky-skills doctor
```

The Python upgrade command applies once the tool has a resolvable package source; reinstall a newly built wheel or checkout during development. `setup --upgrade` installs or repairs the release supported by this app version. It deliberately uses the tested version rather than whichever npm release happens to be latest. An app release advances that version after its compatibility contracts pass.

Use `sky-skills --project /path/to/project` to select a project's lock and installation directory. Global skills use the current user's home. `XDG_STATE_HOME/skills/.skill-lock.json` overrides the default global lock path, exactly as upstream does. Agent environment overrides, including `CODEX_HOME` and `CLAUDE_CONFIG_DIR`, are passed to the CLI.
