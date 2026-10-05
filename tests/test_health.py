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


async def test_check_through_symlinked_temporary_directory(
    isolated, git_source, tmp_path, monkeypatch
):
    """Reproduce macOS /var -> /private/var for both Git-tree and folder hashes."""
    from pathlib import Path

    from .git_server import git

    home, project = isolated
    url, source, _ = git_source
    real_temp = tmp_path / "private-var"
    real_temp.mkdir()
    alias = tmp_path / "var"
    alias.symlink_to(real_temp, target_is_directory=True)
    monkeypatch.setattr("tempfile.tempdir", str(alias))
    runtime = Runtime(tmp_path / "npm")
    service = SkillsService(project, runtime, home)
    folder_hash = await runtime.folder_hash(source / "alpha")
    tree_hash = git("rev-parse", "HEAD:alpha", cwd=source).strip()
    skills = [
        Skill(
            "alpha",
            url,
            scope,
            project / "skills-lock.json",
            {"sourceType": "git", "skillPath": "alpha/SKILL.md", hash_key: expected},
        )
        for scope, hash_key, expected in (
            ("global", "skillFolderHash", tree_hash),
            ("project", "computedHash", folder_hash),
        )
    ]
    await service.check(skills)
    assert [s.status for s in skills] == [Status.CURRENT, Status.CURRENT]
    assert not list(Path(alias).iterdir())


async def test_resolved_root_still_rejects_escaping_recorded_paths(isolated, source, tmp_path):
    home, project = isolated
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    skill = Skill(
        "alpha",
        str(alias),
        "project",
        project / "skills-lock.json",
        {"sourceType": "local", "skillPath": "../outside/SKILL.md", "computedHash": "abc"},
    )
    await SkillsService(project, Runtime(tmp_path / "npm"), home).check([skill])
    assert skill.status == Status.UNSUPPORTED
    assert skill.reason == "Unsafe skillPath in lock."
