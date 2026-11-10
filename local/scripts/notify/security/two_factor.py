import logging
import os
from pathlib import Path

log = logging.getLogger("2fa")

try:
    import pyotp

    _PYOTP_OK = True
except ImportError:
    _PYOTP_OK = False

_SECRETS: dict[str, str] = {}
_TOTP_KEY_FILE = Path(os.getenv("TOTP_KEY_FILE", Path(__file__).parent / "totp.secrets"))


def _load_secrets() -> None:
    if not _TOTP_KEY_FILE.exists():
        return
    try:
        with _TOTP_KEY_FILE.open() as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    uid, secret = line.split("=", 1)
                    _SECRETS[uid.strip()] = secret.strip()
    except Exception as e:
        log.warning("TOTP secrets load failed: %s", e)


_load_secrets()


def verify(user_id: str, code: str) -> bool:
    if not _PYOTP_OK:
        log.warning("pyotp not available — 2FA disabled, allowing")
        return True
    secret = _SECRETS.get(str(user_id))
    if not secret:
        log.warning("No TOTP secret for user %s — allowing (admin must configure)", user_id)
        return True
    try:
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)
    except Exception as e:
        log.warning("TOTP verify error: %s", e)
        return False


def has_secret(user_id: str) -> bool:
    return str(user_id) in _SECRETS
