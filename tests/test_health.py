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


async def test_check_runs_sources_concurrently_with_progress_and_batched_hashes(
    isolated, source, tmp_path, monkeypatch
):
    home, project = isolated
    runtime = Runtime(tmp_path / "npm")
    service = SkillsService(project, runtime, home)
    names = ["alpha", "beta", "gamma"]
    hashes = await runtime.folder_hashes([source / name for name in names])
    assert hashes == [await runtime.folder_hash(source / name) for name in names]
    copy = tmp_path / "copy"
    shutil.copytree(source, copy)
    (copy / "beta/z.txt").write_text("changed upstream")
    skills = [
        Skill(
            name,
            str(root),
            "project",
            project / "skills-lock.json",
            {"sourceType": "local", "computedHash": expected},
        )
        for root in (source, copy)
        for name, expected in zip(names, hashes, strict=True)
    ]
    processes = []
    original = runtime.process

    async def recording(args, cwd, timeout=180):
        processes.append(args)
        return await original(args, cwd, timeout)

    monkeypatch.setattr(runtime, "process", recording)
    progress = []
    await service.check(
        skills, lambda done, total, group: progress.append((done, total, len(group)))
    )
    assert progress == [(1, 2, 3), (2, 2, 3)]
    assert len(processes) == 2, "one hash process per source, not per skill"
    assert [s.status for s in skills] == [Status.CURRENT] * 4 + [Status.OUTDATED, Status.CURRENT]


async def test_hash_algorithm_follows_release_and_lock_schema(isolated, source, tmp_path):
    home, project = isolated
    legacy_runtime = Runtime(tmp_path / "npm", version="1.7.0")
    v2_runtime = Runtime(tmp_path / "npm", version="1.9.0")
    folder = source / "alpha"
    legacy, v2 = await legacy_runtime.folder_hash(folder), await v2_runtime.folder_hash(folder)
    assert legacy != v2
    assert await legacy_runtime.folder_hash_variants([folder]) == [{"legacy": legacy, "v2": v2}]

    def skill(scope, version, expected):
        hash_key = "skillFolderHash" if scope == "global" else "computedHash"
        return Skill(
            "alpha",
            str(source),
            scope,
            project / "skills-lock.json",
            {"sourceType": "local", hash_key: expected},
            lock_version=version,
        )

    # A schema 1 project lock keeps its legacy hash until upstream migrates it; global
    # locks stayed at schema 3, so they may hold either algorithm's hash.
    skills = [
        skill("project", 1, legacy),
        skill("project", 2, v2),
        skill("project", 1, v2),
        skill("project", 2, legacy),
        skill("global", 3, legacy),
        skill("global", 3, v2),
    ]
    await SkillsService(project, v2_runtime, home).check(skills)
    assert [s.status for s in skills] == [Status.CURRENT] * 2 + [Status.OUTDATED] * 2 + [
        Status.CURRENT
    ] * 2


async def test_v2_hash_matches_upstream_normalisation_and_exclusions(tmp_path):
    runtime = Runtime(tmp_path / "npm", version="1.9.0")
    lf, crlf = tmp_path / "lf", tmp_path / "crlf"
    for root, text in ((lf, b"a\nb\n"), (crlf, b"a\r\nb\r\n")):
        root.mkdir()
        (root / "SKILL.md").write_bytes(text)
    lf_hashes, crlf_hashes = await runtime.folder_hash_variants([lf, crlf])
    assert lf_hashes["v2"] == crlf_hashes["v2"]
    assert lf_hashes["legacy"] != crlf_hashes["legacy"]
    before = await runtime.folder_hash(lf)
    (lf / "metadata.json").write_text("{}")
    (lf / "__pycache__").mkdir()
    (lf / "__pycache__/x.pyc").write_text("cache")
    assert await runtime.folder_hash(lf) == before
    (lf / "node_modules").mkdir()
    (lf / "node_modules/dep.js").write_text("counted since 1.8.0")
    assert await runtime.folder_hash(lf) != before
