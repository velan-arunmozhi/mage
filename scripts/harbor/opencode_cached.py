"""OpenCode agent that uses a prefetched binary when the mount matches the pin.

Harbor calls install() for every trial. This subclass keeps the system
packages the run needs (bash, coreutils) and skips nvm plus npm when
/opt/mage-opencode already holds the pinned opencode-ai build.
"""

from __future__ import annotations

from harbor.agents.installed.opencode import OpenCode
from harbor.environments.base import BaseEnvironment

from scripts.harbor.cache_layout import (
    OPENCODE_VERSION,
    link_command,
    probe_command,
    version_matches,
)


class OpenCodeCached(OpenCode):
    async def install(self, environment: BaseEnvironment) -> None:
        await self.ensure_system_dependencies(environment, ("bash", "coreutils"))
        pinned = self._version or OPENCODE_VERSION
        if pinned != OPENCODE_VERSION:
            await super().install(environment)
            return
        probe = await environment.exec(command=probe_command(), user="root")
        stdout = probe.stdout or ""
        if probe.return_code == 0 and version_matches(stdout, pinned):
            await self.exec_as_root(environment, link_command())
            return
        await super().install(environment)
