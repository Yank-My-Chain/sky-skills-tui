"""Fast Pilot coverage of UI selection, filtering, recovery and small terminals."""

import pytest
from rich.text import Text
from textual.content import Content
from textual.widgets import Button, DataTable, Input, Select, Static

from sky_skills_tui.app import ConfirmScreen, PreviewPane, SkillsApp
from sky_skills_tui.models import Inventory, Skill, Status
from sky_skills_tui.service import SkillsService


@pytest.fixture(autouse=True)
def preferences_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def assert_letter_shortcut(app, widget_id, key):
    label = app.query_one(f"#{widget_id}", Button).label
    if isinstance(label, Text):
        label = Content.from_rich_text(label)
    assert isinstance(label, Content)
    assert " · " not in label.plain
    assert any(
        label.plain[span.start : span.end].casefold() == key
        and label.get_style_at_offset(span.start).underline
        for span in label.spans
    )


class FakeService(SkillsService):
    def __init__(self, project):
        super().__init__(project)
        self.rows = [
            Skill(name, source, scope, project / "skills-lock.json")
            for name, source, scope in [
                ("alpha", "owner/one", "project"),
                ("beta", "owner/one", "global"),
                ("gamma", "owner/two", "project"),
            ]
        ]
        self.failure = False
        self.removed = []

    def inventory(self):
        return Inventory(list(self.rows), [])

    async def installed(self, skills):
        pass

    async def check(self, skills, progress=None):
        if self.failure:
            raise RuntimeError("source unavailable")
        for skill in skills:
            skill.status = Status.OUTDATED
        if progress is not None:
            progress(1, 1, skills)

    async def remove(self, skills):
        self.removed = [s.key for s in skills]
        self.rows = [s for s in self.rows if s.key not in self.removed]
        return "Removed chosen skills."


@pytest.mark.parametrize("size", [(80, 24), (140, 45)])
async def test_selection_filters_sources_and_sizes(tmp_path, size):
    app = SkillsApp(FakeService(tmp_path), bootstrap=False)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        for widget_id, key in (
            ("add-source", "b"),
            ("check", "c"),
            ("update", "u"),
            ("install", "i"),
            ("remove", "d"),
            ("inspect", "v"),
            ("activity", "l"),
        ):
            assert_letter_shortcut(app, widget_id, key)
        await pilot.press("s")
        assert app.selected == {"project:alpha", "global:beta"}
        await pilot.press("escape")
        app.query_one("#scope", Select).value = "project"
        await pilot.pause()
        await pilot.press("a")
        assert app.selected == {"project:alpha", "project:gamma"}
        app.query_one("#filter", Input).value = "gamma"
        await pilot.pause()
        assert [s.name for s in app.visible_skills] == ["gamma"]
        # Hidden selections remain visible in the count and are intentionally preserved.
        assert len(app.selected) == 2
        await pilot.press("escape")
        assert not app.selected
        app.query_one("#filter", Input).value = "no matching skill"
        await pilot.pause()
        assert not app.visible_skills


@pytest.mark.parametrize("confirm_key", ["ctrl+enter", "f2"])
async def test_error_recovery_and_remove_cancel(tmp_path, confirm_key):
    service = FakeService(tmp_path)
    app = SkillsApp(service, bootstrap=False)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press(confirm_key)
        assert not service.removed and len(app.screen_stack) == 1
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        assert str(app.screen.query_one("#confirm", Button).label) == (
            "Delete skills · Ctrl+Enter / F2"
        )
        await pilot.press("escape")
        assert not service.removed
        service.failure = True
        await pilot.press("c")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not app.busy
        service.failure = False
        await pilot.press("c")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert all(s.status == Status.OUTDATED for s in app.skills)
        await pilot.press("o", "d")
        await pilot.pause()
        await pilot.press(confirm_key)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(service.removed) == 3 and not app.skills


