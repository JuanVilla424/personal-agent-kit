#!/usr/bin/env python3
"""system_report — a host report generator for the box running this kit.

Pure standard library. Produces a console or markdown report with host identity,
CPU, memory, disk and process snapshot. Designed as the reference package for
the local/scripts layout: README, main, tests, no mandatory dependencies.

Usage:
    python main.py [--format table|md] [--out FILE]

Exit codes: 0 report produced · 1 error.
"""

from __future__ import annotations

import argparse
import datetime
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPORT_VERSION = "1.0.0"


# ── collectors ────────────────────────────────────────────────────────────────


def host_identity() -> dict[str, str]:
    """Host identity: hostname, OS, release, architecture, python version."""
    return {
        "hostname": platform.node() or "unknown",
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine() or "unknown",
        "python": platform.python_version(),
    }


def cpu_info() -> dict[str, str]:
    """CPU count and 1/5/15-minute load average when the OS exposes it."""
    info: dict[str, str] = {"cpus": str(os.cpu_count() or 1)}
    try:
        loads = os.getloadavg()
        info["load"] = " / ".join(f"{v:.2f}" for v in loads)
    except (AttributeError, OSError):
        info["load"] = "n/a"
    return info


def memory_info() -> dict[str, str]:
    """Total and available memory in MiB, parsed from /proc/meminfo (Linux) or sysconf."""
    total = available = None
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            if rest.strip().endswith("kB"):
                values[key.strip()] = int(rest.strip().split()[0]) // 1024
        total = values.get("MemTotal")
        available = values.get("MemAvailable")
    else:
        try:
            import ctypes

            libc = ctypes.CDLL("libc.so.6")  # noqa: F841 — reserved for BSD/macOS paths
        except OSError:
            pass
    if total is None:
        try:
            page = os.sysconf("SC_PAGE_SIZE")
            total = int(os.sysconf("SC_PHYS_PAGES") * page // 1024 // 1024)
        except (ValueError, OSError, AttributeError):
            total = None
    out: dict[str, str] = {
        "total_mib": str(total) if total is not None else "n/a",
        "available_mib": str(available) if available is not None else "n/a",
    }
    return out


def disk_info() -> list[dict[str, str]]:
    """Disk usage for every currently mounted filesystem."""
    rows: list[dict[str, str]] = []
    for path in ("/", "/home", "/tmp", "/var"):
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        rows.append(
            {
                "mount": path,
                "total_gib": f"{usage.total / 1024**3:.1f}",
                "used_gib": f"{usage.used / 1024**3:.1f}",
                "free_gib": f"{usage.free / 1024**3:.1f}",
                "pct": f"{usage.used / usage.total * 100:.0f}%" if usage.total else "n/a",
            }
        )
    return rows


def process_snapshot(limit: int = 5) -> list[str]:
    """Top processes by memory, via ps — skipped silently when ps is unavailable."""
    try:
        out = subprocess.run(
            ["ps", "aux", "--sort=-%mem"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return lines[: limit + 1] if len(lines) > limit else lines[:limit]


# ── rendering ─────────────────────────────────────────────────────────────────


def render_table(host: dict, cpu: dict, mem: dict, disks: list, procs: list[str]) -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = [f"System report — {stamp}", ""]
    out.append(f"host      : {host['hostname']}")
    out.append(f"os        : {host['os']} ({host['arch']})")
    out.append(f"python    : {host['python']}")
    out.append(f"cpus      : {cpu['cpus']}  load(1/5/15): {cpu['load']}")
    out.append(f"mem MiB   : total {mem['total_mib']} / available {mem['available_mib']}")
    out.append("")
    out.append("mount       total GiB  used GiB  free GiB  use%")
    for d in disks:
        out.append(
            f"{d['mount']:<12}{d['total_gib']:>10}  {d['used_gib']:>9}  {d['free_gib']:>8}  {d['pct']:>5}"
        )
    if procs:
        out.append("")
        out.append("top processes (ps aux by mem):")
        out.extend(f"  {ln}" for ln in procs)
    return "\n".join(out)


def render_md(host: dict, cpu: dict, mem: dict, disks: list, procs: list[str]) -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = [
        f"# System report — {stamp}",
        "",
        f"- host: **{host['hostname']}**",
        f"- os: {host['os']} ({host['arch']})",
    ]
    out.append(f"- python: {host['python']}")
    out.append(f"- cpus: {cpu['cpus']} — load 1/5/15: {cpu['load']}")
    out.append(f"- memory MiB: total {mem['total_mib']} / available {mem['available_mib']}")
    out.append("")
    out.append("| mount | total GiB | used GiB | free GiB | use% |")
    out.append("| ----- | --------- | -------- | -------- | ---- |")
    for d in disks:
        out.append(
            f"| {d['mount']} | {d['total_gib']} | {d['used_gib']} | {d['free_gib']} | {d['pct']} |"
        )
    if procs:
        out.append("")
        out.append("```")
        out.extend(procs)
        out.append("```")
    return "\n".join(out) + "\n"


# ── cli ───────────────────────────────────────────────────────────────────────


def build_report(fmt: str = "table") -> str:
    """Assemble the full report in the requested format (table|md)."""
    host, cpu, mem = host_identity(), cpu_info(), memory_info()
    disks, procs = disk_info(), process_snapshot()
    if fmt == "md":
        return render_md(host, cpu, mem, disks, procs)
    return render_table(host, cpu, mem, disks, procs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="system_report", description=__doc__)
    parser.add_argument("--format", choices=("table", "md"), default="table")
    parser.add_argument("--out", default=None, help="write the report to FILE")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        report = build_report(args.format)
    except OSError as e:
        print(f"system_report: error: {e}", file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"report written to {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
