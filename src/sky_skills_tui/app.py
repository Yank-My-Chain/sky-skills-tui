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
from textual.theme import Theme
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from .models import Skill, Status
from .preferences import AgentPreferences
from .presentation import SkillMarkdown, shortcut_label, split_frontmatter
from .runtime import SKILLS_VERSION
from .screens import ActivityScreen, HelpScreen, InstallOptions, InstallScreen
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
                yield Button(shortcut_label("Cancel · Esc", "Esc"), id="cancel")
                yield Button("Remove skills", id="confirm", variant="error")

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class SkillsApp(App[None]):
    TITLE = "Sky"
    SUB_TITLE = "Your skills, their sources, one place"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("space", "toggle_skill", "Select"),
        Binding("a", "select_all", "Select visible", show=False),
        Binding("s", "select_source", "Select source", show=False),
        Binding("c", "check", "Check updates"),
        Binding("u", "update", "Update", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("b", "add_source", "Add skills", show=False),
        Binding("i", "install", "Install", show=False),
        Binding("d", "remove", "Remove", show=False),
        Binding("o", "select_outdated", "Select outdated", show=False),
        Binding("slash", "search", "Filter"),
        Binding("escape", "clear_selection", "Clear", show=False),
        Binding("v", "inspect", "Read skill"),
        Binding("l", "activity", "Activity", show=False),
        Binding("question_mark,f1", "help", "Help", key_display="?"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, service: SkillsService, *, bootstrap: bool = True) -> None:
        super().__init__()
        # Keep tab changes and keyboard navigation immediate.
        self.animation_level = "none"
        self.register_theme(
            Theme(
                name="sky",
                primary="#2c7883",
                secondary="#90a4b0",
                accent="#78c5ce",
                foreground="#dbe4ec",
                background="#101720",
                surface="#19232f",
                panel="#1d2a38",
                success="#9abaac",
                warning="#d9b879",
                error="#d88f99",
            )
        )
        self.theme = "sky"
        self.service = service
        self.bootstrap = bootstrap
        self.skills: list[Skill] = []
        self.available: list[Skill] = []
        self.visible_skills: list[Skill] = []
        self.selected: set[str] = set()
        self.available_selected: set[str] = set()
        self.busy = False
        self.catalog = False
        self.agent_preferences = AgentPreferences()
        self.install_options = InstallOptions(agents=self.agent_preferences.load())
        self.messages: list[str] = []
        self._preview_key: tuple[str, str] | None = None
        self._preview_body = "No skill selected."
        self._rendered_preview: tuple[tuple[str, str] | None, str] | None = None

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
                yield Button(shortcut_label("Add skills", "b"), id="add-source", variant="primary")
            with Horizontal(id="source-bar"):
                yield Input(placeholder="owner/repo, Git URL or local path", id="source")
                yield Button("Browse", id="browse", variant="primary")
                yield Button("Back to library", id="library")
            yield Static("Loading lock files…", id="summary", markup=False)
            with Horizontal(id="main"):
                with Vertical(id="list-panel"):
                    yield DataTable(id="skills", cursor_type="row", zebra_stripes=True)
                    yield Static(
                        "No skills yet. Add a source to get started.", id="empty", markup=False
                    )
                    yield Static("Space select · A all visible · S same source", id="hint")
                with Vertical(id="details-panel"):
                    with TabbedContent(id="inspector-tabs"):
                        with TabPane("Details", id="details-tab"):
                            with VerticalScroll(id="details-scroll", can_focus=True):
                                yield Static(
                                    "Choose a skill to inspect its origin.",
                                    id="details",
                                )
                        with TabPane("SKILL.md", id="content-tab"):
                            with VerticalScroll(id="content-scroll", can_focus=True):
                                yield Static("No skill selected.", id="content", markup=False)
                        with TabPane("Metadata", id="metadata-tab"):
                            with VerticalScroll(id="metadata-scroll", can_focus=True):
                                yield Static("", id="metadata", markup=False)
            yield Static("", id="action-context", markup=False)
            with HorizontalScroll(id="actions"):
                yield Button(shortcut_label("Check updates", "c"), id="check", variant="primary")
                yield Button(shortcut_label("Update", "u"), id="update")
                yield Button(shortcut_label("Restore…", "i"), id="install")
                yield Button(shortcut_label("Remove…", "d"), id="remove")
                yield Button(shortcut_label("Read skill", "v"), id="inspect")
                yield Button(shortcut_label("Activity", "l"), id="activity")
                yield Button(shortcut_label("Help", "?"), id="help")
            yield Static("Ready · ? for help", id="operation", markup=False)
        yield Static(
            "Sky needs at least 80 columns × 24 rows.\nResize the terminal to continue. Q quits.",
            id="size-warning",
        )
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.query_one("#list-panel").border_title = "Library"
        self.query_one("#details-panel").border_title = "Skill inspector"
        self.query_one("#source-bar").display = False
        tips = {
            "scope": "Show project skills, global skills, or both.",
            "filter": "Filter by name, source, status or agent. Press / to focus.",
            "add-source": "Browse a repository or local folder to install new skills (B).",
            "check": "Compare selected or visible skills with their sources (C). No files change.",
            "update": "Reinstall selected or highlighted skills from current source content (U).",
            "install": "Choose agents and reinstall selected skills, or the highlighted skill (I).",
            "remove": "Review selected skills, or the highlighted skill, before removal (D).",
            "inspect": "Read the highlighted skill. Page Up/Down or mouse wheel scrolls (V).",
            "activity": "Read the full operation history and error details (L).",
            "help": "Explain actions and keyboard shortcuts (? or F1).",
        }
        for name, tip in tips.items():
            self.query_one(f"#{name}").tooltip = tip
        self.load_inventory()
        self.query_one("#skills", DataTable).focus()
        if self.bootstrap:
            self.start_operation("Preparing npm skills runtime", self.prepare())

    def on_resize(self, event: Resize) -> None:
        screen = self.screen_stack[0]
        screen.set_class(event.size.height < 32, "short")
        screen.set_class(event.size.width < 120, "narrow")
        screen.set_class(event.size.width < 80 or event.size.height < 24, "too-small")
        if self.query("#skills"):
            self.call_after_refresh(self.render_rows)

    def watch_theme(self) -> None:
        if self.screen_stack and self.screen_stack[0].query("#content"):
            self.call_after_refresh(self.render_preview)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if len(self.screen_stack) > 1:
            return False
        if action in {"toggle_skill", "select_all", "select_source", "select_outdated"}:
            return isinstance(self.focused, DataTable)
        return True

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
        table.clear(columns=True)
        width = max(24, table.size.width - 31)
        table.add_column("", width=1)
        table.add_column("Skill / source", width=width)
        table.add_column("Status / scope", width=22)
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
            Status.CURRENT: self.current_theme.success or "green",
            Status.OUTDATED: self.current_theme.warning or "yellow",
            Status.DEPRECATED: self.current_theme.error or "red",
            Status.UNAVAILABLE: self.current_theme.warning or "yellow",
        }
        for skill in self.visible_skills:
            state = "available" if self.catalog else str(skill.status)
            location = skill.scope
            if not self.catalog and skill.installed_path is None:
                location += " · not on disk"
            table.add_row(
                Text(
                    "✓" if skill.key in self.selection else "○",
                    style=self.current_theme.accent or "cyan",
                ),
                Text.assemble((skill.name, "bold"), "\n", (skill.source, "dim")),
                Text.assemble((state, colors.get(skill.status, "")), "\n", (location, "dim")),
                key=skill.key,
                height=2,
            )
        if self.visible_skills:
            table.move_cursor(row=min(row, len(self.visible_skills) - 1))
        self.query_one("#empty").display = not self.visible_skills
        self.query_one("#skills").display = bool(self.visible_skills)
        self.query_one("#empty", Static).update(
            "No matching skills.\nClear the filter or change the scope."
            if candidates
            else "No skills yet.\nChoose Add skills to browse a repository."
        )
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
        chosen = self.chosen()
        count = len(self.selection)
        hidden = len(self.selection - {s.key for s in self.visible_skills})
        target = f"{count} selected" if count else "highlighted skill"
        if hidden:
            target += f" ({hidden} hidden)"
        check_target = f"{count} selected" if count else f"all {len(self.visible_skills)} visible"
        self.query_one("#action-context", Static).update(
            f"Install: {target} · choose scope and agents next"
            if self.catalog
            else f"Check: {check_target} · Other actions: {target}"
        )
        for name in ("check", "update", "remove"):
            eligible = (
                bool(self.chosen(fallback=False) or self.visible_skills)
                if name == "check"
                else bool(chosen)
            )
            self.query_one(f"#{name}", Button).disabled = self.busy or not installed or not eligible
        self.query_one("#install", Button).disabled = self.busy or not chosen
        self.query_one("#install", Button).label = shortcut_label(
            "Install…" if self.catalog else "Restore…", "i"
        )
        inspector = self.query_one("#inspect", Button)
        inspector.disabled = not self.focused_skill()
        inspector.label = shortcut_label(
            "Back to list"
            if (
                self.screen_stack[0].has_class("narrow")
                and self.screen_stack[0].has_class("reading")
            )
            else "Read skill",
            "v",
        )
        self.query_one("#list-panel").border_title = "Source results" if self.catalog else "Library"

    def show_details(self, skill: Skill | None) -> None:
        if skill is None:
            self.query_one("#details", Static).update(
                "Choose a skill to inspect its source and installation."
            )
            self.query_one("#metadata", Static).update("")
            self._preview_key = None
            self._preview_body = "No skill selected."
            self.render_preview()
            return
        details = Text()
        details.append(skill.name + "\n", style="bold")
        details.append(
            ("Available to install" if self.catalog else str(skill.status).capitalize()) + "\n\n",
            style="bold",
        )
        if not self.catalog:
            details.append(skill.reason + "\n\n")
        for label, value in (
            ("Source", skill.source),
            ("Scope", "Choose when installing" if self.catalog else skill.scope.capitalize()),
            ("Branch", skill.ref or "Default branch"),
            ("Agents", ", ".join(skill.agents) or "Not recorded"),
        ):
            details.append(label + "\n", style="dim")
            details.append(value + "\n\n")
        if skill.description:
            details.append(skill.description + "\n\n")
        details.append("SKILL.md: instructions · Metadata: paths and lock details", style="dim")
        self.query_one("#details", Static).update(details)
        content = "This skill is not on disk. Choose Install or Restore to read SKILL.md."
        if skill.installed_path:
            try:
                content = (skill.installed_path / "SKILL.md").read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                content = f"Cannot read SKILL.md: {error}"
        frontmatter, body = split_frontmatter(content)
        preview_key = (skill.key, content)
        if preview_key != self._preview_key:
            for name in ("content-scroll", "details-scroll", "metadata-scroll"):
                self.query_one(f"#{name}", VerticalScroll).scroll_home(animate=False)
            self._preview_key = preview_key
        self._preview_body = body or "This skill has no instructions."
        self.render_preview()
        metadata = [
            f"Lock file\n{skill.lock_path}",
            f"Installed path\n{skill.installed_path or 'Not on disk'}",
        ]
        metadata.extend(f"{key}\n{value}" for key, value in skill.metadata.items())
        if frontmatter:
            metadata.append("SKILL.md frontmatter\n" + frontmatter)
        self.query_one("#metadata", Static).update("\n\n".join(metadata))

    def render_preview(self) -> None:
        screen = self.screen_stack[0]
        if (
            screen.query_one("#inspector-tabs", TabbedContent).active != "content-tab"
            or not screen.query_one("#details-panel").display
        ):
            return
        preview = (self._preview_key, self.theme)
        if preview != self._rendered_preview:
            screen.query_one("#content", Static).update(
                SkillMarkdown(
                    self._preview_body,
                    code_theme="monokai" if self.current_theme.dark else "friendly",
                )
            )
            self._rendered_preview = preview

    @on(TabbedContent.TabActivated, "#inspector-tabs")
    def inspector_tab(self, event: TabbedContent.TabActivated) -> None:
        self.render_preview()
        if event.pane and (
            self.query_one("#details-panel").has_focus_within or self.screen.has_class("reading")
        ):
            self.query_one(f"#{event.pane.id.removesuffix('-tab')}-scroll").focus()

    @on(DataTable.RowHighlighted, "#skills")
    def highlight(self) -> None:
        self.show_details(self.focused_skill())
        self.update_summary()

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
            "add-source": self.action_add_source,
            "inspect": self.action_inspect,
            "activity": self.action_activity,
            "help": self.action_help,
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
        if self.screen.has_class("reading") or self.query_one("#details-panel").has_focus_within:
            self.screen.remove_class("reading")
            self.query_one("#skills").focus()
            self.update_summary()
            return
        self.selection.clear()
        self.render_rows()

    def action_search(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_activity(self) -> None:
        self.push_screen(ActivityScreen(self.messages))

    def action_inspect(self) -> None:
        if self.screen.has_class("narrow") and self.screen.has_class("reading"):
            self.action_clear_selection()
            return
        if self.focused_skill():
            self.screen.add_class("reading")
            self.query_one("#inspector-tabs", TabbedContent).active = "content-tab"
            self.render_preview()
            self.call_after_refresh(self.query_one("#content-scroll").focus)
            self.update_summary()

    def action_add_source(self) -> None:
        self.query_one("#source-bar").display = True
        self.query_one("#source").focus()

    def action_library(self) -> None:
        self.catalog = False
        self.query_one("#source-bar").display = False
        self.query_one("#skills").focus()
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
        scope = self.install_options.scope
        self.start_operation("Browsing source", self.browse(source, scope))

    async def browse(self, source: str, scope: str) -> str:
        skills = await self.service.browse(source, scope)
        self.available = skills
        self.available_selected.clear()
        self.catalog = True
        self.query_one("#filter", Input).value = ""
        return f"Found {len(skills)} skills. Select several or all, then Install."

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

        def configured(options: InstallOptions | None) -> None:
            if options is None:
                return
            self.install_options = options
            if self.catalog:
                for skill in skills:
                    skill.metadata["targetScope"] = options.scope
            agents = options.agents.replace(",", " ").split()
            self.start_operation(
                f"{'Updating' if update else 'Installing'} {len(skills)} skill(s)",
                self.install(skills, agents, options.copy),
            )

        self.push_screen(
            InstallScreen(
                [s.name for s in skills],
                self.install_options,
                catalog=self.catalog,
                update=update,
                on_agents_chosen=self.remember_agents,
            ),
            configured,
        )

    def remember_agents(self, agents: str) -> None:
        self.install_options.agents = agents
        try:
            self.agent_preferences.save(agents)
        except OSError as error:
            self.activity(f"Could not save agent defaults: {error}")
            self.notify(
                "Agent defaults could not be saved; kept for this session.", severity="warning"
            )

    async def install(self, skills: list[Skill], agents: list[str], copy: bool) -> str:
        message = await self.service.install(skills, agents, copy=copy)
        self.catalog = False
        self.query_one("#source-bar").display = False
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
        self.messages.append(message)
        del self.messages[:-300]
        if isinstance(self.screen, ActivityScreen):
            self.screen.query_one(RichLog).write(Text(message))

    def start_operation(self, label: str, operation: Awaitable[str]) -> None:
        if self.busy:
            if asyncio.iscoroutine(operation):
                operation.close()
            return
        self.busy = True
        self.query_one("#operation", Static).update(label + "…")
        self.activity(label + "…")
        for button in self.query(Button):
            if button.id not in {"inspect", "activity", "help"}:
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
            self.query_one("#operation", Static).update(
                "Operation failed · L opens activity details"
            )
            self.notify(
                "Press L to read the error details and retry.",
                title="Operation failed",
                severity="error",
                timeout=4,
            )
            # A multi-source operation may have partially succeeded before failing.
            self.load_inventory()
        finally:
            self.busy = False
            for button in self.query(Button):
                button.disabled = False
            self.render_rows()
            if len(self.screen_stack) == 1:
                self.query_one("#skills", DataTable).focus()

    async def action_quit(self) -> None:
        if self.busy:
            self.activity("Wait for the current operation to finish before quitting.")
            return
        self.exit()


def runtime_label() -> str:
    return f"Managed skills version: {SKILLS_VERSION}"
