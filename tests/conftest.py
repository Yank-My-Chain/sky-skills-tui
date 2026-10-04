from __future__ import annotations

import os
from pathlib import Path

import pytest

from sky_skills_tui.runtime import SKILLS_VERSION, Runtime
from sky_skills_tui.service import SkillsService

from .git_server import git, serve_git


def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", help="Run real npm contract tests")
    parser.addoption("--network", action="store_true", help="Also test a public GitHub source")
    parser.addoption("--skills-version", default=SKILLS_VERSION, help="Exact npm release to probe")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "integration" in item.keywords and not config.getoption("--integration"):
            item.add_marker(
                pytest.mark.skip(reason="Pass --integration for real npm lifecycle tests")
            )


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    for key, value in {
        "HOME": home,
        "USERPROFILE": home,
        "CODEX_HOME": home / ".codex",
        "CLAUDE_CONFIG_DIR": home / ".claude",
        "XDG_STATE_HOME": home / ".local/state",
        "XDG_CONFIG_HOME": home / ".config",
        "XDG_DATA_HOME": home / ".local/share",
    }.items():
        monkeypatch.setenv(key, str(value))
    return home, project


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    for name in ("alpha", "beta", "gamma"):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name} fixture skill\n---\n\n# {name}\nVersion one.\n"
        )
        (folder / "references").mkdir()
        (folder / "references/Guide.txt").write_text("reference content\n")
        (folder / "z.txt").write_text("sort after uppercase?\n")
    return root


@pytest.fixture
async def real_service(isolated, request):
    home, project = isolated
    # Shared immutable npm installation within a test session; all skill state is isolated.
    prefix = Path(str(request.config.cache.makedir("npm-contract")))
    version = request.config.getoption("--skills-version")
    prefix = prefix / version
    runtime = Runtime(prefix, dict(os.environ), version=version, allow_unverified=True)
    await runtime.ensure()
    return SkillsService(project, runtime, home)


@pytest.fixture
def git_source(source, tmp_path):
    git("init", "-b", "main", cwd=source)
    git("config", "user.name", "Contract Tests", cwd=source)
    git("config", "user.email", "tests@example.invalid", cwd=source)
    git("add", ".", cwd=source)
    git("commit", "-m", "Initial skills", cwd=source)
    git("branch", "release/v1", cwd=source)
    remote_root = tmp_path / "remotes"
    remote = remote_root / "owner/repo.git"
    remote.parent.mkdir(parents=True)
    git("clone", "--bare", str(source), str(remote), cwd=source)
    server, thread = serve_git(remote_root)
    url = f"http://127.0.0.1:{server.server_port}/owner/repo.git"
    try:
        yield url, source, remote
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
