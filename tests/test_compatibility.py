"""Live contracts for EVERY npm command used by the app; run against candidate releases."""

import json
import re
import shutil

import pytest
from textual.widgets import DataTable, Input, SelectionList, Static

from sky_skills_tui.agents import AGENTS
from sky_skills_tui.app import SkillsApp
from sky_skills_tui.models import Status
from sky_skills_tui.runtime import CommandError, CompatibilityError
from sky_skills_tui.upstream import json_rows

from .git_server import git

pytestmark = pytest.mark.integration


async def test_agent_catalogue_matches_managed_cli(real_service):
    cli = real_service.runtime.entry.parent.parent / "dist/cli.mjs"
    source = cli.read_text(encoding="utf-8")
    catalogue = source.split("const agents = {", 1)[1].split("\n};", 1)[0]
    upstream = dict(re.findall(r'\n\t\tname: "([^"]+)",\n\t\tdisplayName: "([^"]+)"', catalogue))
    assert upstream == dict(AGENTS)


@pytest.mark.parametrize("scope,copy", [("project", False), ("global", True)])
async def test_cli_lifecycle_contract(real_service, git_source, scope, copy):
    url, source, remote = git_source
    service = real_service
    available = await service.browse(url, scope)
    assert {s.name for s in available} == {"alpha", "beta", "gamma"}
    assert all(s.description.endswith("fixture skill") for s in available)
    chosen = [s for s in available if s.name != "gamma"]
    await service.install(chosen, ["codex", "claude-code"], copy=copy)
    inventory = service.inventory()
    assert not inventory.warnings
    tracked = inventory.skills
    assert {s.name for s in tracked} == {"alpha", "beta"}
    assert all(s.scope == scope for s in tracked)
    lock = json.loads(service.lock_path(scope).read_text())
    assert lock["version"] == (3 if scope == "global" else 1)
    hash_field = "skillFolderHash" if scope == "global" else "computedHash"
    for skill in tracked:
        entry = lock["skills"][skill.name]
        assert entry["sourceType"] == "git"
        assert entry["sourceUrl"] == url
        assert entry[hash_field] == await service.runtime.folder_hash(source / skill.name)
        assert skill.installed_path is not None
        assert (skill.installed_path / "references/Guide.txt").is_file()
    await service.installed(tracked)
    # npm 1.7.0 reports detected agent links; universal canonical consumers need no link.
    assert all("Claude Code" in s.agents for s in tracked)
    if scope == "project":
        assert (service.project / ".claude/skills/alpha").is_symlink() is (not copy)
    await service.check(tracked)
    assert all(s.status == Status.CURRENT for s in tracked)
    (source / "alpha/references/Guide.txt").write_text("Version two — reference only")
    git("add", ".", cwd=source)
    git("commit", "-m", "Update reference", cwd=source)
    git("push", str(remote), "main", cwd=source)
    await service.check(tracked)
    alpha = next(s for s in tracked if s.name == "alpha")
    beta = next(s for s in tracked if s.name == "beta")
    assert alpha.status == Status.OUTDATED
    assert beta.status == Status.CURRENT
    beta_before = json.dumps(lock["skills"]["beta"], sort_keys=True)
    await service.install([alpha], ["codex", "claude-code"], copy=copy)
    updated = service.inventory().skills
    await service.check(updated)
    assert all(s.status == Status.CURRENT for s in updated)
    after = json.loads(service.lock_path(scope).read_text())
    assert json.dumps(after["skills"]["beta"], sort_keys=True) == beta_before
    # Restore a tracked skill after its files were deleted.
    alpha = next(s for s in updated if s.name == "alpha")
    shutil.rmtree(alpha.installed_path)
    if scope == "project":
        await service.installed([alpha])
        assert alpha.installed_path is None
        # Canonical path is recreated by restoration; list enriches its location afterward.
        alpha_path = service.project / ".agents/skills/alpha"
    else:
        alpha_path = service.home / ".agents/skills/alpha"
    await service.install([alpha], ["codex", "claude-code"], copy=copy)
    assert (alpha_path / "SKILL.md").is_file()
    await service.remove(service.inventory().skills)
    assert not service.inventory().skills
    assert not (service.project / ".claude/skills/alpha").exists()