@pytest.mark.parametrize("size", [(80, 24), (140, 45)])
async def test_dropdown_and_keyboard_scrolling(tmp_path, size):
    from textual.containers import VerticalScroll
    from textual.widgets import Static

    from sky_skills_tui.presentation import RenderedMarkdown

    service = FakeService(tmp_path)
    folder = tmp_path / "alpha"
    folder.mkdir()
    body = "# Readable heading\n\n" + "\n\n".join(
        f"## Section {i}\n\nSome **bold** instructions and `code`." for i in range(35)
    )
    (folder / "SKILL.md").write_text("---\nname: alpha\ndescription: Example\n---\n\n" + body)
    service.rows[0].installed_path = folder
    app = SkillsApp(service, bootstrap=False)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        scope = app.query_one("#scope", Select)
        current = scope.query_one("SelectCurrent")
        assert scope.region.contains_region(current.region)
        await pilot.click("#scope")
        await pilot.pause()
        overlay = scope.query_one("SelectOverlay")
        assert overlay.region.height >= 3
        assert app.screen.region.contains_region(overlay.region)
        await pilot.press("escape")
        app.query_one("#skills").focus()
        await pilot.press("v")
        await pilot.pause()
        assert_letter_shortcut(app, "inspect", "v")
        assert str(app.query_one("#inspect", Button).label) == (
            "Close view" if size[0] < 120 else "View skill"
        )
        scroll = app.query_one("#content-scroll", VerticalScroll)
        assert app.focused is scroll
        assert scroll.max_scroll_y > 0
        preview = app.query_one("#content", PreviewPane).content
        assert isinstance(preview, RenderedMarkdown) and preview.markdown.markup == body
        assert "description: Example" in str(app.query_one("#metadata", Static).content)
        await pilot.press("pagedown")
        await pilot.pause()
        assert scroll.scroll_y > 0
        await pilot.press("end")
        await pilot.pause()
        assert scroll.scroll_y == scroll.max_scroll_y
        await pilot.press("home")
        await pilot.pause()
        assert scroll.scroll_y == 0
        from textual.events import MouseScrollDown

        await pilot._post_mouse_events([MouseScrollDown], "#content-scroll", offset=(2, 2))
        await pilot.pause()
        assert scroll.scroll_y > 0
        # Selection redraws should not recreate the document or reset its scroll.
        old_scroll = scroll.scroll_y
        app.render_rows()
        await pilot.pause()
        assert scroll.scroll_y == old_scroll
        await pilot.press("v" if size[0] < 120 else "escape")
        assert app.query_one("#skills").has_focus
        assert str(app.query_one("#inspect", Button).label) == "View skill"
        assert_letter_shortcut(app, "inspect", "v")


