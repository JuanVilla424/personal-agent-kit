# 🖥️ system_report

System report generator for the machine running this kit. Pure standard library — no
dependencies beyond Python 3.11+. Part of [local/scripts](../README.md).

## 🚀 Usage

```bash
python main.py                     # console report
python main.py --format md         # markdown report
python main.py --out report.txt    # write to a file
```

Exit code is `0` when the report is produced, `1` on error.

## 🧩 What it reports

- Host identity (hostname, OS, architecture, Python version)
- CPU count and load average (when the OS exposes it)
- Memory (total/available from `/proc/meminfo` on Linux, `sysconf` elsewhere)
- Disk usage for every mounted filesystem (`shutil.disk_usage`)
- Top-level processes snapshot (when `ps` is available)

## 🧪 Tests

```bash
python -m pytest tests/ -q
```

## 📜 License

Apache-2.0 — see the repo [LICENSE](../../LICENSE).
