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

[Unreleased]: https://github.com/Yank-My-Chain/sky-skills-tui/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Yank-My-Chain/sky-skills-tui/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Yank-My-Chain/sky-skills-tui/tree/v0.1.0
