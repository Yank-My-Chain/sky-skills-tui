"""Focused dialogs for installation settings, help, and operation history."""

from dataclasses import dataclass

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Markdown, RichLog, Select, Static

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


class InstallScreen(ModalScreen[InstallOptions | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, names: list[str], options: InstallOptions, *, catalog: bool, update: bool):
        super().__init__()
        self.names, self.options, self.catalog = names, options, catalog
        self.verb = "Update" if update else ("Install" if catalog else "Restore")

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
                yield Label("Target agents · separate names with spaces")
                yield Input(
                    value=self.options.agents, placeholder="codex claude-code cursor", id="agents"
                )
                yield Checkbox("Copy files instead of linking", value=self.options.copy, id="copy")
                yield Static(
                    "Links share one installation. Copies are independent.", classes="muted"
                )
                yield Static("", id="install-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield Button(shortcut_label("Cancel · Esc", "Esc"), id="cancel")
                yield Button(self.verb, id="apply-install", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#target-scope" if self.catalog else "#agents").focus()

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#apply-install")
    @on(Input.Submitted, "#agents")
    def apply(self) -> None:
        agents = self.query_one("#agents", Input).value.strip()
        names = agents.replace(",", " ").split()
        if not names or any(a.startswith("-") for a in names):
            self.query_one("#install-error", Static).update("Enter valid agent names, e.g. codex.")
            self.query_one("#agents").focus()
            return
        scope = (
            str(self.query_one("#target-scope", Select).value)
            if self.catalog
            else self.options.scope
        )
        self.dismiss(InstallOptions(scope, agents, self.query_one("#copy", Checkbox).value))
