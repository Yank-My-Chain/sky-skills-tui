# Exploring global skills from local folders

This investigation lives on `explore/global-local-skills`. It does not enable the feature in Sky's normal runtime. The merged `main` branch continues to use the published npm `skills` 1.7.0 release and its existing compatibility policy.

## Findings

The limitation has already been fixed in upstream source. At upstream commit [`18f96ea131dab3b0fcc9b27cf7c6f6cbb6174680`](https://github.com/vercel-labs/skills/tree/18f96ea131dab3b0fcc9b27cf7c6f6cbb6174680), [`src/add.ts`](https://github.com/vercel-labs/skills/blob/18f96ea131dab3b0fcc9b27cf7c6f6cbb6174680/src/add.ts) permits real local-folder installs in its global lock-writing branch, records the local source path, and computes a SHA-256 folder hash.

The npm registry's latest release remained 1.7.0 when checked on October 4, 2026. The [`v1.7.0` source](https://github.com/vercel-labs/skills/blob/v1.7.0/src/add.ts) and the installed npm bundle require a normalized repository identifier to write the global lock, so local folders are excluded there.

Both the published package and the unreleased checkout report **1.7.0**. The version string alone cannot identify a built checkout. Research reports include the CLI bundle SHA-256 and, when available, the upstream Git commit. The normal app cannot silently substitute an unreleased build under the published package's version.

## Observed behavior

We built the upstream checkout with its locked dependencies and ran a standalone probe in temporary homes and projects. The probe uses the bundled Node executable, invokes the CLI directly, and never changes the user's installed skills or Sky's normal npm prefix.

| Contract | Published npm 1.7.0 | Built upstream checkout |
| --- | --- | --- |
| Install/list global local-folder skill | Works | Works |
| Create the global lock entry | No | Yes, schema v3 |
| Record local provenance | No entry | `sourceType: local`, absolute original source path |
| Match the entire source folder hash | No entry | Yes, 64-character SHA-256 |
| Detect a reference-file-only change | No tracked entry | Yes, Sky's existing checker marks outdated |
| Reinstall and refresh the hash | No tracked entry | Yes |
| Preserve the original installation timestamp | No entry | Yes |
| Restore a deleted canonical installation | Not tracked | Yes |
| Detect a skill deleted from a readable source | No tracked entry | Yes, Sky's existing checker marks removed upstream |
| Remove files, agent links, and lock entry | Removes files | Removes files and tracking |

The checkout passed the full probe in both copy and symlink modes, targeting Codex and Claude Code. This verifies the global local-folder lifecycle, not every upstream checkout behavior or every agent/platform combination. Sky's normal install method still blocks the combination; the probe bypasses that method explicitly for research.

Captured reports: [published npm 1.7.0](published-1.7.0.json) and [the upstream checkout in copy mode](upstream-main-copy.json). The latter records the exact source commit and compiled bundle hash alongside the observed lifecycle results.

## Options

| Approach | Effect on upstream lock ownership | Cost and limits |
| --- | --- | --- |
| Adopt the next published release containing the fix | npm skills creates and updates its own lock | Best fit; requires a release and passing compatibility contracts |
| Package a specific upstream commit or maintained backport | Modified npm skills still owns lock writes | Can work sooner; adds build, distribution, provenance and maintenance responsibilities |
| Add a Sky-only sidecar registry | Original upstream lock stays unchanged | Two sources of state; other skills clients cannot see local provenance; diverges from the requested lock-based model |
| Have Sky write global lock entries after installation | Sky shares ownership of upstream's lock | Must handle schema drift, concurrent writers, atomic writes, timestamps and partial failures; changes the current ownership contract |
| Mirror local skills into a Git repository | Upstream tracks the Git source | Works with the published package, but changes provenance and requires committing each update; does not directly manage the original folder |

Prefer the first option. The fix already exists upstream and Sky's existing reader and health checker understand the entries it produces. If immediate availability is essential, a commit-pinned upstream package/backport is the closest alternative; make its identity explicit and run the complete compatibility suite before enabling it. Do not patch whichever `skills` binary happens to be on PATH or silently write lock entries in the normal app.

## Integration plan

1. Identify a published npm release containing the upstream fix and run the global local-folder probe with `--require-lock`.
2. Run all CLI compatibility contracts, including the GitHub tree-hash case, against that exact release.
3. Declare global local-folder tracking as a capability of the tested release. Replace the unconditional local/global guard with that capability check, retaining the guard for releases that lack it.
4. Add a complete Textual Pilot loop for global local-folder browse → install → check → edit reference → update → restore → remove, for copy and symlink modes.
5. Extend global local tests for default-home and XDG lock locations, sources containing multiple skills, direct skill-folder sources, relative source arguments, folder moves, failed installs and name collisions.
6. Update the runtime pin and docs after those contracts pass. The checker can continue reading both Git-backed and local entries from the same upstream global lock.

Local source paths are machine-specific. Moving or deleting the source should make the recorded local skill unavailable/removed until the user chooses a new source. Installation copies the source into the canonical skills directory; an agent symlink points to that canonical installation, not to the original folder, so source edits still need an explicit update.

## Already installed untracked skills

A future upstream release cannot recover provenance that was never recorded. Existing global copies can be found using `skills list --global --json`, but their original folders cannot be inferred reliably from copied content.

A separate adoption flow should show these as **untracked**, let the user choose the original local folder, discover and match the named skill, and reinstall through the supported CLI so it creates a real lock entry. Identical bytes can suggest a candidate but do not prove origin. Never silently assign a source or rename an unrelated skill with the same name.

Do not reinstall from an installation directory into itself or from an overlapping canonical/agent directory. The adoption flow needs an explicit path-overlap check to avoid a copy operation deleting its own source. Manually authored skills with no separate source folder need a separate policy decision; the upstream release fix alone does not address them.

## Reproduce

Probe the published package without enabling it in Sky:

```bash
uv run python scripts/probe_global_local.py --skills-version 1.7.0
# Returns nonzero for this release because tracking is absent:
uv run python scripts/probe_global_local.py --skills-version 1.7.0 --require-lock
```

Build the exact upstream checkout:

```bash
git clone https://github.com/vercel-labs/skills.git /tmp/skills-global-local
git -C /tmp/skills-global-local checkout 18f96ea131dab3b0fcc9b27cf7c6f6cbb6174680
uv run npx --yes pnpm@10.17.1 --dir /tmp/skills-global-local install --frozen-lockfile --ignore-scripts
uv run npx --yes pnpm@10.17.1 --dir /tmp/skills-global-local build
uv run python scripts/probe_global_local.py --cli /tmp/skills-global-local/bin/cli.mjs --require-lock
uv run python scripts/probe_global_local.py --cli /tmp/skills-global-local/bin/cli.mjs --copy --require-lock
```

Run the exploratory pytest contracts:

```bash
uv run pytest --integration --global-local-cli /tmp/skills-global-local/bin/cli.mjs tests/test_global_local_probe.py
```

The published-release contract deliberately asserts that global local tracking is absent. If a candidate release starts generating the lock, that test fails with a message to revisit Sky's policy. The built-checkout contracts are opt-in and require the complete tracked lifecycle to work; they never make the checkout a supported production release.
