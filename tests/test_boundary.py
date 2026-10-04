import asyncio
import json
import sys

import pytest

from sky_skills_tui.runtime import CompatibilityError, Runtime
from sky_skills_tui.service import parse_available
from sky_skills_tui.upstream import json_rows


def test_list_adapter_handles_plugin_headers_and_ansi():
    output = (
        "◇  Available Skills\n\nPlugin Title\n│    \x1b[36malpha\x1b[0m\n│\n"
        "│      Alpha description\n│    beta\n│      Beta description\n"
        "└  Use --skill <name>"
    )
    assert parse_available(output) == [("alpha", "Alpha description"), ("beta", "Beta description")]


@pytest.mark.parametrize("output", ["[]", "Available Skills\nalpha", "New CLI output"])
def test_list_adapter_reports_drift(output):
    with pytest.raises(CompatibilityError):
        parse_available(output)


@pytest.mark.parametrize("output", ['{"skills":[]}', "banner\n[]", '[{"name":"alpha"}]'])
def test_json_boundary_reports_drift(output):
    with pytest.raises(CompatibilityError):
        json_rows(output, "list")


def test_install_boundary_recognizes_failure():
    assert json_rows('[{"name":"alpha","status":"skipped","reason":"missing"}]', "add")
    with pytest.raises(CompatibilityError):
        json_rows('[{"name":"alpha","status":"success"}]', "add")


def test_runtime_rejects_unknown_and_non_exact_versions(tmp_path):
    with pytest.raises(CompatibilityError, match="unverified"):
        Runtime(tmp_path, version="9.9.9")
    with pytest.raises(CompatibilityError, match="exact"):
        Runtime(tmp_path, version="latest", allow_unverified=True)


async def test_installed_version_drift_is_reported_without_overwriting(tmp_path):
    runtime = Runtime(tmp_path)
    path = tmp_path / "node_modules/skills/package.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": "9.9.9"}))
    with pytest.raises(CompatibilityError, match="differs"):
        await runtime.ensure()
    assert json.loads(path.read_text())["version"] == "9.9.9"
    runtime._ready = True
    with pytest.raises(CompatibilityError, match="changed during"):
        await runtime.ensure()


async def test_subprocess_timeout_and_cancellation(tmp_path):
    runtime = Runtime(tmp_path / "npm")
    with pytest.raises(TimeoutError):
        await runtime.process([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 0.05)
    task = asyncio.create_task(
        runtime.process([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
