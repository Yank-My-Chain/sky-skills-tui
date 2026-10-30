"""Focused dialogs for installation settings, help, and operation history."""

from collections.abc import Callable
from dataclasses import dataclass

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    Markdown,
    OptionList,
    RichLog,
    Select,
    SelectionList,
    Static,
)
from textual.widgets.selection_list import Selection

from .agents import AGENT_IDS, AGENTS, COMMON_AGENTS, agent_summary, agent_targets, selected_agents
from .presentation import shortcut_label

# Some terminals send Ctrl+J (line feed) for Ctrl+Enter, and others cannot tell
# Ctrl+Enter from Enter at all. F2 works everywhere (Fn+F2 on Mac keyboards).
APPLY_KEYS = "ctrl+enter,ctrl+j,f2"

HELP = """# Using Sky

## Read and select
**↑ / ↓** moves through skills. **Space / Enter** selects a row.
**A** selects or clears all visible rows. **S** selects the highlighted source.
**O** selects outdated skills. **Escape** steps back: from the filter or a preview
it returns to the list, during a check or browse it cancels, and otherwise it clears
the selection. Selections survive filtering; the selected count includes hidden rows.

**/** focuses search. **V · View skill** opens SKILL.md. At narrow widths,
**V · Close view** returns to the list. **Tab / Shift+Tab** moves focus.
In a preview, use **↑ / ↓, Page Up / Page Down, Home / End** or the mouse wheel.
Use the Details, SKILL.md and Metadata tabs to switch views.

## Manage skills
**C · Check updates** compares selected skills with their sources. With no
selection, it checks every visible skill. It does not change installed files.

**U · Update** reinstalls selected skills, or the highlighted skill, from their
recorded sources. **I · Reinstall** restores missing or existing tracked skills.
Both open installation settings so you can choose agents and copy mode.
**A · Choose agents…** opens a searchable checkbox list with common agents first.
**Use selection · Ctrl+Enter / F2** saves agent defaults for future Sky launches;
Escape cancels. In the agent list, **A** selects all agents and **C** clears the
picker; from the search field, use **Alt+A** and **Alt+C**. On macOS, Alt shortcuts
need Option set to act as Meta (Esc+ in iTerm2) in your terminal settings.
**F2** or **Ctrl+Enter** activates the primary action in the current dialog,
including Install, Reinstall, Update and Delete skills. F2 works in every terminal
(Fn+F2 on Mac keyboards); some terminals and tmux treat Ctrl+Enter as plain Enter.
Enter and Space keep their normal behavior on the focused control.

**D · Delete** reviews selected skills (or the highlighted skill) before deletion.
**R · Refresh** reloads lock files and installation locations.

## Browse skills
**B · Browse skills** opens the source field. Enter an owner/repo, Git URL or local
path, then press Enter or Browse. Select skills in the results and choose
**Install**. Choose Project (this project) or Global (all projects) in the dialog.
**Back to library** returns to installed skills.

## Activity and help
The status line shows a spinner and elapsed time while an operation runs. A check
updates each source's rows as soon as that source finishes.

**L · Activity log** opens operation history, including full error details. **?** opens
this help (**F1** too, where the terminal does not reserve it). **Ctrl+P** opens the
command palette, including theme selection. **Escape** or **Q** closes a dialog.
**Q** quits; it cancels a running check, browse or refresh, but waits for installs,
updates and removals to finish.
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,question_mark,f1", "close", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(classes="reader-dialog"):
            with VerticalScroll(id="help-scroll", can_focus=True):
                yield Markdown(HELP)
            yield Button(shortcut_label("Close · Esc", "Esc"), id="close")

    def on_mount(self) -> None:
        self.query_one("#help-scroll").focus()

    @on(Button.Pressed, "#close")
    def action_close(self) -> None:
        self.dismiss(None)


class ActivityScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,l", "close", "Close", show=False)]

    def __init__(self, messages: list[str]) -> None:
        super().__init__()
        self.messages = messages

    def compose(self) -> ComposeResult:
        with Vertical(classes="reader-dialog"):
            yield Label("Activity log", classes="dialog-title")
            yield RichLog(id="activity-log", wrap=True, markup=False, max_lines=300)
            yield Button(shortcut_label("Close · Esc", "Esc"), id="close")

    def on_mount(self) -> None:
        log = self.query_one(RichLog)
        for message in self.messages:
            log.write(Text(message))
        log.focus()

    @on(Button.Pressed, "#close")
    def action_close(self) -> None:
        self.dismiss(None)


@dataclass
class InstallOptions:
    scope: str = "project"
    agents: str = "codex"
    copy: bool = False


class AgentSelectionList(SelectionList[str]):
    """One keyboard list with a disabled, unmarked divider after common targets."""

    DIVIDER = "__common_divider__"

    def render_line(self, y: int) -> Strip:
        index = self.scroll_offset.y + y
        if index < self.option_count and self.get_option_at_index(index).value == self.DIVIDER:
            return OptionList.render_line(self, y)
        return super().render_line(y)


class AgentPickerScreen(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding(APPLY_KEYS, "apply", "Use selection", show=False, priority=True),
        # Alt works from the search field where the terminal sends it; macOS terminals
        # type å and ç by default, so plain letters work whenever search is not focused.
        Binding("alt+a", "select_all_agents", "Select all agents", show=False, priority=True),
        Binding("alt+c", "clear_agents", "Clear agents", show=False, priority=True),
        Binding("a", "select_all_agents", "Select all agents", show=False),
        Binding("c", "clear_agents", "Clear agents", show=False),
    ]

    def __init__(self, agents: str) -> None:
        super().__init__()
        self.targets = selected_agents(agents)
        self.shown: set[str] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="agent-dialog"):
            yield Label("Target agents", classes="dialog-title")
            yield Input(placeholder="Find agent…", id="agent-search")
            yield Static("", id="agent-count", markup=False)
            with Horizontal(id="agent-toolbar"):
                yield Button(shortcut_label(f"Select all {len(AGENTS)}", "a"), id="all-agents")
                yield Button(shortcut_label("Clear", "c"), id="clear-agents")
            yield AgentSelectionList(id="agent-list")
            yield Static("No matching agents.", id="agent-empty")
            yield Static("All includes agents not installed on this machine.", classes="muted")
            with Horizontal(classes="dialog-actions"):
                yield Button(shortcut_label("Cancel · Esc", "Esc"), id="cancel-agents")
                yield Button(
                    shortcut_label("Use selection · Ctrl+Enter / F2", "Ctrl+Enter / F2"),
                    id="use-agents",
                    variant="primary",
                )

    def on_mount(self) -> None:
        self.render_agents()
        self.query_one("#agent-search").focus()

    def render_agents(self) -> None:
        query = self.query_one("#agent-search", Input).value.strip().casefold()
        agents = [(key, name) for key, name in AGENTS if query in f"{key} {name}".casefold()]
        self.shown = {key for key, _ in agents}
        choices = self.query_one("#agent-list", AgentSelectionList)
        selections = [
            Selection(
                name if key != "universal" else "Universal · shared .agents directory",
                key,
                key in self.targets,
            )
            for key, name in agents
        ]
        if not query:
            selections.insert(
                len(COMMON_AGENTS),
                Selection(Text("─" * 54, style="dim"), AgentSelectionList.DIVIDER, disabled=True),
            )
        with choices.prevent(SelectionList.SelectedChanged):
            choices.clear_options()
            choices.add_options(selections)
        choices.highlighted = 0 if agents else None
        self.query_one("#agent-empty").display = not agents
        self.update_count()

    def update_count(self) -> None:
        shown = len(self.shown)
        description = (
            f"{len(AGENTS)} available · common agents first"
            if shown == len(AGENTS)
            else f"{shown} of {len(AGENTS)} shown"
        )
        self.query_one("#agent-count", Static).update(
            f"{len(self.targets)} selected · {description}"
        )
        self.query_one("#use-agents", Button).disabled = not self.targets

    @on(Input.Changed, "#agent-search")
    def filter_agents(self) -> None:
        self.render_agents()

    def on_key(self, event: Key) -> None:
        agents = self.query_one("#agent-list", AgentSelectionList)
        if event.key == "down" and self.query_one("#agent-search").has_focus and self.shown:
            agents.focus()
        elif event.key == "up" and agents.has_focus and not agents.highlighted:
            self.query_one("#agent-search").focus()
        else:
            return
        event.stop()
        event.prevent_default()

    @on(SelectionList.SelectedChanged, "#agent-list")
    def selection_changed(self) -> None:
        self.targets.difference_update(self.shown)
        self.targets.update(self.query_one("#agent-list", AgentSelectionList).selected)
        self.targets.intersection_update(AGENT_IDS)
        self.update_count()

    @on(Button.Pressed, "#all-agents")
    def action_select_all_agents(self) -> None:
        self.targets = set(AGENT_IDS)
        self.render_agents()

    @on(Button.Pressed, "#clear-agents")
    def action_clear_agents(self) -> None:
        self.targets.clear()
        self.render_agents()

    @on(Button.Pressed, "#cancel-agents")
    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#use-agents")
    def action_apply(self) -> None:
        if self.targets:
            self.dismiss(agent_targets(self.targets))


class InstallScreen(ModalScreen[InstallOptions | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding(APPLY_KEYS, "apply", "Apply installation", show=False, priority=True),
        # This dialog has no text field, so the plain letter works on every keyboard.
        Binding("a,alt+a", "choose_agents", "Choose agents", show=False),
    ]

    def __init__(
        self,
        names: list[str],
        options: InstallOptions,
        *,
        catalog: bool,
        update: bool,
        on_agents_chosen: Callable[[str], None] | None = None,
    ):
        super().__init__()
        self.names, self.options, self.catalog = names, options, catalog
        self.verb = "Update" if update else ("Install" if catalog else "Reinstall")
        self.agents = options.agents
        self.on_agents_chosen = on_agents_chosen

    def compose(self) -> ComposeResult:
        with Vertical(id="install-dialog"):
            yield Label(f"{self.verb} {len(self.names)} skill(s)", classes="dialog-title")
            with VerticalScroll(id="install-fields", can_focus=True):
                yield Static(", ".join(self.names), id="install-names", markup=False)
                if self.catalog:
                    yield Label("Install scope")
                    yield Select(
                        [
                            ("Project · this project", "project"),
                            ("Global · all projects", "global"),
                        ],
                        value=self.options.scope,
                        allow_blank=False,
                        id="target-scope",
                    )
                else:
                    yield Static("Uses each skill's recorded source and scope.", classes="muted")
                yield Label("Target agents")
                with Horizontal(id="agent-summary-row"):
                    yield Static(agent_summary(self.agents), id="agent-summary", markup=False)
                    yield Button(shortcut_label("Choose agents…", "a"), id="choose-agents")
                yield Checkbox("Copy files instead of linking", value=self.options.copy, id="copy")
                yield Static(
                    "Links share one installation. Copies are independent.", classes="muted"
                )
                yield Static("", id="install-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield Button(shortcut_label("Cancel · Esc", "Esc"), id="cancel")
                yield Button(
                    shortcut_label(f"{self.verb} · Ctrl+Enter / F2", "Ctrl+Enter / F2"),
                    id="apply-install",
                    variant="primary",
                )

    def on_mount(self) -> None:
        self.query_one("#target-scope" if self.catalog else "#choose-agents").focus()

    @on(Button.Pressed, "#choose-agents")
    def action_choose_agents(self) -> None:
        def chosen(agents: str | None) -> None:
            if agents is not None:
                self.agents = agents
                self.query_one("#agent-summary", Static).update(agent_summary(agents))
                if self.on_agents_chosen is not None:
                    self.on_agents_chosen(agents)
            self.query_one("#choose-agents").focus()

        self.app.push_screen(AgentPickerScreen(self.agents), chosen)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#apply-install")
    def action_apply(self) -> None:
        if not selected_agents(self.agents):
            self.query_one("#install-error", Static).update("Choose at least one target agent.")
            self.query_one("#choose-agents").focus()
            return
        scope = (
            str(self.query_one("#target-scope", Select).value)
            if self.catalog
            else self.options.scope
        )
        self.dismiss(InstallOptions(scope, self.agents, self.query_one("#copy", Checkbox).value))
