"""Pinned OpenCode install shared by prefetch and the cached Harbor agent.

The cache lives on the AMD64 host and is mounted into each task container.
Harbor's OpenCode.install() otherwise runs nvm and npm inside every trial.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

NODE_VERSION = "22.21.0"
OPENCODE_VERSION = "1.19.3"
CACHE_IN_CONTAINER = "/opt/mage-opencode"
OPENCODE_BIN = f"{CACHE_IN_CONTAINER}/prefix/bin/opencode"
NODE_BIN = f"{CACHE_IN_CONTAINER}/node/bin/node"
VERSION_FILE = f"{CACHE_IN_CONTAINER}/VERSION"


def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "mage-opencode"


def node_dist_name(machine: str) -> str:
    if machine in {"x86_64", "amd64"}:
        return "linux-x64"
    if machine in {"aarch64", "arm64"}:
        return "linux-arm64"
    raise ValueError(f"Unsupported machine for the OpenCode cache: {machine}")


def node_tarball_url(version: str, machine: str) -> str:
    dist = node_dist_name(machine)
    name = f"node-v{version}-{dist}.tar.xz"
    return f"https://nodejs.org/dist/v{version}/{name}"


def cache_ready(cache: Path, version: str = OPENCODE_VERSION) -> bool:
    version_file = cache / "VERSION"
    opencode = cache / "prefix" / "bin" / "opencode"
    node = cache / "node" / "bin" / "node"
    if not version_file.is_file() or not opencode.is_file() or not node.is_file():
        return False
    if not os.access(opencode, os.X_OK) or not os.access(node, os.X_OK):
        return False
    recorded = version_file.read_text(encoding="utf-8").strip()
    return recorded == version


def probe_command() -> str:
    return (
        "printf '%s\\n' binary && "
        f"test -x {OPENCODE_BIN} && "
        f"{OPENCODE_BIN} --version && "
        "printf '%s\\n' pinned && "
        f"cat {VERSION_FILE}"
    )


def link_command() -> str:
    return (
        f"ln -sfn {OPENCODE_BIN} /usr/local/bin/opencode && "
        f"ln -sfn {NODE_BIN} /usr/local/bin/node"
    )


def version_matches(stdout: str, pinned: str) -> bool:
    """True when the mounted binary and VERSION file both report pinned."""
    lines = stdout.splitlines()
    try:
        binary_at = lines.index("binary")
        pinned_at = lines.index("pinned")
    except ValueError:
        return False
    if pinned_at <= binary_at:
        return False
    binary_lines = [line.strip() for line in lines[binary_at + 1 : pinned_at] if line.strip()]
    pinned_lines = [line.strip() for line in lines[pinned_at + 1 :] if line.strip()]
    if not binary_lines or pinned_lines != [pinned]:
        return False
    return pinned in binary_lines[-1]


def mount_spec(cache: Path) -> dict[str, object]:
    return {
        "type": "bind",
        "source": str(cache),
        "target": CACHE_IN_CONTAINER,
        "read_only": True,
    }


def _extract_node(archive: Path, cache: Path) -> None:
    extract_root = cache / "src" / "node"
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        tar.extractall(extract_root, filter="data")
    children = [child for child in extract_root.iterdir() if child.is_dir()]
    node_home = children[0] if len(children) == 1 else extract_root
    link = cache / "node"
    if link.is_symlink() or link.exists():
        if link.is_dir() and not link.is_symlink():
            shutil.rmtree(link)
        else:
            link.unlink()
    link.symlink_to(node_home, target_is_directory=True)
    node = link / "bin" / "node"
    node.chmod(node.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def prefetch(cache: Path, machine: str | None = None) -> None:
    """Download pinned Node and opencode-ai when the cache is missing."""
    cache.mkdir(parents=True, exist_ok=True)
    if cache_ready(cache):
        print(f"OpenCode cache ready: {cache}")
        return
    machine = machine or platform.machine()
    url = node_tarball_url(NODE_VERSION, machine)
    src = cache / "src"
    src.mkdir(parents=True, exist_ok=True)
    archive = src / "node.tar.xz"
    if not archive.is_file():
        print(f"Downloading {url}")
        urllib.request.urlretrieve(url, archive)
    if not (cache / "node" / "bin" / "node").is_file():
        _extract_node(archive, cache)
    npm = cache / "node" / "bin" / "npm"
    prefix = cache / "prefix"
    prefix.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = str(cache / "node" / "bin") + os.pathsep + env.get("PATH", "")
    print(f"Installing opencode-ai@{OPENCODE_VERSION} into {prefix}")
    subprocess.run(
        [str(npm), "install", "-g", f"opencode-ai@{OPENCODE_VERSION}", "--prefix", str(prefix)],
        check=True,
        env=env,
    )
    opencode = prefix / "bin" / "opencode"
    reported = subprocess.run(
        [str(opencode), "--version"],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    if OPENCODE_VERSION not in reported.stdout:
        raise SystemExit(
            f"Cached opencode reported {reported.stdout!r}, expected {OPENCODE_VERSION}."
        )
    (cache / "VERSION").write_text(OPENCODE_VERSION + "\n", encoding="utf-8")
    print(f"OpenCode cache ready: {cache}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pin Node 22 and opencode-ai on this host.")
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="Exit 0 when the pinned cache is present.")
    args = parser.parse_args(argv)
    cache = args.cache if args.cache is not None else default_cache_dir()
    if args.check:
        if cache_ready(cache):
            print(f"OpenCode cache ready: {cache}")
            return 0
        print(f"OpenCode cache is absent: {cache}", file=sys.stderr)
        return 1
    prefetch(cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
