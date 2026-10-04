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
