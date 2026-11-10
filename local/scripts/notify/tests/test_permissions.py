import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_default_user_allowed():
    from security.permissions import check

    d = check("999999999999999999")
    assert d.allowed
    assert d.role == "user"
    assert "Read" in d.allowed_tools


def test_unknown_user_defaults_to_user():
    from security.permissions import check

    d = check("000000000000000001")
    assert d.allowed
    assert d.role == "user"
    assert d.budget_usd == 1.00


def test_quiet_hours_disabled_by_default():
    from security.permissions import is_quiet_hours

    # Default permissions.yaml has quiet_hours.enabled=false
    assert not is_quiet_hours("123456789")


def test_needs_2fa_for_dangerous_tools():
    from security.permissions import needs_2fa, Decision

    d = Decision(
        allowed=True,
        reason="ok",
        role="admin",
        allowed_tools=["Read", "Bash", "Edit", "Write"],
        requires_2fa=True,
    )
    assert needs_2fa(d, ["Bash"])
    assert not needs_2fa(d, ["Read"])
