"""system_report/main.py — collectors, renderers and the report assembly."""

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
