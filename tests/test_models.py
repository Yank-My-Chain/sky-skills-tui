import json

import pytest

from sky_skills_tui.models import (
    Skill,
    global_lock,
    read_inventory,
    sanitized_name,
    validate_lock_for_mutation,
)


def write_lock(path, skills, version=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": version, "skills": skills}))


def test_both_scopes_metadata_and_missing_files(isolated):
    home, project = isolated
    entry = {"source": "owner/repo", "sourceType": "github", "ref": "release/v2", "custom": 9}
    write_lock(project / "skills-lock.json", {"alpha": entry})
    write_lock(global_lock(home), {"alpha": entry}, 3)
    folder = project / ".agents/skills/alpha"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("installed")
    before = (project / "skills-lock.json").read_bytes()
    inventory = read_inventory(project, home)
    assert len(inventory.skills) == 2
    assert len({s.key for s in inventory.skills}) == 2
    assert sum(s.installed_path is not None for s in inventory.skills) == 1
    assert all(s.metadata["custom"] == 9 for s in inventory.skills)
    assert all(s.source_input == "owner/repo#release/v2" for s in inventory.skills)
    assert (project / "skills-lock.json").read_bytes() == before


def test_xdg_and_default_global_location(isolated, monkeypatch):
    home, _ = isolated
    assert global_lock(home) == home / ".local/state/skills/.skill-lock.json"
    monkeypatch.delenv("XDG_STATE_HOME")
    assert global_lock(home) == home / ".agents/.skill-lock.json"


@pytest.mark.parametrize("payload", ["{", "[]", '{"version":1,"skills":[]}', "<<<<<<< HEAD"])
def test_invalid_locks_are_visible_and_block_mutations(isolated, payload):
    home, project = isolated
    lock = project / "skills-lock.json"
    lock.write_text(payload)
    assert read_inventory(project, home).warnings
    with pytest.raises(ValueError, match="Refusing"):
        validate_lock_for_mutation(lock, "project")
    assert lock.read_text() == payload


@pytest.mark.parametrize("version", [0, 2, 4, "1", True])
def test_schema_drift_preserves_entries(isolated, version):
    home, project = isolated
    path = project / "skills-lock.json"
    write_lock(path, {"alpha": {"source": "owner/repo"}}, version)
    inventory = read_inventory(project, home)
    assert inventory.skills[0].name == "alpha"
    assert inventory.warnings
    with pytest.raises(ValueError):
        validate_lock_for_mutation(path, "project")


def test_relative_local_sources_resolve_against_lock(isolated):
    _, project = isolated
    skill = Skill(
        "alpha", "../source", "project", project / "skills-lock.json", {"sourceType": "local"}
    )
    assert skill.source_input == str(project.parent / "source")
    assert sanitized_name("../Unsafe Skill---Name") == "unsafe-skill-name"
    assert sanitized_name("...") == "unnamed-skill"
