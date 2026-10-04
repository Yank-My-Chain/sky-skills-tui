"""Keyboard-first Textual interface for managing locked and available skills."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Markdown,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from .models import Skill, Status
from .runtime import SKILLS_VERSION
from .service import SkillsService


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label("Review removal", id="confirm-title")
            yield Static(self.message, markup=False)
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Remove skills", id="confirm", variant="error")

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class SkillsApp(App[None]):
    TITLE = "Sky Skills"
    SUB_TITLE = "Your skills, their sources, one place"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("space", "toggle_skill", "Select"),
        Binding("a", "select_all", "Select visible"),
        Binding("s", "select_source", "Select source"),
        Binding("c", "check", "Check"),
        Binding("u", "update", "Update"),
        Binding("r", "refresh", "Refresh"),
        Binding("b", "browse", "Browse", show=False),
        Binding("i", "install", "Install", show=False),
        Binding("d", "remove", "Remove", show=False),
        Binding("o", "select_outdated", "Select outdated", show=False),
        Binding("slash", "search", "Filter"),
        Binding("escape", "clear_selection", "Clear", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, service: SkillsService, *, bootstrap: bool = True) -> None:
        super().__init__()
        self.service = service
        self.bootstrap = bootstrap
        self.skills: list[Skill] = []
        self.available: list[Skill] = []
        self.visible_skills: list[Skill] = []
        self.selected: set[str] = set()
        self.available_selected: set[str] = set()
        self.busy = False
        self.catalog = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="workspace"):
            with Horizontal(id="intro"):
                yield Static("SKILL LIBRARY", id="library-title")
                yield Static(str(self.service.project), id="project-path", markup=False)
            with Horizontal(id="filters"):
                yield Select(
                    [("All scopes", "all"), ("Project", "project"), ("Global", "global")],
                    value="all",
                    allow_blank=False,
                    id="scope",
                )
                yield Input(placeholder="Filter name, source, status or agent…", id="filter")
                yield Button("Refresh", id="refresh")
            with Horizontal(id="source-bar"):
                yield Input(
                    placeholder="Browse a source: owner/repo, URL or local path", id="source"
                )
                yield Button("Browse source", id="browse", variant="primary")
                yield Button("Library", id="library")
            with Horizontal(id="targets"):
                yield Label("Install to")
                yield Select(
                    [("Project", "project"), ("Global", "global")],
                    value="project",
                    allow_blank=False,
                    id="target-scope",
                )
                yield Input(
                    value="codex", placeholder="Agents, e.g. codex claude-code", id="agents"
                )
                yield Checkbox("Copy files", id="copy")
            yield Static("Loading lock files…", id="summary", markup=False)
            with Horizontal(id="main"):
                with Vertical(id="list-panel"):
                    yield DataTable(id="skills", cursor_type="row", zebra_stripes=True)
                    yield Static("Space selects · A selects visible · S selects source", id="hint")
                with Vertical(id="details-panel"):
                    with TabbedContent():
                        with TabPane("Details", id="details-tab"):
                            with VerticalScroll():
                                yield Static(
                                    "Choose a skill to inspect its origin.",
                                    id="details",
                                    markup=False,
                                )
                        with TabPane("SKILL.md", id="content-tab"):
                            yield Markdown("Select an installed skill to read it.", id="content")
            with HorizontalScroll(id="actions"):
                yield Button("Select visible", id="select-all")
                yield Button("Select source", id="select-source")
                yield Button("Check", id="check")
                yield Button("Install / restore", id="install", variant="primary")
                yield Button("Update", id="update", variant="success")
                yield Button("Remove", id="remove", variant="error")
            yield RichLog(id="log", wrap=True, markup=False, max_lines=300)
            yield Static("Ready", id="operation", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#skills", DataTable).add_columns("", "Skill", "Source", "Scope", "Status")
        self.load_inventory()
        self.query_one("#skills", DataTable).focus()
        if self.bootstrap:
            self.start_operation("Preparing npm skills runtime", self.prepare())

    def on_resize(self, event: Resize) -> None:
        self.screen.set_class(event.size.height < 32, "short")
        self.screen.set_class(event.size.width < 100, "narrow")

    async def prepare(self) -> str:
        version = await self.service.runtime.ensure()
        await self.service.installed(self.skills)
        return f"npm skills {version} ready. Node/npm are managed with this tool."

    def load_inventory(self) -> None:
        previous = {s.key: s for s in self.skills}
        inventory = self.service.inventory()
        self.skills = inventory.skills
        for skill in self.skills:
            old = previous.get(skill.key)
            if old and old.metadata == skill.metadata:
                skill.status, skill.reason = old.status, old.reason
                if old.installed_path and (old.installed_path / "SKILL.md").is_file():
                    skill.agents = old.agents
                    skill.installed_path = old.installed_path
        self.selected.intersection_update(s.key for s in self.skills)
        for warning in inventory.warnings:
            self.activity(warning)
        self.render_rows()

    @property
    def selection(self) -> set[str]:
        return self.available_selected if self.catalog else self.selected

    def focused_skill(self) -> Skill | None:
        table = self.query_one("#skills", DataTable)
        if self.visible_skills and table.cursor_row < len(self.visible_skills):
            return self.visible_skills[table.cursor_row]
        return None

    def chosen(self, *, fallback: bool = True) -> list[Skill]:
        candidates = self.available if self.catalog else self.skills
        result = [s for s in candidates if s.key in self.selection]
        current = self.focused_skill()
        return result or ([current] if fallback and current else [])

    def render_rows(self) -> None:
        table = self.query_one("#skills", DataTable)
        row = table.cursor_row
        table.clear()
        scope = self.query_one("#scope", Select).value
        query = self.query_one("#filter", Input).value.casefold()
        candidates = self.available if self.catalog else self.skills
        self.visible_skills = [
            s
            for s in candidates
            if (
                (self.catalog or scope == "all" or s.scope == scope)
                and query in f"{s.name} {s.source} {s.status} {' '.join(s.agents)}".casefold()
            )
        ]
        colors = {
            Status.CURRENT: "green",
            Status.OUTDATED: "yellow",
            Status.DEPRECATED: "red",
            Status.UNAVAILABLE: "magenta",
        }
        for skill in self.visible_skills:
            state = "available" if self.catalog else str(skill.status)
            if not self.catalog and skill.installed_path is None:
                state += " · not on disk"
            table.add_row(
                Text("✓" if skill.key in self.selection else "○", style="cyan"),
                Text(skill.name),
                Text(skill.source),
                Text(skill.scope),
                Text(state, style=colors.get(skill.status, "dim")),
                key=skill.key,
            )
        if self.visible_skills:
            table.move_cursor(row=min(row, len(self.visible_skills) - 1))
        self.update_summary()
        self.show_details(self.focused_skill())

    def update_summary(self) -> None:
        label = "SOURCE CATALOG" if self.catalog else "INSTALLED SKILLS"
        outdated = sum(s.status == Status.OUTDATED for s in self.skills)
        self.query_one("#summary", Static).update(
            f"{label}   {len(self.visible_skills)} visible   ·   {len(self.selection)} selected"
            f"   ·   {outdated} outdated"
        )
        installed = not self.catalog
        for name in ("check", "update", "remove"):
            self.query_one(f"#{name}", Button).disabled = self.busy or not installed

    def show_details(self, skill: Skill | None) -> None:
        if skill is None:
            self.query_one("#details", Static).update(
                "No matching skills.\n\nBrowse a repository above to install skills, "
                "or change the scope and filter. Existing lock files are discovered automatically."
            )
            self.query_one("#content", Markdown).update("No skill selected.")
            return
        details = [
            skill.name,
            "",
            f"Source: {skill.source}",
            f"Provider: {skill.source_type}",
            f"Scope: {skill.scope}",
            f"Ref: {skill.ref or 'default branch'}",
            f"Status: {skill.status}",
            skill.reason,
            "",
            f"Lock: {skill.lock_path}",
            f"Path: {skill.installed_path or 'not on disk'}",
            f"Agents: {', '.join(skill.agents) or 'not recorded'}",
        ]
        for key, value in skill.metadata.items():
            if key not in {"source", "sourceType", "ref"}:
                details.append(f"{key}: {value}")
        if skill.description:
            details.extend(["", skill.description])
        self.query_one("#details", Static).update("\n".join(details))
        content = "This skill is not installed. Install or restore it to read SKILL.md."
        if skill.installed_path:
            try:
                content = (skill.installed_path / "SKILL.md").read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                content = f"Cannot read SKILL.md: {error}"
        self.query_one("#content", Markdown).update(content)

    @on(DataTable.RowHighlighted, "#skills")
    def highlight(self) -> None:
        self.show_details(self.focused_skill())

    @on(DataTable.RowSelected, "#skills")
    def row_selected(self) -> None:
        self.action_toggle_skill()

    @on(Input.Changed, "#filter")
    @on(Select.Changed, "#scope")
    def filter_changed(self) -> None:
        if self.query_one("#skills", DataTable).columns:
            self.render_rows()

    @on(Input.Submitted, "#source")
    def source_submitted(self) -> None:
        self.action_browse()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "refresh": self.action_refresh,
            "browse": self.action_browse,
            "library": self.action_library,
            "select-all": self.action_select_all,
            "select-source": self.action_select_source,
            "check": self.action_check,
            "install": self.action_install,
            "update": self.action_update,
            "remove": self.action_remove,
        }
        if handler := handlers.get(event.button.id or ""):
            handler()

    def action_toggle_skill(self) -> None:
        if skill := self.focused_skill():
            if skill.key in self.selection:
                self.selection.remove(skill.key)
            else:
                self.selection.add(skill.key)
            self.render_rows()

    def action_select_all(self) -> None:
        keys = {s.key for s in self.visible_skills}
        if keys.issubset(self.selection):
            self.selection.difference_update(keys)
        else:
            self.selection.update(keys)
        self.render_rows()

    def action_select_source(self) -> None:
        if current := self.focused_skill():
            self.selection.update(s.key for s in self.visible_skills if s.source == current.source)
            self.render_rows()

    def action_select_outdated(self) -> None:
        self.selection.update(s.key for s in self.visible_skills if s.status == Status.OUTDATED)
        self.render_rows()

    def action_clear_selection(self) -> None:
        self.selection.clear()
        self.render_rows()

    def action_search(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_library(self) -> None:
        self.catalog = False
        self.render_rows()

    def action_refresh(self) -> None:
        if not self.busy:
            self.load_inventory()
            self.start_operation("Refreshing installation locations", self.refresh_locations())

    async def refresh_locations(self) -> str:
        await self.service.installed(self.skills)
        return "Library refreshed."

    def action_browse(self) -> None:
        if self.busy:
            return
        source = self.query_one("#source", Input).value.strip()
        if not source and (current := self.focused_skill()):
            source = current.source_input
            self.query_one("#source", Input).value = source
        scope = str(self.query_one("#target-scope", Select).value)
        self.start_operation("Browsing source", self.browse(source, scope))

    async def browse(self, source: str, scope: str) -> str:
        skills = await self.service.browse(source, scope)
        self.available = skills
        self.available_selected.clear()
        self.catalog = True
        self.query_one("#filter", Input).value = ""
        return f"Found {len(skills)} skills. Select several or all, then Install / restore."

    def action_check(self) -> None:
        if self.busy or self.catalog:
            return
        skills = self.chosen(fallback=False) or list(self.visible_skills)
        if not skills:
            self.activity("No installed skills to check.")
            return
        self.start_operation(f"Checking {len(skills)} skill(s)", self.check(skills))

    async def check(self, skills: list[Skill]) -> str:
        await self.service.check(skills)
        for skill in skills:
            self.activity(f"{skill.name}: {skill.status} — {skill.reason}")
        return f"Checked {len(skills)} skill(s)."

    def action_install(self) -> None:
        self.install_chosen(update=False)

    def action_update(self) -> None:
        if not self.catalog:
            self.install_chosen(update=True)

    def install_chosen(self, *, update: bool) -> None:
        if self.busy:
            return
        skills = self.chosen()
        if not skills:
            self.activity("Select a skill first.")
            return
        if update:
            skills = [s for s in skills if s.status != Status.DEPRECATED]
        if not skills:
            self.activity("The chosen skills were removed upstream. Review them before removal.")
            return
        if self.catalog:
            scope = str(self.query_one("#target-scope", Select).value)
            for skill in skills:
                skill.metadata["targetScope"] = scope
        agents = self.query_one("#agents", Input).value.replace(",", " ").split()
        copy = self.query_one("#copy", Checkbox).value
        self.start_operation(
            f"{'Updating' if update else 'Installing'} {len(skills)} skill(s)",
            self.install(skills, agents, copy),
        )

    async def install(self, skills: list[Skill], agents: list[str], copy: bool) -> str:
        message = await self.service.install(skills, agents, copy=copy)
        self.catalog = False
        self.available_selected.clear()
        self.load_inventory()
        await self.service.installed(self.skills)
        return message

    def action_remove(self) -> None:
        if self.busy or self.catalog:
            return
        skills = self.chosen()
        if not skills:
            return
        message = "Remove these skills and their agent links?\n\n" + "\n".join(
            f"• {s.name} ({s.scope})" for s in skills
        )

        def confirmed(result: bool | None) -> None:
            if result:
                self.start_operation(f"Removing {len(skills)} skill(s)", self.remove(skills))

        self.push_screen(ConfirmScreen(message), confirmed)

    async def remove(self, skills: list[Skill]) -> str:
        message = await self.service.remove(skills)
        self.load_inventory()
        return message

    def activity(self, message: str) -> None:
        self.query_one("#log", RichLog).write(Text(message))

    def start_operation(self, label: str, operation: Awaitable[str]) -> None:
        if self.busy:
            if asyncio.iscoroutine(operation):
                operation.close()
            return
        self.busy = True
        self.query_one("#operation", Static).update(label + "…")
        self.activity(label + "…")
        for button in self.query(Button):
            button.disabled = True
        self.run_worker(self.perform(operation), name=label, exit_on_error=False)

    async def perform(self, operation: Awaitable[str]) -> None:
        try:
            message = await operation
            self.activity(message)
            self.query_one("#operation", Static).update(message)
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            self.activity(message)
            self.query_one("#operation", Static).update("Operation failed — see activity log")
            self.notify(str(error), title="Operation failed", severity="error", timeout=8)
            # A multi-source operation may have partially succeeded before failing.
            self.load_inventory()
        finally:
            self.busy = False
            for button in self.query(Button):
                button.disabled = False
            self.render_rows()
            self.query_one("#skills", DataTable).focus()

    async def action_quit(self) -> None:
        if self.busy:
            self.activity("Wait for the current operation to finish before quitting.")
            return
        self.exit()


def runtime_label() -> str:
    return f"Managed skills version: {SKILLS_VERSION}"
