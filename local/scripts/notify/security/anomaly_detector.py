import asyncio
import logging
import time
from collections import deque
from pathlib import Path

from ops import metrics

log = logging.getLogger("anomaly")

_history: deque[dict] = deque(maxlen=200)
_lock = asyncio.Lock()
_SCORE_THRESHOLD = 0.8


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _score(text: str) -> float:
    words = set(text.lower().split())
    # Length penalty: very short or very long
    length_score = min(1.0, max(0.0, (len(text) - 2000) / 3000)) if len(text) > 2000 else 0.0

    # Repetition score: similarity to recent messages
    recent_words = [set(h["text"].lower().split()) for h in list(_history)[-10:]]
    sim_scores = [_jaccard(words, rw) for rw in recent_words] if recent_words else [0.0]
    max_sim = max(sim_scores) if sim_scores else 0.0

    # Combined
    return length_score * 0.4 + max_sim * 0.6


async def check(user_id: str, text: str, window_minutes: int = 10) -> bool:
    now = time.monotonic()
    async with _lock:
        _history.append({"text": text, "user": user_id, "ts": now})
        score = _score(text)
        metrics.anomaly_score.observe(score)
        if score >= _SCORE_THRESHOLD:
            log.warning("Anomaly detected: user=%s score=%.2f", user_id, score)
            return True
    return False


async def alert(user_id: str, text: str) -> None:
    try:
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from notify import notify  # type: ignore

        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: notify(
                level="warning",
                title="Anomaly detected — Slack bot",
                message=f"User {user_id} triggered anomaly detector. Text preview: {text[:200]}",
            ),
        )
    except Exception as e:
        log.warning("Anomaly alert failed: %s", e)
