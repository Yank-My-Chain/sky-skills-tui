# Using the TUI

Launch `sky` inside a project, or pass `--project`. The app reads that project's `skills-lock.json` and your global lock. The summary shows visible skills, selected skills, and outdated skills. The activity log records operations and errors.

## Inspect installed skills

Move through rows with the arrow keys. The details pane shows source, provider, ref, status, lock file, path, agent links, timestamps where available, and all other recorded metadata. Open **SKILL.md** to read installed instructions.

Use the scope selector and text filter to narrow the library. Filtering matches names, sources, statuses, and agent display names. A tracked skill with no canonical installation is marked **not on disk**; Refresh asks upstream for additional agent-specific paths. Installation data and agent links come from `skills list --json`.

## Select and operate

| Key | Action |
| --- | --- |
| Space or Enter | Toggle the highlighted row |
| A | Toggle selection of all visible rows |
| S | Select visible rows from the highlighted source |
| O | Select visible outdated skills |
| Escape | Clear the current view's selection |
| / | Focus the filter |
| C | Check selected skills, or every visible skill if nothing is selected |
| U | Update selected skills, or the highlighted skill |
| I | Install or restore selected skills, or the highlighted skill |
| B | Browse the entered source; if empty, use the highlighted skill's source |
| D | Review removal of selected skills, or the highlighted skill |
| R | Reload locks and installation locations |
| Q | Quit after an operation finishes |

Selections survive filtering. The count includes hidden selected rows, and operations apply to the entire selection. Library and catalog selections are kept separately. **Select source** respects the current filter and scope; clear filters to select every skill from a location. Action buttons are horizontally scrollable on narrow terminals.

## Browse and bulk install

Enter an `owner/repo`, a repository URL, a branch-qualified source such as `owner/repo#release/v1`, or a local path. Click **Browse source** to load the upstream catalog. Select multiple rows, or press A to select the whole catalog.

Choose the target project/global scope, supply upstream agent identifiers such as `codex claude-code cursor`, and choose whether to copy files. **Install / restore** batches selected names by source and scope. The default target is Codex. An explicit `*` agent target asks upstream to install to all supported agents.

After installation, the library reloads from upstream's newly written lock. Missing tracked installations can be restored with the same button. This restores from the recorded source/ref; a lock hash is not a commit pin, so it installs the current source content rather than guaranteeing byte-for-byte historical reproduction.

## Check and update

Checking compares the source with the installed lock hash. It does not change files or locks. It fetches one snapshot for each source/ref, compares the whole folder including supporting files, and marks moved skills outdated. Git sources require Git; existing Git credentials and explicit environment settings pass through to upstream operations.

**Update** reinstalls selected skills from their recorded sources and refs through `skills add`, refreshing upstream's locks. It uses the agent targets and copy setting currently shown in the TUI. Those settings are explicit because the lock does not fully record installation mode or agent placement. Existing links to other agents are not removed; independent copies for other agents may need their own update. Confirmed removed skills are excluded from updating.

## Remove

Removal lists the names and scopes in a review dialog. Cancel or Escape leaves them unchanged. Confirming delegates removal of those skills and agent links to upstream. Project/global scope stays explicit, and unrelated skills remain installed. The app never treats a failed update check as permission to remove a skill.

Operations run in background workers while the app stays responsive. Mutation buttons are disabled during an operation. Subprocesses have time limits and are terminated on cancellation. The activity log reports partial failures; Refresh reloads actual state from the locks.
