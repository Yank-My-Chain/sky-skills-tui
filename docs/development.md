# Development and verification

```bash
uv sync
uv run hatch run check
uv run hatch run integration
uv run hatch run docs
uv run hatch build
```

The package uses Hatchling for wheel/sdist builds, Hatch environments configured with `installer = "uv"`, and a checked-in uv lock. Ruff checks and formats Python, ty checks types, and pytest runs unit and Pilot tests. CSS and the hash helper ship inside the wheel.

## Test layers

Fast tests run with `uv run pytest`: lock loading and drift protection, source/ref handling, JSON and text adapters, health states, process cancellation, selection, filtering, source grouping, failure recovery, confirmation cancellation, and terminal sizes of 80×24 and 140×45. npm lifecycle tests are skipped unless explicitly enabled.

`uv run pytest --integration` installs the real npm package in a dedicated cache. Every lifecycle gets temporary project/home/XDG/agent directories. A local smart-HTTP Git server hosts deterministic fixtures, supports shallow clones and refs, and avoids reliance on a public repository for the main contracts. Tests commit reference-only updates and skill removal, then verify actual hashes and state.

`uv run pytest --integration --network` adds a public GitHub source to test global 40-character tree SHAs. This test requires GitHub and npm connectivity. It intentionally fails if upstream tracking or public fixtures change, so investigate the failure rather than masking it as a skip.

Textual's `App.run_test()` and Pilot perform the complete browse → select all → install → check → change source → update → check → confirm removal loop against the real CLI. See [Textual testing](https://textual.textualize.io/guide/testing/).

## Detect upstream drift

`.github/workflows/compatibility.yml` runs supported-version contracts on changes and weekly. A separate scheduled/manual candidate job queries npm's latest release and probes it. It does not change the application's supported-version declaration. Failures identify the command, result schema, lock behavior, or lifecycle assumption that changed; CI retains JUnit XML reports.

To reproduce locally:

```bash
npm view skills version
uv run pytest --integration --skills-version X.Y.Z --junitxml=compatibility.xml
```

Before supporting a release:

1. Probe the exact published npm version and investigate all failures.
2. Update the adapters for intentional changes and add regression fixtures.
3. Run the full fast, live, and GitHub suites against that version.
4. Update `SKILLS_VERSION` and `SUPPORTED_VERSIONS` in `runtime.py`, and the documented compatibility limits.
5. Build wheel and sdist, install the wheel with `uv tool install`, run `sky setup`, `sky doctor`, and the TUI.

Normal runtime use never opts into unverified versions. Tests opt in explicitly with `allow_unverified=True`, isolating their npm prefix by version.

## Architecture

`models.py` reads upstream locks. `runtime.py` prepares the private npm package and runs bounded subprocesses. `upstream.py` validates the JSON boundary. `service.py` groups operations and compares source snapshots. `app.py` renders the library and catalogs, keeps selections by scope/name, and runs service operations as Textual workers. `cli.py` exposes launch, setup, list and diagnostics.

Mutation operations are serialized within the app. npm preparation also uses a cross-process file lock. Upstream skill mutations do not offer transactional multi-source writes: earlier groups may succeed if a later group fails, so the UI reports the error and reloads locks. Avoid concurrent mutation from multiple CLI/app instances.

Checks run discovered-skill scanning in a worker thread, while Git/npm subprocesses run asynchronously. Subprocess cancellation terminates the process group on POSIX. npm install uses `--ignore-scripts`, and upstream telemetry is disabled for managed invocations.

## Documentation

Zensical configuration lives in `zensical.toml`:

```bash
uv run hatch run docs
uv run hatch run serve-docs
```

Built HTML is written to `site/`. The documentation build is checked in CI. Zensical setup is documented in its [official configuration guide](https://zensical.org/docs/setup/basics/).
