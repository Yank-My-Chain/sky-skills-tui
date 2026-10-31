# Changelog

All notable changes to Sky are documented here. This changelog follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Release tags use `vMAJOR.MINOR.PATCH`. During initial development (`0.x`),
features and breaking changes increment the minor version; fixes increment the
patch version. Breaking changes are explicitly identified in the release notes.
See the [release policy](docs/development.md#releases) for the compatibility
contract and release process.

## [Unreleased]

## [0.3.0] - 2026-10-30

### Changed

- Checking updates fetches up to four sources at once and hashes each source's
  skills with one Node process, so large libraries check much faster. Rows show
  their results as each source finishes.
- Startup and Refresh list project and global installations concurrently.
- Running operations show a spinner, progress, and elapsed time. Rows being
  checked, installed, updated, or removed are marked in the status column.
- Pressing an action key while an operation runs explains why nothing happened
  instead of ignoring the key.
- Escape steps back one level: it leaves the filter or source field, then the
  preview, then cancels a running check, browse, or refresh, and only then
  clears the selection.
- In installation settings, A opens Choose agents. In the agent picker, A and C
  select all and clear while the list has focus; Alt+A and Alt+C still work from
  the search field. macOS terminals type å and ç for Option+A and Option+C.
- Help and Activity log also close with Q, and with the key that opened them.

### Fixed

- Moving through skills with a long SKILL.md preview open no longer freezes the
  interface. Previews render in the background and are cached.
- Selecting rows no longer rebuilds the whole table.
- Q can cancel a check, browse, or refresh and quit, instead of being ignored
  until a slow or unreachable source times out.
- Dialogs also accept Ctrl+J, which some terminals send for Ctrl+Enter.
- Escape in the filter field no longer clears the current selection.
- Tab and Shift+Tab move focus inside dialogs again, and Ctrl+Q and Ctrl+P
  work while a dialog is open. Library shortcuts remain paused behind dialogs.
- Space presses the focused button, as on desktop platforms, so Delete skills
  and other dialog actions can be reached with Tab and Space.

## [0.2.0] - 2026-10-05

### Added

- Searchable agent picker covering all 79 targets supported by skills 1.7.0,
  with selection preserved while filtering and actions to select all or clear.
- Common agents at the top of the picker: Codex, GitHub Copilot, Cursor,
  Claude Code, Gemini CLI, and OpenCode, separated from the alphabetical list.
- Confirmed agent selections saved as the default across Sky launches and
  projects, with Codex used when no valid preference has been saved.

### Changed

- Action buttons underline their keyboard shortcuts, including Escape on
  Cancel and Close buttons.
- Button wording matches its letter shortcut: Browse skills (B), Reinstall (I),
  Delete (D), View skill / Close view (V), and Activity log (L).
- Dialog buttons show Ctrl+Enter / F2 for their primary action, including
  Use selection. Choose agents and Select all use Alt+A; Clear uses Alt+C.

## [0.1.0] - 2026-10-04

Initial release.

### Added

- Terminal skill library driven by project and global npm skills lock files,
  with source grouping, filtering, bulk selection, and installation details.
- Repository and local-path browsing, bulk installation, update checks,
  updates, restoration of missing installations, and reviewed removal.
- Skill content previews, metadata inspection, activity log, keyboard help,
  and a layout that adapts to terminals down to 80 × 24.
- Source health reporting that distinguishes confirmed upstream removals from
  unavailable sources, and safeguards for unsupported lock schemas.
- Managed skills 1.7.0 runtime with bundled Node/npm, unattended setup,
  diagnostics, and text or JSON inventory through the `sky` command.
- Git-tag-derived package versions, installation documentation, and automated
  checks against the published npm CLI.

[Unreleased]: https://github.com/Yank-My-Chain/sky-skills-tui/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Yank-My-Chain/sky-skills-tui/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Yank-My-Chain/sky-skills-tui/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Yank-My-Chain/sky-skills-tui/tree/v0.1.0