@pytest.mark.parametrize("size", [(80, 24), (140, 45)])
async def test_preview_is_lazy_and_refreshes_when_reopened(tmp_path, size):
    from unittest.mock import patch

    from textual.containers import VerticalScroll
    from textual.widgets import DataTable, TabbedContent

    from sky_skills_tui.presentation import RenderedMarkdown

    service = FakeService(tmp_path)
    bodies = {}
    for skill in service.rows[:2]:
        folder = tmp_path / skill.name
        folder.mkdir()
        bodies[skill.name] = f"# {skill.name}\n\n" + "\n\n".join(
            f"## Section {i}\n\n- **First** item\n- Second item\n\n"
            "| Task | Status |\n| --- | --- |\n| Read | Ready |\n\n"
            f"```python\nprint({i})\n```"
            for i in range(20)
        )
        (folder / "SKILL.md").write_text(bodies[skill.name])
        skill.installed_path = folder

    app = SkillsApp(service, bootstrap=False)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        content = app.query_one("#content", PreviewPane)
        table = app.query_one("#skills", DataTable)
        tabs = app.query_one("#inspector-tabs", TabbedContent)
        scroll = app.query_one("#content-scroll", VerticalScroll)
        table.move_cursor(row=1)
        await pilot.pause()
        assert not isinstance(content.content, RenderedMarkdown)

        await pilot.press("v")
        await pilot.pause()
        beta = content.content
        assert isinstance(beta, RenderedMarkdown) and beta.markdown.markup == bodies["beta"]
        assert not content.children
        await pilot.press("pagedown")
        await pilot.pause()
        old_scroll = scroll.scroll_y
        assert old_scroll > 0
        with patch.object(tabs.query_one("Underline"), "animate") as animate:
            await pilot.click(tabs.get_tab("metadata-tab"))
            await pilot.pause()
            await pilot.click(tabs.get_tab("content-tab"))
            await pilot.pause()
            animate.assert_not_called()
        assert content.content is beta
        assert scroll.scroll_y == old_scroll

        # At narrow widths the content tab remains active behind the library.
        await pilot.press("escape")
        if size[0] >= 120:
            tabs.active = "details-tab"
        table.move_cursor(row=0)
        await pilot.pause()
        assert content.content is beta
        await pilot.press("v")
        await pilot.pause()
        alpha = content.content
        assert isinstance(alpha, RenderedMarkdown) and alpha.markdown.markup == bodies["alpha"]
        assert scroll.scroll_y == 0

        tabs.active = "metadata-tab"
        await pilot.pause()
        changed_body = bodies["alpha"] + "\n\nUpdated instructions."
        (tmp_path / "alpha" / "SKILL.md").write_text(changed_body)
        app.render_rows()
        app.theme = "textual-light"
        await pilot.pause()
        assert content.content is alpha
        tabs.active = "content-tab"
        await pilot.pause()
        refreshed = content.content
        assert isinstance(refreshed, RenderedMarkdown) and refreshed.markdown.markup == changed_body
        assert refreshed.markdown.code_theme == "friendly"
        app.theme = "sky"
        await pilot.pause()
        refreshed = content.content
        assert (
            isinstance(refreshed, RenderedMarkdown) and refreshed.markdown.code_theme == "monokai"
        )

        app.action_help()
        app.theme = "textual-light"
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        refreshed = content.content
        assert (
            isinstance(refreshed, RenderedMarkdown) and refreshed.markdown.code_theme == "friendly"
        )

        await pilot.press("escape")
        await pilot.resize_terminal(80, 24)
        table.move_cursor(row=1)
        await pilot.pause()
        assert content.content is refreshed
        await pilot.resize_terminal(140, 45)
        await pilot.pause()
        resized = content.content
        assert isinstance(resized, RenderedMarkdown) and resized.markdown.markup == bodies["beta"]

        app.query_one("#filter", Input).value = "unmatched"
        await pilot.pause()
        empty = content.content
        assert isinstance(empty, RenderedMarkdown) and empty.markdown.markup == "No skill selected."


async def test_install_settings_help_and_activity(tmp_path):
    from textual.widgets import Checkbox, SelectionList

    from sky_skills_tui.screens import ActivityScreen, HelpScreen, InstallScreen

    class InstallingService(FakeService):
        installed_args: tuple[list[Skill], list[str], bool] | None = None

        async def browse(self, source, scope):
            return [Skill("delta", source, "available", self.lock_path(scope))]

        async def install(self, skills, agents, *, copy=False):
            self.installed_args = (skills, agents, copy)
            return "Installed."

    service = InstallingService(tmp_path)
    app = SkillsApp(service, bootstrap=False)
    async with app.run_test(size=(80, 24)) as pilot:
        assert str(app.query_one("#install", Button).label) == "Reinstall…"
        await pilot.press("i")
        assert isinstance(app.screen, InstallScreen)
        assert str(app.screen.query_one("#apply-install", Button).label) == (
            "Reinstall · Ctrl+Enter / F2"
        )
        await pilot.press("escape")
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("c")  # Background shortcuts must not start operations from dialogs.
        assert not app.busy
        await pilot.press("escape", "b")
        app.query_one("#source", Input).value = "owner/repo"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.catalog
        assert str(app.query_one("#install", Button).label) == "Install…"
        assert_letter_shortcut(app, "install", "i")
        await pilot.press("i")
        assert isinstance(app.screen, InstallScreen)
        scope = app.screen.query_one("#target-scope", Select)
        assert scope.region.contains_region(scope.query_one("SelectCurrent").region)
        scope.value = "global"
        await pilot.click("#choose-agents")
        app.screen.query_one("#agent-list", SelectionList).select("claude-code")
        await pilot.pause()
        await pilot.click("#use-agents")
        app.screen.query_one("#copy", Checkbox).value = True
        assert app.screen.query_one("#install-dialog").content_region.contains_region(
            app.screen.query_one("#apply-install").region
        )
        assert await pilot.click("#apply-install")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert service.installed_args is not None
        skills, agents, copy = service.installed_args
        assert skills[0].metadata["targetScope"] == "global"
        assert agents == ["codex", "claude-code"] and copy
        assert not app.catalog
        assert str(app.query_one("#install", Button).label) == "Reinstall…"
        assert_letter_shortcut(app, "install", "i")
        assert not app.query_one("#source-bar").display
        await pilot.press("l")
        assert isinstance(app.screen, ActivityScreen)
        assert "Installed." in app.screen.messages
        await pilot.press("escape", "u", "escape")
        assert not isinstance(app.screen, InstallScreen)


