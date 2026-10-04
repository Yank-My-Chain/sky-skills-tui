# Locks and upstream compatibility

The managed and tested release is **npm skills 1.7.0**. Upstream is actively developed, so compatibility is a tested boundary rather than an assumption about its latest code. An unverified release is rejected by the normal runtime. A managed installation whose version differs from the supported release is reported explicitly; `sky setup --upgrade` repairs it.

During development, 1.6.0 also passed the local CLI contract suite as a candidate, while 1.5.0 failed both lifecycle contracts because `add --json` did not produce the expected JSON array. Only 1.7.0 is declared supported; probing a candidate does not automatically enable it for normal use.

## Lock files

| Scope | Location | Schema | Hash |
| --- | --- | --- | --- |
| Project | `<project>/skills-lock.json` | 1 | `computedHash`, SHA-256 of folder paths and file bytes |
| Global | `~/.agents/.skill-lock.json` | 3 | `skillFolderHash`, GitHub tree SHA or source folder SHA-256 |
| Global with XDG | `$XDG_STATE_HOME/skills/.skill-lock.json` | 3 | Same as above |

These are the [upstream project](https://github.com/vercel-labs/skills/blob/main/src/local-lock.ts) and [global](https://github.com/vercel-labs/skills/blob/main/src/skill-lock.ts) formats. Published-package contract tests define the supported behavior, since `main` can contain changes not yet published.

The app reads these files without writing them. All installation, update and removal writes belong to npm `skills`. Unknown metadata remains available in the viewer. Invalid files produce visible warnings. Old/future schemas remain readable where possible and block mutation, preventing upstream's old-global-lock migration from silently discarding entries. No automatic migration is attempted.

Lock entries are authoritative for provenance. Untracked installed folders are not silently added to the library or assigned an inferred source. A lock entry can remain visible even when files are missing.

## Status meanings

| Status | Meaning |
| --- | --- |
| unchecked | No source comparison has run during this session |
| current | Source folder matches the locked hash |
| outdated | Folder contents or recorded location changed |
| removed upstream | A readable source no longer contains the skill, or a recorded local source is gone |
| source unavailable | Clone/read failed; remote removal, privacy, authentication and offline access cannot be distinguished |
| unverifiable | Insufficient metadata, ambiguous source/name, unsafe recorded path, or unsupported provider |

The tool cannot infer a maintainer's declared deprecation policy: **removed upstream** means the skill disappeared from a confirmed readable source. GitHub 404s can also mean a private repository, so they are not treated as confirmed deletion. Checks preserve refs and group by both source and ref to avoid falsely marking a skill deleted on another branch.

Source hashes are compared with upstream's algorithm. A small bundled Node helper preserves JavaScript `localeCompare` path ordering for SHA-256 hashes. Global GitHub entries with a 40-character tree SHA use the repository's Git tree object; 64-character hashes use file content. Checks clone Git sources into a temporary directory and remove it afterward. No lock or installation directory is changed by checking.

## Source support and limits

Installation scope and source type are separate choices. **Project** scope installs into the current project and records `skills-lock.json`; **global** scope installs into your user directories and records the global `.skill-lock.json`. Either scope can use a Git repository as its source. A **local-path source** is a folder on disk, such as `./my-skills`, regardless of where its files are installed.

In the published `skills` 1.7.0 package, `skills add ./my-skills --global` can install files but does not write a global lock entry. Its global lock-writing branch requires a normalized repository source identifier, which a local folder lacks. The project lock-writing branch does not have that requirement, so `skills add ./my-skills` records the source and folder hash correctly. This behavior is visible in the [1.7.0 install implementation](https://github.com/vercel-labs/skills/blob/v1.7.0/src/add.ts) and covered by Sky's live contracts.

Sky blocks **local-path source + global scope** before installation because an untracked installation would lack the upstream provenance needed to manage it. This restriction does not apply to Git-based global installs or local-path project installs. An upstream fix can remove it once the new release passes the compatibility contracts.

| Source | Browse/install | Check |
| --- | --- | --- |
| GitHub repositories | Yes, project/global | Folder hashes and refs; public tree SHA covered by network contract |
| GitLab/generic Git | Yes when the original URL is available | Folder hash and ref |
| Local directories | Project scope | Folder hash; missing local source detected |
| Global local directories | Blocked in 1.7.0 because no global lock is generated | Existing compatible lock entries can be read |
| Well-known skill sites | Upstream listing/install; only successfully locked entries count as managed | Unverifiable in this version |
| Direct downloads / archives | Upstream can install, but may not generate a lock; reported as unsupported management | Unverifiable |
| `node_modules` entries | Existing lock entries displayed | Unverifiable; use upstream experimental sync directly |

Legacy generic-Git/GitLab entries with only `owner/repo` and no original URL are blocked for reinstall and unverifiable for checks: choosing GitHub would reinterpret their source. Duplicate names without a usable path are unverifiable. Plugin-scoped naming can differ between catalog results and lock keys; a mismatch is reported as a compatibility error rather than claiming successful tracking. Commit-SHA refs unsupported by upstream's shallow branch clone remain unavailable for checks.

Agent placement comes from `skills list --json` and may omit universal consumers that need no separate link. The lock itself does not fully describe agent targets, installation mode, or independent copies; choose these explicitly when reinstalling. Automatic update checks, persistent status caches, provider-specific website digests, and cross-project recursive scanning are not implemented.

## Contract coverage

The boundary in `upstream.py` validates JSON arrays, result status, required fields, scopes, and agent lists. `parse_available` is isolated because upstream explicitly rejects `--list --json`. Its ANSI/Unicode text structure is covered by fast fixtures and by the real CLI.

Live tests exercise `--version`, `add --list --full-depth`, `add --skill … --agent … --yes --json`, project/global and copy flags, `list --json`, and `remove … --yes`. They assert lock versions, keys, hashes, source URLs, refs, actual installed content, symlink behavior, error exits, update isolation, restore behavior, and disappearance. A Textual Pilot test drives the whole UI lifecycle against the real binary.

Run a candidate without changing supported versions:

```bash
uv run pytest --integration --skills-version 1.7.0
uv run pytest --integration --network --skills-version 1.7.0
```

The option requires an exact release version. Candidate runtimes are installed in separate pytest cache directories and allowed only by the test harness. See [development](development.md) for the release process and scheduled compatibility workflow.
