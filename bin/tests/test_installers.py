"""Behavior of the installers: options, and the steps that need no network, sudo or systemd."""

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL = REPO_ROOT / "bin" / "install.sh"
LIB = REPO_ROOT / "bin" / "_lib.sh"
TIMEOUT_SECONDS = 60
OWN_AGENTS = {"infra-agent", "security-agent", "reports-agent", "database"}


def _run_installer(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL), *args],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def _lib(snippet: str, checkout: Path, **env: str) -> subprocess.CompletedProcess:
    """Run a snippet with bin/_lib.sh sourced and REPO_ROOT pointing at a scratch checkout."""
    code = f'source "{LIB}"; REPO_ROOT="{checkout}"; {snippet}'
    return subprocess.run(
        ["bash", "-c", code],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
        env={**os.environ, **env},
        check=False,
    )


def test_dry_run_defaults_to_the_core_install():
    result = _run_installer("--dry-run")

    assert result.returncode == 0
    assert "Local brain: yes" in result.stdout
    for optional in ("BMAD", "OpenCode", "Voice", "Slack", "Dev tools"):
        assert f"{optional}: no" in result.stdout
    assert "nothing was changed" in result.stdout


def test_flags_decide_every_option():
    result = _run_installer(
        "--dry-run",
        "--no-brain",
        "--with-bmad",
        "--with-opencode",
        "--with-tts",
        "--with-slack",
        "--with-dev-tools",
        "--language",
        "pt-BR",
    )

    assert result.returncode == 0
    assert "Local brain: no" in result.stdout
    for optional in ("BMAD", "OpenCode", "Voice", "Slack", "Dev tools"):
        assert f"{optional}: yes" in result.stdout
    assert "Language: pt-BR" in result.stdout


def test_dry_run_changes_nothing():
    policy = REPO_ROOT / "ai18n.yaml"
    before = policy.read_bytes()

    _run_installer("--dry-run", "--language", "es")

    assert policy.read_bytes() == before


@pytest.mark.parametrize(
    "args",
    [
        ("--nope",),
        ("--with-nope",),
        ("--no-nope",),
        ("--language",),
        ("--language", "Spanish"),
        ("--language", "es_CO"),
        ("--opencode-model",),
    ],
)
def test_bad_options_stop_before_any_change(args):
    result = _run_installer("--dry-run", *args)

    assert result.returncode == 2
    assert "see --help" in result.stderr
    assert "Install plan" not in result.stdout


def test_help_documents_every_flag():
    result = _run_installer("--help")

    assert result.returncode == 0
    for flag in ("--yes", "--dry-run", "--language", "--opencode-model"):
        assert flag in result.stdout
    for feature in ("brain", "bmad", "opencode", "tts", "slack", "dev-tools"):
        assert f"--with-{feature}" in result.stdout
        assert f"--no-{feature}" in result.stdout


def test_opencode_is_installed_from_the_package_that_ships_the_pinned_major():
    lib = LIB.read_text(encoding="utf-8")
    pin = (REPO_ROOT / "configs" / "opencode.version").read_text(encoding="utf-8").strip()
    assert 'OPENCODE_NPM_PACKAGE="@opencode/cli"' in lib
    assert '"$OPENCODE_NPM_PACKAGE@$oc_pin"' in lib
    assert pin.split(".")[0] == "2"  # opencode-ai stops at 1.x


@pytest.mark.skipif(shutil.which("opencode") is None, reason="needs the opencode CLI")
def test_the_server_unit_uses_only_flags_the_installed_opencode_accepts():
    unit = (REPO_ROOT / "bin" / "opencode" / "opencode-server.service").read_text(encoding="utf-8")
    exec_start = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    shown = subprocess.run(
        ["opencode", "serve", "--help"], capture_output=True, text=True, timeout=60, check=True
    )
    accepted = shown.stdout + shown.stderr  # some versions print their help to stderr
    for flag in re.findall(r"\s(--[a-z-]+)", exec_start):
        assert flag in accepted, f"opencode serve does not accept {flag}"


def test_installers_never_create_a_linux_user():
    pattern = re.compile(r"\b(useradd|adduser|groupadd|addgroup)\b")
    for script in (LIB, INSTALL, REPO_ROOT / "bin" / "install-opencode.sh"):
        assert not pattern.search(script.read_text(encoding="utf-8")), script


def test_code_never_assumes_a_home_directory():
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py", "*.sh", "*.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    offenders = [
        name
        for name in listed.stdout.splitlines()
        if "/tests/" not in name
        and name != "bin/_lib.sh"  # it holds the placeholders it renders
        and re.search(r"/home/(<user>|[a-z])", (REPO_ROOT / name).read_text(encoding="utf-8"))
    ]
    assert not offenders


