"""
Daily backup/restore of audit logs, data/, config files.
Run by agent-bot-backup.service (systemd timer).
"""

import argparse
import datetime
import logging
import os
import subprocess
import tarfile
from pathlib import Path

log = logging.getLogger("backup-restore")

_NOTIFY_DIR = Path(__file__).parent.parent
_BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/var/backups/agent-bot"))
_KEEP_DAYS = 30
_S3_BUCKET = os.getenv("BACKUP_S3_BUCKET", "")
_AWS_BIN = "aws"


def _targets() -> list[Path]:
    return [
        _NOTIFY_DIR / "audit",
        _NOTIFY_DIR / "data",
        _NOTIFY_DIR / "security" / "permissions.yaml",
        (
            _NOTIFY_DIR / ".env.sops.yaml"
            if (_NOTIFY_DIR / ".env.sops.yaml").exists()
            else _NOTIFY_DIR / ".env"
        ),
    ]


def backup() -> None:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    out = _BACKUP_DIR / f"agent-bot-{date}.tar.gz"

    with tarfile.open(out, "w:gz") as tar:
        for target in _targets():
            if target.exists():
                tar.add(target, arcname=target.name)
                log.info("Backed up: %s", target)

    log.info("Backup created: %s (%.1f KB)", out, out.stat().st_size / 1024)

    # S3 copy
    if _S3_BUCKET:
        try:
            subprocess.run(
                [_AWS_BIN, "s3", "cp", str(out), f"s3://{_S3_BUCKET}/bot-backups/"],
                check=True,
                timeout=120,
            )
            log.info("Uploaded to S3: %s", _S3_BUCKET)
        except Exception as e:
            log.warning("S3 upload failed: %s", e)

    # Rotate old backups
    cutoff = datetime.datetime.now() - datetime.timedelta(days=_KEEP_DAYS)
    for old in _BACKUP_DIR.glob("agent-bot-*.tar.gz"):
        try:
            date_str = old.stem.replace("agent-bot-", "")
            old_date = datetime.datetime.fromisoformat(date_str)
            if old_date < cutoff:
                old.unlink()
                log.info("Deleted old backup: %s", old)
        except Exception:
            continue


def restore(archive_path: str) -> None:
    archive = Path(archive_path)
    if not archive.exists():
        raise FileNotFoundError(archive_path)
    restore_dir = _NOTIFY_DIR / "restore_tmp"
    restore_dir.mkdir(exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(restore_dir)
    log.info("Extracted to %s — review and move manually", restore_dir)
    print(f"Extracted to {restore_dir}")
    print("Review the contents and manually move files to restore state.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("path", nargs="?", help="Archive path for restore")
    args = parser.parse_args()
    if args.action == "backup":
        backup()
    else:
        if not args.path:
            parser.error("restore requires <path>")
        restore(args.path)
