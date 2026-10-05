# Using the TUI

Launch `sky` inside a project, or pass `--project`. The app reads that project's `skills-lock.json` and your global lock. The summary shows visible skills, selected skills, and outdated skills. Press **L** or choose **Activity** to read operations and full error details. Press **?** or **F1** for help that explains each action.

## Inspect installed skills

Move through rows with the arrow keys. Each row shows the skill and source, with status and scope alongside. **Details** shows the source, branch, status and agents; **Metadata** holds paths, raw lock fields and SKILL.md frontmatter. Action buttons underline their keyboard shortcut; when the key is absent from the action name, it appears after the label.

Choose **Read skill** or press **V** to open the formatted **SKILL.md** preview. Use the mouse wheel, arrows, Page Up/Down or Home/End to scroll. YAML frontmatter is separated from the instructions so it is not rendered as a Markdown heading. Tab and Shift+Tab move between controls; Escape returns focus to the list.

At widths below 120 columns the library and inspector share one pane. **V** opens the inspector and Escape returns to the library. The minimum terminal size is **80 × 24**; below that, Sky asks you to resize. Theme colors adapt when you switch themes through the command palette. UTF-8 is required; mouse and color are enhancements. Arabic/mixed-direction display depends on the terminal's shaping and bidirectional support. For plain or screen-reader-friendly output use `sky list` or `sky list --json`.

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
| B | Open the source field to browse new skills |
| V | Read the highlighted skill; Escape returns to the list |
| L | Open activity and error details |
| ? or F1 | Explain controls and shortcuts |
| D | Review removal of selected skills, or the highlighted skill |
| R | Reload locks and installation locations |
| Q | Quit after an operation finishes |

Selections survive filtering. The count includes hidden selected rows, and operations apply to the entire selection. Library and catalog selections are kept separately. **Select source** respects the current filter and scope; clear filters to select every skill from a location. At narrow widths Activity and Help remain available through **L** and **?**, keeping the action row visible.

## Browse and bulk install

Choose **Add skills** (B), then enter an `owner/repo`, a repository URL, a branch-qualified source such as `owner/repo#release/v1`, or a local path. Press Enter or click **Browse** to load the upstream catalog. Select multiple rows, or press A to select the whole catalog.

Choose **Install…** to open installation settings. Choose the target project/global scope, select **Choose agents…**, and choose whether to copy files instead of linking. The dialog explains both modes. Install batches selected names by source and scope. Cancel or Escape leaves installations unchanged.

The agent picker shows the supported targets from the managed CLI. Codex, GitHub Copilot, Cursor, Claude Code, Gemini CLI, and OpenCode appear first, followed by a subtle divider and the remaining agents alphabetically. Search matches display names and identifiers; selections survive filtering. Press **Down** from search to enter the list, use **↑ / ↓** to move and **Space / Enter** to toggle. **Select all 79** and **Clear** apply to the entire catalogue, including hidden rows. Selecting all asks upstream to install for every supported agent, even agents absent from this machine.

**Use selection** confirms the agents and saves them as your default for subsequent installations, updates, restores, and future Sky launches across projects. It does not install anything. Cancel or Escape in the picker preserves your previous default. The initial default is Codex. Sky stores only agent defaults in its user configuration directory (`~/.config/sky/preferences.json` on Linux, respecting `XDG_CONFIG_HOME`); scope and copy mode remain session settings. These preferences do not modify upstream skill locks.

After installation, the library reloads from upstream's newly written lock. Missing tracked installations can be restored with **Restore…** in the library. This restores from the recorded source/ref; a lock hash is not a commit pin, so it installs the current source content rather than guaranteeing byte-for-byte historical reproduction.

## Check and update

Checking compares the source with the installed lock hash. It does not change files or locks. It fetches one snapshot for each source/ref, compares the whole folder including supporting files, and marks moved skills outdated. Git sources require Git; existing Git credentials and explicit environment settings pass through to upstream operations.

**Update** opens installation settings, then reinstalls selected skills from their recorded sources and refs through `skills add`, refreshing upstream's locks. It uses your saved agent defaults and the copy setting you choose in that dialog. Those settings are explicit because the lock does not fully record installation mode or agent placement. Existing links to other agents are not removed; independent copies for other agents may need their own update. Confirmed removed skills are excluded from updating.

## Remove

Removal lists the names and scopes in a review dialog. Cancel or Escape leaves them unchanged. Confirming delegates removal of those skills and agent links to upstream. Project/global scope stays explicit, and unrelated skills remain installed. The app never treats a failed update check as permission to remove a skill.

Operations run in background workers while the app stays responsive. Mutation buttons are disabled during an operation. Subprocesses have time limits and are terminated on cancellation. The activity log reports partial failures; Refresh reloads actual state from the locks.
