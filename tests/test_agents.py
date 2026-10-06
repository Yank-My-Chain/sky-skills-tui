"""Agent picker behavior and user defaults across sessions."""

import json

import pytest
from textual.widgets import Button, Input, Static

from sky_skills_tui.agents import AGENT_IDS, AGENTS, COMMON_AGENTS, selected_agents
from sky_skills_tui.app import SkillsApp
from sky_skills_tui.preferences import AgentPreferences
from sky_skills_tui.screens import (
    AgentPickerScreen,
    AgentSelectionList,
    InstallOptions,
    InstallScreen,
)
from sky_skills_tui.service import SkillsService


@pytest.mark.parametrize("size", [(80, 24), (140, 42)])
async def test_picker_filters_preserve_hidden_choices_and_divider_navigation(isolated, size):
    home, project = isolated
    app = SkillsApp(SkillsService(project, home=home), bootstrap=False)
    results = []
    async with app.run_test(size=size) as pilot:
        app.push_screen(AgentPickerScreen("codex"), results.append)
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, AgentPickerScreen)
        choices = picker.query_one(AgentSelectionList)
        assert "Ctrl+Enter / F2" in str(picker.query_one("#use-agents", Button).label)
        assert [choices.get_option_at_index(i).value for i in range(6)] == list(COMMON_AGENTS)
        assert choices.get_option_at_index(6).disabled
        choices.focus()
        choices.highlighted = 5
        await pilot.press("down")
        assert choices.highlighted == 7
        await pilot.press("up")
        assert choices.highlighted == 5
        assert picker.query_one("#agent-dialog").content_region.contains_region(
            picker.query_one("#use-agents").region
        )

        search = picker.query_one("#agent-search", Input)
        search.value = "claude"
        search.focus()
        await pilot.pause()
        assert choices.option_count == 1
        assert picker.targets == {"codex"}
        await pilot.press("down", "space")
        await pilot.pause()
        assert picker.targets == {"codex", "claude-code"}
        search.value = "no matching agent"
        await pilot.pause()
        assert picker.query_one("#agent-empty").display
        assert picker.targets == {"codex", "claude-code"}
        assert not picker.query_one("#use-agents", Button).disabled
        search.value = ""
        search.focus()
        await pilot.pause()
        assert set(choices.selected) == {"codex", "claude-code"}
        assert choices.option_count == len(AGENTS) + 1
        await pilot.press("ctrl+enter")
        assert results == ["codex claude-code"]
        assert not app.busy


async def test_all_and_clear_apply_to_catalogue_while_filtered(isolated):
    home, project = isolated
    app = SkillsApp(SkillsService(project, home=home), bootstrap=False)
    results = []
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(AgentPickerScreen("*"), results.append)
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, AgentPickerScreen)
        assert picker.targets == AGENT_IDS
        picker.query_one("#agent-search", Input).value = "cursor"
        await pilot.pause()
        search = picker.query_one("#agent-search", Input)
        search.focus()
        await pilot.press("alt+c")
        assert not picker.targets
        assert picker.query_one("#use-agents", Button).disabled
        await pilot.press("ctrl+enter", "f2")
        assert app.screen is picker and not results
        await pilot.press("alt+a")
        assert picker.targets == AGENT_IDS
        assert search.value == "cursor"
        assert set(picker.query_one(AgentSelectionList).selected) == {"cursor"}
        picker.query_one(AgentSelectionList).focus()
        await pilot.press("f2")
        assert results == ["*"]