@pytest.mark.parametrize(
    "unit",
    [
        "local/scripts/memory_index/agent-memory.service",
        "bin/opencode/opencode-server.service",
        *sorted(
            str(p.relative_to(REPO_ROOT))
            for p in (REPO_ROOT / "local" / "scripts" / "notify").glob("agent-bot*.service")
        ),
    ],
)
def test_units_render_for_any_user_and_any_checkout_path(unit, tmp_path):
    checkout = tmp_path / "somewhere" / "else"
    fake_home = tmp_path / "home-of-anyone"
    # wherever this user's claude and opencode live, the units point there and nowhere fixed
    tools = tmp_path / "tools-of-anyone"
    tools.mkdir()
    for tool in ("claude", "opencode"):
        (tools / tool).write_text("#!/bin/sh\n", encoding="utf-8")
        (tools / tool).chmod(0o755)
    path = f"{tools}:{os.environ['PATH']}"

    result = _lib(
        f'render_placeholders "{REPO_ROOT / unit}"', checkout, HOME=str(fake_home), PATH=path
    )

    assert result.returncode == 0
    assert "<user>" not in result.stdout
    assert "<opencode-bin>" not in result.stdout
    assert "<claude-dir>" not in result.stdout and "v26.1.0" not in result.stdout
    if "PATH=" in result.stdout and "agent-bot" in unit:
        assert f"PATH={tools}:" in result.stdout
    if "opencode-server" in unit:
        assert f"ExecStart={tools}/opencode serve" in result.stdout
    assert "personal-agent-kit" not in result.stdout.replace("Personal Agent Kit", "")
    assert f"WorkingDirectory={checkout}" in result.stdout
    assert re.search(r"^User=\S+$", result.stdout, re.MULTILINE)


def test_env_file_is_rendered_private_and_never_overwritten(tmp_path):
    shutil.copy(REPO_ROOT / ".env.template", tmp_path / ".env.template")

    assert _lib("setup_env_file", tmp_path).returncode == 0

    env_file = tmp_path / ".env"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert f"REPO_ROOT={tmp_path}" in env_file.read_text(encoding="utf-8")
    assert "<user>" not in env_file.read_text(encoding="utf-8").split("<grafana")[0]

    env_file.write_text("KEEP=me\n", encoding="utf-8")
    assert _lib("setup_env_file", tmp_path).returncode == 0
    assert env_file.read_text(encoding="utf-8") == "KEEP=me\n"


def test_a_template_env_gets_a_real_token(tmp_path):
    """The tokens of the template's own comments must never count as configured auth."""
    shutil.copy(REPO_ROOT / ".env.template", tmp_path / ".env")
    (tmp_path / ".venv").symlink_to(REPO_ROOT / ".venv")

    configured = _lib(
        "has_env MEMORY_USER_TOKENS || has_env MEMORY_SERVICE_TOKEN || has_env MEMORY_ADMIN_TOKEN",
        tmp_path,
    )
    no_auth = _lib("env_is_true MEMORY_ALLOW_NO_AUTH", tmp_path)

    assert configured.returncode != 0
    assert no_auth.returncode != 0


def _policy_in(checkout: Path) -> dict:
    lines = (checkout / "ai18n.yaml").read_text(encoding="utf-8").splitlines()
    pairs = (line.split(": ", 1) for line in lines if re.match(r"^[a-z0-9]+: ", line))
    return dict(pairs)


@pytest.mark.parametrize("tag, written", [("es", "es"), ("pt-BR", "pt-BR"), ("no", '"no"')])
def test_language_changes_the_conversation_and_nothing_else(tmp_path, tag, written):
    shutil.copy(REPO_ROOT / "ai18n.yaml", tmp_path / "ai18n.yaml")
    (tmp_path / ".env").write_text("TTS_LANGUAGE=en\nLOG_LEVEL=INFO\n", encoding="utf-8")

    assert _lib(f"PAK_LANGUAGE={tag}; setup_language", tmp_path).returncode == 0

    policy = _policy_in(tmp_path)
    assert policy["respond"] == written
    assert policy["speak"] == written
    assert {policy[surface] for surface in ("document", "code", "instruct", "default")} == {"en"}
    assert f"TTS_LANGUAGE={tag}\n" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_without_a_language_the_policy_stays_untouched(tmp_path):
    shutil.copy(REPO_ROOT / "ai18n.yaml", tmp_path / "ai18n.yaml")
    before = (tmp_path / "ai18n.yaml").read_bytes()

    assert _lib("setup_language", tmp_path).returncode == 0

    assert (tmp_path / "ai18n.yaml").read_bytes() == before


