import os
import shutil
from pathlib import Path


def _firejail_available() -> bool:
    return shutil.which("firejail") is not None


def wrap_cmd(cmd: list[str], repo_root: str) -> list[str]:
    if os.getenv("SANDBOX_DISABLED", "0") == "1":
        return cmd
    if not _firejail_available():
        return cmd
    home = str(Path.home())
    claude_config = f"{home}/.config/claude"
    anthropic_config = f"{home}/.config/anthropic"
    claude_local = f"{home}/.claude"
    nvm = f"{home}/.nvm"
    return [
        "firejail",
        "--quiet",
        "--net=none",
        f"--read-only=/",
        f"--rw=/tmp",
        f"--rw={repo_root}",
        f"--whitelist={claude_config}",
        f"--whitelist={anthropic_config}",
        f"--whitelist={claude_local}",
        f"--whitelist={nvm}",
        "--seccomp",
        "--caps.drop=all",
        "--noroot",
        "--private-dev",
        "--nosound",
        "--no3d",
        "--noinput",
        "--",
    ] + cmd
