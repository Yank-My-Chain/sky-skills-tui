"""Focused dialogs for installation settings, help, and operation history."""

from collections.abc import Callable
from dataclasses import dataclass

from rich.text import Text
from textual import on
from textual.app import ComposeResult
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

HELP = """# Using Sky

## Read and select
**↑ / ↓** moves through skills. **Space / Enter** selects a row.
**A** selects or clears all visible rows. **S** selects the highlighted source.
**O** selects outdated skills. **Escape** clears selection or returns to the list.
Selections survive filtering; the selected count includes hidden rows.

**/** focuses search. **V** opens SKILL.md. **Tab / Shift+Tab** moves focus.
In a preview, use **↑ / ↓, Page Up / Page Down, Home / End** or the mouse wheel.
Use the Details, SKILL.md and Metadata tabs to switch views.

## Manage skills
**C · Check updates** compares selected skills with their sources. With no
selection, it checks every visible skill. It does not change installed files.

**U · Update** reinstalls selected skills, or the highlighted skill, from their
recorded sources. **I · Restore** reinstalls missing or existing tracked skills.
Both open installation settings so you can choose agents and copy mode.
**Choose agents…** opens a searchable checkbox list with common agents first.
**Use selection** saves agent defaults for future Sky launches; Escape cancels.

**D · Remove** reviews selected skills (or the highlighted skill) before removal.
**R · Refresh** reloads lock files and installation locations.

## Add skills
**B · Add skills** opens the source field. Enter an owner/repo, Git URL or local
path, then press Enter or Browse. Select skills in the results and choose
**Install**. Choose Project (this project) or Global (all projects) in the dialog.
**Back to library** returns to installed skills.

## Activity and help
**L** opens operation history, including full error details. **? / F1** opens
this help. **Ctrl+P** opens the command palette, including theme selection.
**Escape** closes a dialog. **Q** quits after an operation finishes.
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close")]

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
    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, messages: list[str]) -> None:
        super().__init__()
        self.messages = messages

    def compose(self) -> ComposeResult:
        with Vertical(classes="reader-dialog"):
            yield Label("Activity", classes="dialog-title")
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
    BINDINGS = [("escape", "cancel", "Cancel")]

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
                yield Button(f"Select all {len(AGENTS)}", id="all-agents")
                yield Button("Clear", id="clear-agents")
            yield AgentSelectionList(id="agent-list")
            yield Static("No matching agents.", id="agent-empty")
            yield Static("All includes agents not installed on this machine.", classes="muted")
            with Horizontal(classes="dialog-actions"):
                yield Button(shortcut_label("Cancel · Esc", "Esc"), id="cancel-agents")
                yield Button("Use selection", id="use-agents", variant="primary")

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
        if event.key == "down" and self.query_one("#agent-search").has_focus and self.shown:
            self.query_one("#agent-list").focus()
            event.stop()
            event.prevent_default()

    @on(SelectionList.SelectedChanged, "#agent-list")
    def selection_changed(self) -> None:
        self.targets.difference_update(self.shown)
        self.targets.update(self.query_one("#agent-list", AgentSelectionList).selected)
        self.targets.intersection_update(AGENT_IDS)
        self.update_count()

    @on(Button.Pressed, "#all-agents")
    def select_all_agents(self) -> None:
        self.targets = set(AGENT_IDS)
        self.render_agents()

    @on(Button.Pressed, "#clear-agents")
    def clear_agents(self) -> None:
        self.targets.clear()
        self.render_agents()

    @on(Button.Pressed, "#cancel-agents")
    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#use-agents")
    def apply(self) -> None:
        if self.targets:
            self.dismiss(agent_targets(self.targets))


class InstallScreen(ModalScreen[InstallOptions | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

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
        self.verb = "Update" if update else ("Install" if catalog else "Restore")
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
                    yield Button("Choose agents…", id="choose-agents")
                yield Checkbox("Copy files instead of linking", value=self.options.copy, id="copy")
                yield Static(
                    "Links share one installation. Copies are independent.", classes="muted"
                )
                yield Static("", id="install-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield Button(shortcut_label("Cancel · Esc", "Esc"), id="cancel")
                yield Button(self.verb, id="apply-install", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#target-scope" if self.catalog else "#choose-agents").focus()

    @on(Button.Pressed, "#choose-agents")
    def choose_agents(self) -> None:
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
    def apply(self) -> None:
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