def test_bmad_is_inactive_in_a_clean_tree_and_activates_on_request(tmp_path):
    integrations = tmp_path / ".bmad" / "integrations" / "claude"
    (integrations / "commands" / "bmad" / "core").mkdir(parents=True)
    (integrations / "commands" / "bmad" / "core" / "party.md").write_text("x", encoding="utf-8")
    (integrations / "agents" / "bmad-review").mkdir(parents=True)
    (integrations / "agents" / "bmad-review" / "reviewer.md").write_text("y", encoding="utf-8")

    assert _lib("bmad_active", tmp_path).returncode != 0

    for _ in range(2):  # re-running refreshes the copies
        assert _lib("setup_bmad", tmp_path).returncode == 0

    assert _lib("bmad_active", tmp_path).returncode == 0
    assert (tmp_path / ".claude/commands/bmad/core/party.md").exists()
    assert (tmp_path / ".claude/agents/bmad-review/reviewer.md").exists()
    assert not (tmp_path / ".claude/commands/bmad/bmad").exists()


def test_repo_ships_bmad_inactive():
    tracked_by_default = REPO_ROOT / ".bmad" / "integrations" / "claude" / "commands" / "bmad"
    assert tracked_by_default.is_dir()
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".claude/commands/bmad/x.md"],
        cwd=REPO_ROOT,
        check=False,
    )
    assert ignored.returncode == 0


def _opencode_checkout(checkout: Path) -> None:
    """Copy into a scratch checkout what build-config.sh reads."""
    (checkout / "bin").mkdir(parents=True)
    shutil.copy(LIB, checkout / "bin" / "_lib.sh")
    shutil.copytree(REPO_ROOT / "bin" / "opencode", checkout / "bin" / "opencode")
    for persona_dir in (".bmad/local", ".bmad/core/agents", ".bmad/bmm/agents"):
        shutil.copytree(REPO_ROOT / persona_dir, checkout / persona_dir)


def _build_opencode_config(checkout: Path, home: Path) -> dict:
    result = subprocess.run(
        ["bash", str(checkout / "bin" / "opencode" / "build-config.sh")],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((home / ".config" / "opencode" / "opencode.json").read_text("utf-8"))


@pytest.mark.skipif(shutil.which("jq") is None, reason="build-config.sh needs jq")
def test_opencode_gets_only_the_kits_personas_without_bmad(tmp_path):
    _opencode_checkout(tmp_path / "repo")

    config = _build_opencode_config(tmp_path / "repo", tmp_path)

    assert set(config["agent"]) == OWN_AGENTS
    assert "default_agent" not in config
    assert all(agent["prompt"] for agent in config["agent"].values())


@pytest.mark.skipif(shutil.which("jq") is None, reason="build-config.sh needs jq")
def test_opencode_gets_the_whole_team_with_bmad_active(tmp_path):
    _opencode_checkout(tmp_path / "repo")
    (tmp_path / "repo" / ".claude" / "commands" / "bmad").mkdir(parents=True)

    config = _build_opencode_config(tmp_path / "repo", tmp_path)

    assert OWN_AGENTS < set(config["agent"])
    assert config["default_agent"] == "bmad-master"
    assert all(agent["prompt"] for agent in config["agent"].values())


@pytest.mark.skipif(shutil.which("jq") is None, reason="build-config.sh needs jq")
def test_opencode_gets_the_normalized_language_policy(tmp_path):
    checkout = tmp_path / "repo"
    _opencode_checkout(checkout)
    (checkout / ".venv").symlink_to(REPO_ROOT / ".venv")
    for part in ("src", "schema"):
        shutil.copytree(REPO_ROOT / "helpers/ai18n" / part, checkout / "helpers/ai18n" / part)
    policy = (REPO_ROOT / "ai18n.yaml").read_text(encoding="utf-8")
    (checkout / "ai18n.yaml").write_text(
        policy.replace("respond: en", "respond: es"), encoding="utf-8"
    )

    config = _build_opencode_config(checkout, tmp_path)

    rendered = tmp_path / ".config" / "opencode" / "ai18n-policy.md"
    assert str(rendered) in config["instructions"]
    assert "respond: es" in rendered.read_text(encoding="utf-8")
    assert "Agents get it normalized" not in rendered.read_text(encoding="utf-8")


def test_the_cli_is_linked_for_whoever_installs_and_a_foreign_pak_is_left_alone(tmp_path):
    home = tmp_path / "home"
    result = _lib("setup_cli", REPO_ROOT, HOME=str(home))
    link = home / ".local" / "bin" / "pak"
    assert result.returncode == 0 and link.resolve() == REPO_ROOT / "bin" / "pak"
    assert _lib("setup_cli", REPO_ROOT, HOME=str(home)).returncode == 0  # idempotent
    link.unlink()
    link.write_text("someone else's pak\n", encoding="utf-8")
    result = _lib("setup_cli", REPO_ROOT, HOME=str(home))
    assert "left alone" in result.stdout + result.stderr
    assert link.read_text(encoding="utf-8") == "someone else's pak\n"
