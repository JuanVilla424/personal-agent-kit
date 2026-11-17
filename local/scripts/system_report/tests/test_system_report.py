"""system_report/main.py — collectors, renderers and the report assembly."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from system_report.main import (  # noqa: E402
    build_report,
    cpu_info,
    disk_info,
    host_identity,
    main,
    memory_info,
    render_md,
    render_table,
)


def test_host_identity_has_the_five_keys():
    host = host_identity()
    assert set(host) == {"hostname", "os", "arch", "python"}
    assert all(v for v in host.values())


def test_cpu_info_reports_cpus_and_load():
    cpu = cpu_info()
    assert int(cpu["cpus"]) >= 1
    assert cpu["load"].count("/") == 2 or cpu["load"] == "n/a"


def test_memory_info_parses_proc_meminfo():
    mem = memory_info()
    assert "total_mib" in mem and "available_mib" in mem
    if mem["total_mib"] != "n/a":
        assert int(mem["total_mib"]) > 0


def test_disk_info_covers_root(tmp_path):
    disks = disk_info()
    assert disks, "at least the root mount"
    assert disks[0]["mount"] == "/"
    for d in disks:
        assert float(d["total_gib"]) >= 0


def test_render_table_contains_every_section():
    host = {"hostname": "h", "os": "Linux 6.x", "arch": "x86_64", "python": "3.12"}
    cpu = {"cpus": "4", "load": "0.10 / 0.20 / 0.30"}
    mem = {"total_mib": "16000", "available_mib": "8000"}
    disks = [
        {"mount": "/", "total_gib": "100.0", "used_gib": "40.0", "free_gib": "60.0", "pct": "40%"}
    ]
    report = render_table(host, cpu, mem, disks, ["  1 root  python"])
    assert "host      : h" in report
    assert "mount       total GiB" in report
    assert "top processes" in report


def test_render_md_uses_markdown_tables():
    disks = [
        {"mount": "/", "total_gib": "100.0", "used_gib": "40.0", "free_gib": "60.0", "pct": "40%"}
    ]
    report = render_md(
        {"hostname": "h", "os": "o", "arch": "a", "python": "3"},
        {"cpus": "4", "load": "n/a"},
        {"total_mib": "1", "available_mib": "1"},
        disks,
        [],
    )
    assert report.startswith("# System report")
    assert "| mount |" in report and "-----" in report


def test_main_table_prints_and_returns_zero(capsys):
    assert main(["--format", "table"]) == 0
    out = capsys.readouterr().out
    assert "System report" in out


def test_main_md_format(capsys):
    assert main(["--format", "md"]) == 0
    assert "# System report" in capsys.readouterr().out


def test_main_out_writes_the_file(tmp_path, capsys):
    dest = tmp_path / "report.md"
    assert main(["--format", "md", "--out", str(dest)]) == 0
    assert dest.exists() and "System report" in dest.read_text()
    assert f"report written to {dest}" in capsys.readouterr().out


def test_cpu_load_na_when_os_does_not_expose_it(monkeypatch):
    """Platforms without getloadavg report n/a instead of crashing."""

    def _raise(*_a):
        raise AttributeError("no loadavg here")

    monkeypatch.setattr(cpu_info.__globals__["os"], "getloadavg", _raise)
    assert cpu_info()["load"] == "n/a"


def test_memory_falls_back_to_sysconf_without_proc(tmp_path, monkeypatch):
    """Without /proc/meminfo (non-Linux) the totals come from sysconf."""

    monkeypatch.setattr(memory_info.__globals__["Path"], "exists", lambda self: False)

    def fake_sysconf(name):
        return {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 4_000_000}[name]

    monkeypatch.setattr(memory_info.__globals__["os"], "sysconf", fake_sysconf)
    mem = memory_info()
    assert mem["total_mib"] == str(4_000_000 * 4096 // 1024 // 1024)
    assert mem["available_mib"] == "n/a"


def test_memory_survives_sysconf_failure(tmp_path, monkeypatch):
    """A failing sysconf leaves the totals as n/a instead of crashing."""

    monkeypatch.setattr(memory_info.__globals__["Path"], "exists", lambda self: False)

    def _boom(_name):
        raise OSError("sysconf unavailable")

    monkeypatch.setattr(memory_info.__globals__["os"], "sysconf", _boom)
    mem = memory_info()
    assert mem["total_mib"] == "n/a" and mem["available_mib"] == "n/a"


def test_disk_info_skips_unreadable_mounts(monkeypatch):
    """A mount that raises OSError is skipped; the rest survive."""

    import system_report.main as m

    real = m.shutil.disk_usage

    def selective(path):
        if str(path) == "/":
            raise OSError("permission denied")
        return real(path)

    monkeypatch.setattr(m.shutil, "disk_usage", selective)
    disks = disk_info()
    assert all(d["mount"] != "/" for d in disks)


def test_process_snapshot_returns_empty_when_ps_fails(monkeypatch):
    """ps unavailable or slow → empty snapshot, never a crash."""

    import system_report.main as m

    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired("ps", 10)

    monkeypatch.setattr(m.subprocess, "run", _boom)
    assert m.process_snapshot() == []


def test_main_reports_os_errors_and_returns_one(monkeypatch, capsys):
    """An OSError while assembling the report prints the error and exits 1."""

    import system_report.main as m

    monkeypatch.setattr(m, "host_identity", lambda: (_ for _ in ()).throw(OSError("disk gone")))
    assert m.main([]) == 1
    assert "disk gone" in capsys.readouterr().err
