"""local/brain-ui — the brain page as it ships: its engine untouched, its text in one catalog,
nothing asked of another server."""

import hashlib
import re
from pathlib import Path

UI = Path(__file__).resolve().parents[4] / "local" / "brain-ui"
PAGE = (UI / "index.html").read_text(encoding="utf-8")
LIVE = (UI / "live.js").read_text(encoding="utf-8")


def _catalog() -> set[str]:
    """The keys of the page's text catalog (I18N.en in index.html)."""
    block = PAGE[PAGE.index("const I18N = {") : PAGE.index("const LANGS = ")]
    return set(re.findall(r"(?:^|[{,])\s*([A-Za-z_][A-Za-z0-9_]*): (?=[\"`]|name =>)", block, re.M))


def test_the_vendored_engine_is_the_published_one():
    listed = dict(
        re.findall(
            r"\| `([^`]+)`\s+\|[^|]+\| `([0-9a-f]{64})` \|",
            (UI / "vendor" / "README.md").read_text("utf-8"),
        )
    )
    assert set(listed) == {"three.min.js", "OrbitControls.js", "LICENSE-three.txt"}
    for name, sha256 in listed.items():
        assert hashlib.sha256((UI / "vendor" / name).read_bytes()).hexdigest() == sha256, name


def test_the_page_asks_no_other_server_for_anything():
    loaded = re.findall(r"<(?:script|link|img)\b[^>]*\b(?:src|href)=\"([^\"]+)\"", PAGE)
    assert loaded and not [url for url in loaded if "//" in url]
    assert not re.search(r"\bfetch\(\s*[\"'`]https?:", PAGE + LIVE)


def test_every_text_the_page_shows_comes_from_its_catalog():
    catalog = _catalog()
    used = set(re.findall(r'data-i18n(?:-aria|-title)?="([A-Za-z0-9_]+)"', PAGE))
    named = re.findall(r'\bt\("([A-Za-z0-9_]+)"\)|key: "([A-Za-z0-9_]+)"', PAGE)
    used |= {key for pair in named for key in pair if key}
    used |= set(re.findall(r'\b(?:say|shown)\("([A-Za-z0-9_]+)"', LIVE))
    for table in re.findall(r"const (?:STATUS|CHECKS|CYCLES) = \{([^}]+)\}", LIVE):
        used |= set(re.findall(r': "([A-Za-z0-9_]+)"', table))
    assert len(used) > 60 and not sorted(used - catalog)


def test_the_page_ships_one_language_and_no_view_of_a_part_the_kit_does_not_have():
    assert re.findall(r"^    ([a-z]{2}(?:-[A-Z]{2})?): \{$", PAGE, re.M) == ["en"]
    assert "data-lang=" not in PAGE and 'id="operations"' not in PAGE
    assert [tab for tab in re.findall(r'role="tab"[^>]*aria-controls="([a-z]+)"', PAGE)] == [
        "live",
        "health",
    ]