async def test_resize_empty_and_unicode(tmp_path):
    from textual.widgets import Static

    service = FakeService(tmp_path)
    service.rows[0].name = "設計 · مرحبا · cafe\u0301 · 👩‍💻"
    app = SkillsApp(service, bootstrap=False)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        assert service.rows[0].name in str(app.query_one("#details", Static).content)
        for size in [(80, 24), (60, 18), (140, 45), (80, 24)]:
            await pilot.resize_terminal(*size)
            await pilot.pause()
            assert app.query_one("#size-warning").display == (size[0] < 80)
        app.query_one("#filter", Input).value = "unmatched"
        await pilot.pause()
        assert app.query_one("#empty").display
        assert app.query_one("#check").disabled
        app.query_one("#filter", Input).focus()
        await pilot.press("end", "question_mark")
        assert app.query_one("#filter", Input).value == "unmatched?"
        assert len(app.screen_stack) == 1


async def test_escape_steps_back_and_selection_updates_rows_in_place(tmp_path, monkeypatch):
    app = SkillsApp(FakeService(tmp_path), bootstrap=False)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        table = app.query_one("#skills", DataTable)
        cleared = []
        original_clear = table.clear
        monkeypatch.setattr(
            table,
            "clear",
            lambda *args, **kwargs: cleared.append(1) or original_clear(*args, **kwargs),
        )
        await pilot.press("space", "a")
        assert not cleared, "selection changes must not rebuild the table"
        assert app.selected == {"project:alpha", "global:beta", "project:gamma"}
        assert str(table.get_cell("project:alpha", "mark")) == "✓"

        # Escape leaves the filter instead of discarding the selection.
        await pilot.press("slash", "o")
        await pilot.press("escape")
        assert table.has_focus and len(app.selected) == 3
        await pilot.press("b")
        assert app.query_one("#source", Input).has_focus
        await pilot.press("escape")
        assert table.has_focus and not app.query_one("#source-bar").display
        assert len(app.selected) == 3

        await pilot.press("escape")
        assert not app.selected
        assert str(table.get_cell("project:alpha", "mark")) == "○"


async def test_long_preview_renders_in_background(tmp_path, monkeypatch):
    from sky_skills_tui.presentation import RenderedMarkdown

    service = FakeService(tmp_path)
    folder = tmp_path / "alpha"
    folder.mkdir()
    body = "# Long skill\n\n" + "\n\n".join(
        f"## Section {i}\n\n```python\nprint({i})\n```\n\n| A | B |\n| - | - |\n| 1 | 2 |"
        for i in range(200)
    )
    (folder / "SKILL.md").write_text(body)
    service.rows[0].installed_path = folder
    app = SkillsApp(service, bootstrap=False)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        content = app.query_one("#content", PreviewPane)
        shown = []
        original_update = content.update
        monkeypatch.setattr(
            content, "update", lambda value: shown.append(value) or original_update(value)
        )
        await pilot.press("v")
        await app.workers.wait_for_complete()
        await pilot.pause()
        # A placeholder appears at once; the document follows from a worker.
        assert [type(value) for value in shown] == [Text, RenderedMarkdown]
        assert str(shown[0]) == "Rendering SKILL.md…"
        rendered = content.content
        assert isinstance(rendered, RenderedMarkdown) and rendered.markdown.markup == body
        assert content.virtual_size.height > 1000
        # Moving away and back reuses the rendered document.
        await pilot.press("escape", "down", "up")
        await pilot.pause()
        assert content.content is rendered