async def test_picker_confirmation_persists_across_projects_and_cancel_does_not(isolated):
    home, project = isolated
    service = SkillsService(project, home=home)
    app = SkillsApp(service, bootstrap=False)
    async with app.run_test(size=(140, 42)) as pilot:
        app.push_screen(
            InstallScreen(
                ["example"],
                app.install_options,
                catalog=True,
                update=False,
                on_agents_chosen=app.remember_agents,
            )
        )
        await pilot.pause()
        await pilot.press("alt+a")
        picker = app.screen
        picker.query_one(AgentSelectionList).select("cursor")
        await pilot.pause()
        await pilot.press("escape")
        assert not app.agent_preferences.path.exists()
        assert app.screen.query_one("#choose-agents").has_focus
        await pilot.press("alt+a")
        search = app.screen.query_one("#agent-search", Input)
        await pilot.press("u")
        assert search.value == "u" and isinstance(app.screen, AgentPickerScreen)
        search.value = ""
        await pilot.pause()
        app.screen.query_one(AgentSelectionList).select("claude-code")
        await pilot.pause()
        await pilot.press("ctrl+enter")
        assert isinstance(app.screen, InstallScreen)
        assert app.screen.query_one("#choose-agents").has_focus
        assert "Claude Code" in str(app.screen.query_one("#agent-summary", Static).content)
        assert app.agent_preferences.load() == "codex claude-code"
        assert not app.busy
        await pilot.press("escape")
        assert len(app.screen_stack) == 1
    other_project = project / "other"
    other_project.mkdir()
    next_app = SkillsApp(SkillsService(other_project, home=home), bootstrap=False)
    assert next_app.install_options.agents == "codex claude-code"
    assert next_app.install_options.scope == "project" and not next_app.install_options.copy


@pytest.mark.parametrize("key", ["ctrl+enter", "f2"])
@pytest.mark.parametrize(
    ("catalog", "update", "verb"),
    [(True, False, "Install"), (False, False, "Reinstall"), (False, True, "Update")],
)
async def test_install_dialog_shortcut_applies_current_settings(
    isolated, key, catalog, update, verb
):
    from textual.widgets import Checkbox, Select

    home, project = isolated
    app = SkillsApp(SkillsService(project, home=home), bootstrap=False)
    results = []
    async with app.run_test(size=(80, 24)) as pilot:
        screen = InstallScreen(
            ["example"], InstallOptions(agents="codex"), catalog=catalog, update=update
        )
        app.push_screen(screen, results.append)
        await pilot.pause()
        button = screen.query_one("#apply-install", Button)
        assert str(button.label) == f"{verb} · Ctrl+Enter / F2"
        assert screen.query_one("#install-dialog").content_region.contains_region(button.region)
        if catalog:
            screen.query_one("#target-scope", Select).value = "global"
        copy = screen.query_one("#copy", Checkbox)
        copy.focus()
        await pilot.press("space")
        assert copy.value and app.screen is screen
        await pilot.press(key)
        assert results == [InstallOptions("global" if catalog else "project", "codex", True)]
        assert len(app.screen_stack) == 1 and not app.busy


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        '{"version": 2, "agents": ["cursor"]}',
        '{"version": 1, "agents": [123]}',
        '{"version": 1, "agents": []}',
    ],
)
def test_bad_preferences_fall_back_to_codex(tmp_path, content):
    path = tmp_path / "preferences.json"
    path.write_text(content)
    assert AgentPreferences(path).load() == "codex"


def test_preferences_round_trip_all_and_drop_obsolete_agents(tmp_path):
    preferences = AgentPreferences(tmp_path / "config" / "preferences.json")
    assert preferences.load() == "codex"
    preferences.save("*")
    assert preferences.load() == "*"
    assert selected_agents(preferences.load()) == AGENT_IDS
    preferences.path.write_text(json.dumps({"version": 1, "agents": ["cursor", "obsolete"]}))
    assert preferences.load() == "cursor"
    with pytest.raises(ValueError, match="at least one"):
        preferences.save("")
    assert preferences.load() == "cursor"
    assert not list(preferences.path.parent.glob(".agents-*"))


def test_failed_preferences_write_preserves_previous_default(tmp_path, monkeypatch):
    preferences = AgentPreferences(tmp_path / "preferences.json")
    preferences.save("codex")

    def fail_replace(*args):
        raise OSError("Read-only configuration")

    monkeypatch.setattr("sky_skills_tui.preferences.os.replace", fail_replace)
    with pytest.raises(OSError, match="Read-only"):
        preferences.save("cursor")
    assert preferences.load() == "codex"
    assert not list(tmp_path.glob(".agents-*"))
