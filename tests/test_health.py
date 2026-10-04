import shutil

from sky_skills_tui.models import Skill, Status
from sky_skills_tui.runtime import Runtime
from sky_skills_tui.service import SkillsService


async def test_local_health_hashes_references_and_detects_removal(isolated, source, tmp_path):
    home, project = isolated
    runtime = Runtime(tmp_path / "npm")
    service = SkillsService(project, runtime, home)
    skills = [
        Skill(
            name,
            str(source),
            "project",
            project / "skills-lock.json",
            {"sourceType": "local", "computedHash": await runtime.folder_hash(source / name)},
        )
        for name in ("alpha", "beta", "gamma")
    ]
    (source / "beta/references/Guide.txt").write_text("changed reference only")
    shutil.rmtree(source / "gamma")
    await service.check(skills)
    assert [s.status for s in skills] == [Status.CURRENT, Status.OUTDATED, Status.DEPRECATED]


async def test_unknown_sources_and_missing_local_source(isolated, tmp_path):
    home, project = isolated
    service = SkillsService(project, Runtime(tmp_path / "npm"), home)
    missing = Skill(
        "alpha",
        str(tmp_path / "gone"),
        "project",
        project / "skills-lock.json",
        {"sourceType": "local"},
    )
    unknown = Skill(
        "beta",
        "https://example.com",
        "project",
        project / "skills-lock.json",
        {"sourceType": "well-known"},
    )
    await service.check([missing, unknown])
    assert missing.status == Status.DEPRECATED
    assert unknown.status == Status.UNSUPPORTED


async def test_ambiguous_git_source_is_not_reinterpreted_as_github(isolated, tmp_path):
    home, project = isolated
    service = SkillsService(project, Runtime(tmp_path / "npm"), home)
    skill = Skill(
        "alpha",
        "org/repo",
        "project",
        project / "skills-lock.json",
        {"sourceType": "gitlab", "computedHash": "abc"},
    )
    await service.check([skill])
    assert skill.status == Status.UNSUPPORTED
