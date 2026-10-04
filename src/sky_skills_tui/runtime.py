"""Private npm installation and cancellable subprocess execution."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
from pathlib import Path

import nodejs_wheel.executable
from filelock import FileLock, Timeout
from platformdirs import user_data_path

SKILLS_VERSION = "1.7.0"
SUPPORTED_VERSIONS = frozenset({SKILLS_VERSION})


class CompatibilityError(RuntimeError):
    pass


class CommandError(RuntimeError):
    pass


class Runtime:
    def __init__(
        self,
        prefix: Path | None = None,
        env: dict[str, str] | None = None,
        *,
        version: str = SKILLS_VERSION,
        allow_unverified: bool = False,
    ) -> None:
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?", version):
            raise CompatibilityError("Use an exact npm skills version, such as 1.7.0.")
        if version not in SUPPORTED_VERSIONS and not allow_unverified:
            raise CompatibilityError(
                f"npm skills {version} is unverified. Tested releases: "
                f"{', '.join(sorted(SUPPORTED_VERSIONS))}. Run the compatibility suite first."
            )
        self.requested_version = version
        self.allow_unverified = allow_unverified
        self.prefix = prefix or user_data_path("sky") / "npm"
        self.env = dict(os.environ if env is None else env)
        root = Path(nodejs_wheel.executable.ROOT_DIR)
        self.node = root / ("node.exe" if os.name == "nt" else "bin/node")
        self.npm = root / "lib/node_modules/npm/bin/npm-cli.js"
        self.env["PATH"] = str(self.node.parent) + os.pathsep + self.env.get("PATH", "")
        self.env.update(
            {"DISABLE_TELEMETRY": "1", "NO_COLOR": "1", "GIT_TERMINAL_PROMPT": "0", "CI": "1"}
        )
        self.entry = self.prefix / "node_modules/skills/bin/cli.mjs"
        self._ready = False
        self._setup_lock = asyncio.Lock()

    async def process(self, args: list[str], cwd: Path, timeout: float = 180) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                env=self.env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name != "nt",
            )
        except OSError as error:
            raise CommandError(str(error)) from error
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                try:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.communicate(), 5)
                except TimeoutError:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    await process.communicate()
            raise
        output = stdout.decode("utf-8", errors="replace")
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace") or output
            raise CommandError(f"Command exited {process.returncode}: {detail[-6000:].strip()}")
        return output

    def version(self) -> str | None:
        try:
            data = json.loads((self.prefix / "node_modules/skills/package.json").read_text())
            return str(data["version"])
        except (OSError, ValueError, KeyError):
            return None

    async def ensure(self, *, upgrade: bool = False) -> str:
        async with self._setup_lock:
            if self._ready and not upgrade:
                version = self.version()
                if version != self.requested_version:
                    self._ready = False
                    raise CompatibilityError(
                        f"Managed npm skills changed during this session: {version!r}; "
                        f"expected {self.requested_version}. Run sky setup --upgrade."
                    )
                return version
            self.prefix.mkdir(parents=True, exist_ok=True)
            lock = FileLock(str(self.prefix / ".setup.lock"))
            while True:
                try:
                    lock.acquire(timeout=0)
                    break
                except Timeout:
                    await asyncio.sleep(0.1)
            try:
                version = self.version()
                if version and version != self.requested_version and not upgrade:
                    raise CompatibilityError(
                        f"Managed npm skills {version} differs from tested "
                        f"{self.requested_version}. Run sky setup --upgrade to repair it."
                    )
                if upgrade or version != self.requested_version or not self.entry.exists():
                    await self.process(
                        [
                            str(self.node),
                            str(self.npm),
                            "install",
                            "--prefix",
                            str(self.prefix),
                            f"skills@{self.requested_version}",
                            "--ignore-scripts",
                            "--no-audit",
                            "--no-fund",
                        ],
                        self.prefix,
                    )
                reported = (
                    await self.process([str(self.node), str(self.entry), "--version"], self.prefix)
                ).strip()
                if reported != self.requested_version:
                    raise CompatibilityError(
                        f"CLI reports {reported!r}, expected {self.requested_version}."
                    )
                self._ready = True
                return self.version() or self.requested_version
            finally:
                lock.release()

    async def run(self, args: list[str], cwd: Path) -> str:
        await self.ensure()
        return await self.process([str(self.node), str(self.entry), *args], cwd)

    async def folder_hash(self, path: Path) -> str:
        helper = Path(__file__).with_name("hash.mjs")
        return (await self.process([str(self.node), str(helper), str(path)], path)).strip()