async def test_busy_operations_show_progress_and_can_be_cancelled(tmp_path, monkeypatch):
    import asyncio

    class SlowService(FakeService):
        started = asyncio.Event()

        async def check(self, skills, progress=None):
            self.started.set()
            await asyncio.Event().wait()

    service = SlowService(tmp_path)
    app = SkillsApp(service, bootstrap=False)
    notices = []
    async with app.run_test(size=(140, 45)) as pilot:
        monkeypatch.setattr(app, "notify", lambda message, **kwargs: notices.append(message))
        await pilot.press("c")
        await service.started.wait()
        await pilot.pause()
        operation = str(app.query_one("#operation", Static).content)
        assert app.busy and "Checking 3 skill(s)…" in operation and "Esc cancels" in operation
        table = app.query_one("#skills", DataTable)
        assert "checking…" in str(table.get_cell("project:alpha", "status"))

        await pilot.press("c")
        assert notices and "still running" in notices[-1]

        await pilot.press("escape")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not app.busy and not app.pending
        assert str(app.query_one("#operation", Static).content) == "Cancelled: Checking 3 skill(s)."
        assert "unchecked" in str(table.get_cell("project:alpha", "status"))

        # Changes to installed files cannot be interrupted by quitting.
        never = asyncio.Event()

        async def remove():
            await never.wait()
            return "Removed."

        app.start_operation("Removing 1 skill(s)", remove())
        await pilot.press("q")
        assert app.is_running and "must finish first" in notices[-1]
        never.set()
        await app.workers.wait_for_complete()


async def test_dialog_shortcuts_avoid_os_conflicts(tmp_path):
    from textual.widgets import SelectionList

    from sky_skills_tui.agents import AGENT_IDS
    from sky_skills_tui.screens import AgentPickerScreen, HelpScreen, InstallScreen

    service = FakeService(tmp_path)
    app = SkillsApp(service, bootstrap=False)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("i")
        assert isinstance(app.screen, InstallScreen)
        assert_letter_shortcut(app.screen, "choose-agents", "a")
        await pilot.press("a")
        assert isinstance(app.screen, AgentPickerScreen)
        picker = app.screen
        assert_letter_shortcut(picker, "all-agents", "a")
        assert_letter_shortcut(picker, "clear-agents", "c")
        # Letters type into the search field (macOS sends Option+A as "å").
        await pilot.press("c", "o")
        assert picker.query_one("#agent-search", Input).value == "co"
        assert picker.targets == {"codex"}
        await pilot.press("backspace", "backspace", "down")
        assert picker.query_one("#agent-list", SelectionList).has_focus
        await pilot.press("a")
        assert picker.targets == set(AGENT_IDS)
        await pilot.press("c")
        assert not picker.targets
        await pilot.press("up")
        assert picker.query_one("#agent-search", Input).has_focus
        await pilot.press("alt+a")
        assert picker.targets == set(AGENT_IDS)
        await pilot.press("escape", "escape")
        assert len(app.screen_stack) == 1

        # Terminals that send a line feed for Ctrl+Enter still confirm.
        await pilot.press("d", "ctrl+j")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert service.removed == ["project:alpha"]

        for opener, closer in (("question_mark", "q"), ("question_mark", "question_mark")):
            await pilot.press(opener)
            assert isinstance(app.screen, HelpScreen)
            await pilot.press(closer)
            assert len(app.screen_stack) == 1
