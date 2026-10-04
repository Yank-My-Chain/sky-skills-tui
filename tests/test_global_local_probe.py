"""Research contracts: detect upstream changes independently of Sky's installation guard."""

import pytest

from scripts.probe_global_local import probe

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("copy", [False, True])
async def test_published_global_local_lock_contract(request, copy):
    version = request.config.getoption("--skills-version")
    report = await probe(version, copy=copy)
    assert report["installedAndListed"] and report["removedAndUntracked"]
    assert not report["globalLocalLockWritten"], (
        "Upstream now writes global local-folder locks. Revisit Sky's version-specific policy "
        "and run the complete global local-folder lifecycle before enabling support."
    )


@pytest.mark.parametrize("copy", [False, True])
async def test_built_upstream_global_local_lifecycle(request, copy):
    cli = request.config.getoption("--global-local-cli")
    if cli is None:
        pytest.skip("Pass --global-local-cli to research a built upstream checkout")
    report = await probe(cli=cli, copy=copy)
    assert report["globalLocalLockWritten"]
    assert report["hashMatchesSource"]
    assert report["referenceOnlyUpdateTracked"]
    assert report["originalInstallTimestampPreserved"]
    assert report["missingInstallationRestored"]
    assert report["sourceSkillRemovalDetected"]
    assert report["removedAndUntracked"]