async def test_error_exit_and_json_contract(real_service, source):
    runtime = real_service.runtime
    project = real_service.project
    assert json_rows(await runtime.run(["list", "--json"], project), "list") == []
    with pytest.raises(CommandError):
        await runtime.run(
            [
                "add",
                str(source),
                "--skill",
                "does-not-exist",
                "--agent",
                "codex",
                "--yes",
                "--json",
            ],
            project,
        )
    with pytest.raises(CommandError):
        await runtime.run(["add", str(source), "--list", "--json", "--yes"], project)
    with pytest.raises(CommandError):
        await runtime.run(
            ["add", str(source), "--skill", "alpha", "--agent", "invalid-agent", "--yes", "--json"],
            project,
        )


async def test_pilot_real_full_loop(real_service, source):
    app = SkillsApp(real_service)
    async with app.run_test(size=(140, 45)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.click("#add-source")
        app.query_one("#source", Input).value = str(source)
        await pilot.click("#browse")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.catalog and len(app.available) == 3
        await pilot.press("a")
        assert len(app.available_selected) == 3
        await pilot.click("#install")
        await pilot.pause()
        await pilot.click("#choose-agents")
        app.screen.query_one("#agent-list", SelectionList).select("claude-code")
        await pilot.pause()
        await pilot.click("#use-agents")
        assert app.agent_preferences.load() == "codex claude-code"
        await pilot.click("#apply-install")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not app.catalog and len(app.skills) == 3
        await pilot.press("c")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert all(s.status == Status.CURRENT for s in app.skills)
        (source / "alpha/references/Guide.txt").write_text("updated via Pilot")
        await pilot.press("c")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert next(s for s in app.skills if s.name == "alpha").status == Status.OUTDATED
        await pilot.press("a", "u")
        await pilot.pause()
        await pilot.click("#apply-install")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("c")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert all(s.status == Status.CURRENT for s in app.skills)
        assert app.query_one("#skills", DataTable).row_count == 3
        await pilot.click("#remove")
        await pilot.pause()
        await pilot.click("#confirm")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not app.skills
        assert "Removed" in str(app.query_one("#operation", Static).content)


async def test_refs_scope_isolation_and_confirmed_deprecation(real_service, git_source):
    url, source, remote = git_source
    service = real_service
    project_skills = await service.browse(url, "project")
    global_skills = await service.browse(url + "#release/v1", "global")
    await service.install([s for s in project_skills if s.name == "alpha"], ["codex"])
    await service.install([s for s in global_skills if s.name == "alpha"], ["codex"])
    inventory = service.inventory().skills
    assert len(inventory) == 2
    assert next(s for s in inventory if s.scope == "global").ref == "release/v1"
    shutil.rmtree(source / "alpha")
    git("add", "-A", cwd=source)
    git("commit", "-m", "Remove alpha on main", cwd=source)
    git("push", str(remote), "main", cwd=source)
    await service.check(inventory)
    assert next(s for s in inventory if s.scope == "project").status == Status.DEPRECATED
    assert next(s for s in inventory if s.scope == "global").status == Status.CURRENT
    await service.remove([s for s in inventory if s.scope == "project"])
    assert [s.scope for s in service.inventory().skills] == ["global"]


async def test_global_local_is_explicitly_unsupported(real_service, source):
    available = await real_service.browse(str(source), "global")
    with pytest.raises(CompatibilityError, match="global local-path"):
        await real_service.install(available, ["codex"])
    assert not (real_service.home / ".agents/skills").exists()


async def test_private_missing_or_offline_source_is_not_deprecated(real_service):
    from sky_skills_tui.models import Skill

    skill = Skill(
        "alpha",
        "owner/missing",
        "project",
        real_service.project / "skills-lock.json",
        {
            "sourceType": "git",
            "sourceUrl": "http://127.0.0.1:1/owner/missing.git",
            "skillPath": "alpha/SKILL.md",
            "computedHash": "a" * 64,
        },
    )
    await real_service.check([skill])
    assert skill.status == Status.UNAVAILABLE


async def test_public_github_tree_hash_contract(real_service, request):
    if not request.config.getoption("--network"):
        pytest.skip("Pass --network for GitHub tree SHA coverage")
    service = real_service
    available = await service.browse("vercel-labs/agent-skills#main", "global")
    selected = [s for s in available if s.name == "web-design-guidelines"]
    assert selected
    await service.install(selected, ["codex"])
    tracked = service.inventory().skills
    assert tracked[0].source_type == "github"
    assert len(tracked[0].metadata["skillFolderHash"]) == 40
    await service.check(tracked)
    assert tracked[0].status == Status.CURRENT
    tracked[0].metadata["skillFolderHash"] = "0" * 40
    await service.check(tracked)
    assert tracked[0].status == Status.OUTDATED
    await service.remove(tracked)
