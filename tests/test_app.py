"""Fast Pilot coverage of UI selection, filtering, recovery and small terminals."""

import pytest
from textual.widgets import Input, Select

from sky_skills_tui.app import ConfirmScreen, SkillsApp
from sky_skills_tui.models import Inventory, Skill, Status
from sky_skills_tui.service import SkillsService


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

    async def check(self, skills):
        if self.failure:
            raise RuntimeError("source unavailable")
        for skill in skills:
            skill.status = Status.OUTDATED

    async def remove(self, skills):
        self.removed = [s.key for s in skills]
        self.rows = [s for s in self.rows if s.key not in self.removed]
        return "Removed chosen skills."


@pytest.mark.parametrize("size", [(80, 24), (140, 45)])
async def test_selection_filters_sources_and_sizes(tmp_path, size):
    app = SkillsApp(FakeService(tmp_path), bootstrap=False)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
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


async def test_error_recovery_and_remove_cancel(tmp_path):
    service = FakeService(tmp_path)
    app = SkillsApp(service, bootstrap=False)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
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
        await pilot.click("#confirm")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(service.removed) == 3 and not app.skills


@pytest.mark.parametrize("size", [(80, 24), (140, 45)])
async def test_dropdown_and_keyboard_scrolling(tmp_path, size):
    from textual.containers import VerticalScroll
    from textual.widgets import Markdown, Static

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
        scroll = app.query_one("#content-scroll", VerticalScroll)
        assert app.focused is scroll
        assert scroll.max_scroll_y > 0
        assert app.query_one("#content", Markdown)._markdown == body
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
        await pilot.press("escape")
        assert app.query_one("#skills").has_focus


async def test_install_settings_help_and_activity(tmp_path):
    from textual.widgets import Checkbox

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
        await pilot.press("i")
        assert isinstance(app.screen, InstallScreen)
        scope = app.screen.query_one("#target-scope", Select)
        assert scope.region.contains_region(scope.query_one("SelectCurrent").region)
        scope.value = "global"
        app.screen.query_one("#agents", Input).value = "codex claude-code"
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
