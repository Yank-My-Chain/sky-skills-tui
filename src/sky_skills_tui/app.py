"""Keyboard-first Textual interface for managing locked and available skills."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Iterable

from rich.segment import Segment
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.events import Resize
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.theme import Theme
from textual.widget import Widget
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
from textual.worker import Worker

from .models import Skill, Status
from .preferences import AgentPreferences
from .presentation import RenderedMarkdown, SkillMarkdown, shortcut_label, split_frontmatter
from .runtime import SKILLS_VERSION
from .screens import (
    APPLY_KEYS,
    ActionButton,
    ActivityScreen,
    HelpScreen,
    InstallOptions,
    InstallScreen,
)
from .service import SkillsService

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# Previews that render within this budget appear at once, without a placeholder.
PREVIEW_INLINE_SECONDS = 0.03
# Longer documents are parsed and rendered in the background from the start.
PREVIEW_INLINE_CHARS = 8000
# Background previews render in slices this long, handling keys between them.
PREVIEW_SLICE_SECONDS = 0.01
PREVIEW_CACHE_SIZE = 8


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding(APPLY_KEYS, "confirm", "Delete skills", show=False, priority=True),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label("Review deletion", id="confirm-title")
            yield Static(self.message, markup=False)
            with Horizontal():
                yield ActionButton(shortcut_label("Cancel · Esc", "Esc"), id="cancel")
                yield ActionButton(
                    shortcut_label("Delete skills · Ctrl+Enter / F2", "Ctrl+Enter / F2"),
                    id="confirm",
                    variant="error",
                )

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)


class PreviewPane(Widget):
    """SKILL.md view that draws only the visible lines of a pre-rendered document.

    A Static would re-render every line of a long skill on each update and layout.
    """

    DEFAULT_CSS = "PreviewPane { height: auto; }"

    def __init__(self, content: str, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.content: RenderedMarkdown | Text = Text(content)
        self._lines: tuple[int, list[list[Segment]]] | None = None
        self._strips: dict[int, Strip] = {}

    def update(self, content: RenderedMarkdown | Text) -> None:
        self.content = content
        self._lines, self._strips = None, {}
        self.refresh(layout=True)

    def lines(self, width: int) -> list[list[Segment]]:
        if isinstance(self.content, RenderedMarkdown):
            return self.content.lines
        if self._lines is None or self._lines[0] != width:
            options = self.app.console_options.update_width(max(width, 1))
            self._lines = (width, self.app.console.render_lines(self.content, options, pad=False))
            self._strips = {}
        return self._lines[1]

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return len(self.lines(width))

    def render_line(self, y: int) -> Strip:
        width = self.content_size.width
        lines = self.lines(width)
        if y >= len(lines):
            return Strip.blank(width, self.rich_style)
        # Strips are created only for lines that scroll into view.
        if (strip := self._strips.get(y)) is None:
            strip = self._strips[y] = Strip(lines[y]).apply_style(self.rich_style)
        return strip

    def notify_style_update(self) -> None:
        super().notify_style_update()
        self._strips = {}

    def on_resize(self) -> None:
        # Markdown is rendered for a specific width, so redraw when that changes.
        render = getattr(self.app, "render_preview", None)
        if render is not None:
            render()


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
        Binding("b", "add_source", "Browse skills", show=False),
        Binding("i", "install", "Install / reinstall", show=False),
        Binding("d", "remove", "Delete", show=False),
        Binding("o", "select_outdated", "Select outdated", show=False),
        Binding("slash", "search", "Filter"),
        Binding("escape", "step_back", "Back / clear", show=False),
        Binding("v", "inspect", "View skill"),
        Binding("l", "activity", "Activity log", show=False),
        Binding("question_mark,f1", "help", "Help", key_display="?"),
        Binding("q", "request_quit", "Quit"),
    ]
    # Library shortcuts pause behind dialogs; Tab, Ctrl+Q and Ctrl+P keep working there.
    LIBRARY_ACTIONS = frozenset(b.action for b in BINDINGS if isinstance(b, Binding))

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
        self._rendered_preview: tuple[object, ...] | None = None
        self._preview_pending: tuple[object, ...] | None = None
        self._preview_cache: OrderedDict[tuple[object, ...], RenderedMarkdown] = OrderedDict()
        # Keys of rows an operation is working on, shown in the status column.
        self.pending: set[str] = set()
        self.pending_label = ""
        self.operation_label = ""
        self.operation_detail = ""
        self.operation_started = 0.0
        self.operation_cancellable = False
        self.operation_worker: Worker[None] | None = None
        self._busy_notified = 0.0

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
                yield ActionButton(
                    shortcut_label("Browse skills", "b"), id="add-source", variant="primary"
                )
            with Horizontal(id="source-bar"):
                yield Input(placeholder="owner/repo, Git URL or local path", id="source")
                yield ActionButton("Browse", id="browse", variant="primary")
                yield ActionButton("Back to library", id="library")
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
                                yield PreviewPane("No skill selected.", id="content")
                        with TabPane("Metadata", id="metadata-tab"):
                            with VerticalScroll(id="metadata-scroll", can_focus=True):
                                yield Static("", id="metadata", markup=False)
            yield Static("", id="action-context", markup=False)
            with HorizontalScroll(id="actions"):
                yield ActionButton(
                    shortcut_label("Check updates", "c"), id="check", variant="primary"
                )
                yield ActionButton(shortcut_label("Update", "u"), id="update")
                yield ActionButton(shortcut_label("Reinstall…", "i"), id="install")
                yield ActionButton(shortcut_label("Delete…", "d"), id="remove")
                yield ActionButton(shortcut_label("View skill", "v"), id="inspect")
                yield ActionButton(shortcut_label("Activity log", "l"), id="activity")
                yield ActionButton(shortcut_label("Help", "?"), id="help")
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
            "remove": "Review selected skills, or the highlighted skill, before deletion (D).",
            "inspect": "View the highlighted skill. Page Up/Down or mouse wheel scrolls (V).",
            "activity": "Read the full operation history and error details (L).",
            "help": "Explain actions and keyboard shortcuts (? or F1).",
        }
        for name, tip in tips.items():
            self.query_one(f"#{name}").tooltip = tip
        self.load_inventory()
        self.query_one("#skills", DataTable).focus()
        self.set_interval(0.1, self.tick_operation)
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
            return action not in self.LIBRARY_ACTIONS
        if action in {"toggle_skill", "select_all", "select_source", "select_outdated"}:
            return isinstance(self.focused, DataTable)
        return True

    def blocked(self) -> bool:
        """Explain, rather than silently ignore, actions requested while busy."""
        if not self.busy:
            return False
        now = time.monotonic()
        if now - self._busy_notified > 2:
            self._busy_notified = now
            self.notify(
                f"{self.operation_label} is still running."
                + (" Press Esc to cancel it." if self.operation_cancellable else ""),
                title="Please wait",
                timeout=3,
            )
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
        table.add_column("", width=1, key="mark")
        table.add_column("Skill / source", width=width, key="skill")
        table.add_column("Status / scope", width=22, key="status")
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
        for skill in self.visible_skills:
            table.add_row(
                self.mark_cell(skill),
                Text.assemble((skill.name, "bold"), "\n", (skill.source, "dim")),
                self.status_cell(skill),
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
            else "No skills yet.\nChoose Browse skills to explore a repository."
        )
        self.update_summary()
        self.show_details(self.focused_skill())

    def mark_cell(self, skill: Skill) -> Text:
        return Text(
            "✓" if skill.key in self.selection else "○",
            style=self.current_theme.accent or "cyan",
        )

    def status_cell(self, skill: Skill) -> Text:
        colors = {
            Status.CURRENT: self.current_theme.success or "green",
            Status.OUTDATED: self.current_theme.warning or "yellow",
            Status.DEPRECATED: self.current_theme.error or "red",
            Status.UNAVAILABLE: self.current_theme.warning or "yellow",
        }
        state, color = (
            ("available" if self.catalog else str(skill.status)),
            colors.get(skill.status, ""),
        )
        if skill.key in self.pending:
            state, color = self.pending_label, self.current_theme.accent or "cyan"
        location = skill.scope
        if not self.catalog and skill.installed_path is None:
            location += " · not on disk"
        return Text.assemble((state, color), "\n", (location, "dim"))

    def refresh_cells(self, keys: Iterable[str] | None = None) -> None:
        """Redraw the mark and status of some rows without rebuilding the table."""
        table = self.query_one("#skills", DataTable)
        wanted = None if keys is None else set(keys)
        for skill in self.visible_skills:
            if wanted is None or skill.key in wanted:
                table.update_cell(skill.key, "mark", self.mark_cell(skill))
                table.update_cell(skill.key, "status", self.status_cell(skill))
        self.update_summary()

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
            "Install…" if self.catalog else "Reinstall…", "i"
        )
        inspector = self.query_one("#inspect", Button)
        inspector.disabled = not self.focused_skill()
        inspector.label = shortcut_label(
            "Close view"
            if (
                self.screen_stack[0].has_class("narrow")
                and self.screen_stack[0].has_class("reading")
            )
            else "View skill",
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
        content = "This skill is not on disk. Choose Install or Reinstall to view SKILL.md."
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
        view = screen.query_one("#content", PreviewPane)
        width = view.content_size.width
        if width <= 0:
            return  # PreviewPane.on_resize retries once the pane is laid out.
        code_theme = "monokai" if self.current_theme.dark else "friendly"
        target = (self._preview_key, code_theme, width)
        if target in (self._rendered_preview, self._preview_pending):
            return
        # A new target supersedes any preview still rendering.
        self.workers.cancel_group(self, "preview")
        if (cached := self._preview_cache.get(target)) is not None:
            self._preview_cache.move_to_end(target)
            self._show_preview(target, cached)
            return
        body = self._preview_body
        if len(body) <= PREVIEW_INLINE_CHARS:
            rendered = RenderedMarkdown(SkillMarkdown(body, code_theme=code_theme), width)
            if rendered.render_for(PREVIEW_INLINE_SECONDS):
                self._show_preview(target, self._cache_preview(target, rendered))
                return
        else:
            rendered = None
        # Long documents finish in the background so the list stays responsive.
        self._preview_pending = target
        self._rendered_preview = None
        view.update(Text("Rendering SKILL.md…", style="dim"))
        self.run_worker(
            self._finish_preview(target, rendered or (body, code_theme, width)),
            group="preview",
            exit_on_error=False,
        )

    async def _finish_preview(
        self, target: tuple[object, ...], work: RenderedMarkdown | tuple[str, str, int]
    ) -> None:
        if isinstance(work, tuple):
            await asyncio.sleep(0)  # Parse in a separate loop turn from the key press.
            body, code_theme, width = work
            work = RenderedMarkdown(SkillMarkdown(body, code_theme=code_theme), width)
        while not work.render_for(PREVIEW_SLICE_SECONDS):
            await asyncio.sleep(0)
        if self._preview_pending == target:
            self._show_preview(target, self._cache_preview(target, work))

    def _cache_preview(
        self, target: tuple[object, ...], rendered: RenderedMarkdown
    ) -> RenderedMarkdown:
        self._preview_cache[target] = rendered
        while len(self._preview_cache) > PREVIEW_CACHE_SIZE:
            self._preview_cache.popitem(last=False)
        return rendered

    def _show_preview(self, target: tuple[object, ...], rendered: RenderedMarkdown) -> None:
        self.screen_stack[0].query_one("#content", PreviewPane).update(rendered)
        self._rendered_preview = target
        self._preview_pending = None

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
            self.selection.symmetric_difference_update({skill.key})
            self.refresh_cells([skill.key])

    def action_select_all(self) -> None:
        keys = {s.key for s in self.visible_skills}
        if keys.issubset(self.selection):
            self.selection.difference_update(keys)
        else:
            self.selection.update(keys)
        self.refresh_cells(keys)

    def action_select_source(self) -> None:
        if current := self.focused_skill():
            keys = {s.key for s in self.visible_skills if s.source == current.source}
            self.selection.update(keys)
            self.refresh_cells(keys)

    def action_select_outdated(self) -> None:
        keys = {s.key for s in self.visible_skills if s.status == Status.OUTDATED}
        self.selection.update(keys)
        self.refresh_cells(keys)

    def action_step_back(self) -> None:
        """Escape steps back one level: leave a field or preview, cancel, then clear."""
        focused = self.focused
        if isinstance(focused, Input) and focused.id in {"filter", "source"}:
            if focused.id == "source" and not focused.value and not self.catalog:
                self.query_one("#source-bar").display = False
            self.query_one("#skills").focus()
            return
        if self.screen.has_class("reading") or self.query_one("#details-panel").has_focus_within:
            self.action_clear_selection()
            return
        if self.busy and self.operation_cancellable and self.operation_worker:
            self.operation_worker.cancel()
            return
        self.action_clear_selection()

    def action_clear_selection(self) -> None:
        if self.screen.has_class("reading") or self.query_one("#details-panel").has_focus_within:
            self.screen.remove_class("reading")
            self.query_one("#skills").focus()
            self.update_summary()
            return
        cleared = set(self.selection)
        self.selection.clear()
        self.refresh_cells(cleared)

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
            self.call_after_refresh(self.render_preview)
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
        if not self.blocked():
            self.load_inventory()
            self.start_operation(
                "Refreshing installation locations", self.refresh_locations(), cancellable=True
            )

    async def refresh_locations(self) -> str:
        await self.service.installed(self.skills)
        return "Library refreshed."

    def action_browse(self) -> None:
        if self.blocked():
            return
        source = self.query_one("#source", Input).value.strip()
        if not source and (current := self.focused_skill()):
            source = current.source_input
            self.query_one("#source", Input).value = source
        scope = self.install_options.scope
        self.start_operation("Browsing source", self.browse(source, scope), cancellable=True)

    async def browse(self, source: str, scope: str) -> str:
        skills = await self.service.browse(source, scope)
        self.available = skills
        self.available_selected.clear()
        self.catalog = True
        self.query_one("#filter", Input).value = ""
        return f"Found {len(skills)} skills. Select several or all, then Install."

    def action_check(self) -> None:
        if self.catalog or self.blocked():
            return
        skills = self.chosen(fallback=False) or list(self.visible_skills)
        if not skills:
            self.activity("No installed skills to check.")
            return
        self.start_operation(
            f"Checking {len(skills)} skill(s)",
            self.check(skills),
            cancellable=True,
            pending=(skills, "checking…"),
        )

    async def check(self, skills: list[Skill]) -> str:
        def progress(done: int, total: int, group: list[Skill]) -> None:
            # Show each source's results as soon as it finishes.
            self.operation_detail = f"{done} of {total} sources"
            self.pending.difference_update(s.key for s in group)
            self.refresh_cells(s.key for s in group)

        await self.service.check(skills, progress)
        for skill in skills:
            self.activity(f"{skill.name}: {skill.status} — {skill.reason}")
        return f"Checked {len(skills)} skill(s)."

    def action_install(self) -> None:
        self.install_chosen(update=False)

    def action_update(self) -> None:
        if not self.catalog:
            self.install_chosen(update=True)

    def install_chosen(self, *, update: bool) -> None:
        if self.blocked():
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
                pending=(skills, "updating…" if update else "installing…"),
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
        if self.catalog or self.blocked():
            return
        skills = self.chosen()
        if not skills:
            return
        message = "Delete these skills and their agent links?\n\n" + "\n".join(
            f"• {s.name} ({s.scope})" for s in skills
        )

        def confirmed(result: bool | None) -> None:
            if result:
                self.start_operation(
                    f"Removing {len(skills)} skill(s)",
                    self.remove(skills),
                    pending=(skills, "removing…"),
                )

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

    def start_operation(
        self,
        label: str,
        operation: Awaitable[str],
        *,
        cancellable: bool = False,
        pending: tuple[list[Skill], str] | None = None,
    ) -> None:
        """Run one operation at a time. Only read-only operations may be cancelled."""
        if self.busy:
            if asyncio.iscoroutine(operation):
                operation.close()
            return
        self.busy = True
        self.operation_label, self.operation_detail = label, ""
        self.operation_started = time.monotonic()
        self.operation_cancellable = cancellable
        self.activity(label + "…")
        for button in self.query(Button):
            if button.id not in {"inspect", "activity", "help"}:
                button.disabled = True
        if pending:
            skills, self.pending_label = pending
            self.pending = {s.key for s in skills}
            self.refresh_cells(self.pending)
        self.tick_operation()
        self.operation_worker = self.run_worker(
            self.perform(label, operation), name=label, exit_on_error=False
        )

    def tick_operation(self) -> None:
        """Animate the status line so long operations never look frozen."""
        if not self.busy:
            return
        elapsed = time.monotonic() - self.operation_started
        parts = [f"{SPINNER[int(elapsed * 10) % len(SPINNER)]} {self.operation_label}…"]
        if self.operation_detail:
            parts.append(self.operation_detail)
        if elapsed >= 1:
            parts.append(f"{int(elapsed)}s")
        if self.operation_cancellable:
            parts.append("Esc cancels")
        self.query_one("#operation", Static).update(" · ".join(parts))

    async def perform(self, label: str, operation: Awaitable[str]) -> None:
        try:
            message = await operation
            self.activity(message)
            self.query_one("#operation", Static).update(message)
        except asyncio.CancelledError:
            # Subprocesses are terminated by Runtime.process; finished results are kept.
            self.activity(f"Cancelled: {label}.")
            self.query_one("#operation", Static).update(f"Cancelled: {label}.")
            raise
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
            self.operation_cancellable = False
            self.operation_worker = None
            self.pending.clear()
            for button in self.query(Button):
                button.disabled = False
            self.render_rows()
            if len(self.screen_stack) == 1:
                self.query_one("#skills", DataTable).focus()

    async def action_request_quit(self) -> None:
        await self.action_quit()

    async def action_quit(self) -> None:
        if self.busy:
            if self.operation_cancellable and self.operation_worker:
                self.operation_worker.cancel()
                self.exit()
                return
            self.notify(
                f"{self.operation_label} must finish first so nothing is left half-written.",
                title="Please wait",
                severity="warning",
                timeout=4,
            )
            return
        self.exit()


def runtime_label() -> str:
    return f"Managed skills version: {SKILLS_VERSION}"
