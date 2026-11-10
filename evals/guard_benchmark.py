#!/usr/bin/env python3
"""guard_benchmark.py — the guard on the cases its rules were tuned on, and on cases they never saw.

Two sets:
  dev        evals/datasets/guard-corpus.jsonl: the cases the rules were written and tuned against.
             Each must get its exact verdict; bin/tests/test_guard_corpus.py enforces that.
  held-out   evals/datasets/guard-heldout.jsonl: commands written before a round of changes and
             frozen, with their sha256 in guard-heldout.floor.json. No rule is tuned on a held-out
             case: one that gets fixed moves to dev, and the next honest number needs a new batch.

"Stopped" means blocked or challenged: either way the command does not run on its own. Stage 1
only, what the hooks and plugins run. No model is called. docs/guard-benchmark.md has the results.

Usage: python3 evals/guard_benchmark.py [--out FILE]
Exit 1 when the held-out set changed without its floor, or scores below the floor.
"""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import auto_guard  # noqa: E402

DATASETS = REPO / "evals" / "datasets"
DEV = DATASETS / "guard-corpus.jsonl"
HELDOUT = DATASETS / "guard-heldout.jsonl"
FLOOR = DATASETS / "guard-heldout.floor.json"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def must_stop(case: dict) -> bool:
    return case["expect"] in ("block", "challenge", "stop")


def _blank() -> dict[str, int]:
    return {"harmful": 0, "stopped": 0, "harmless": 0, "ran": 0}


def score(cases: list[dict], key: str = "") -> dict:
    """Stopped of the harmful and ran of the harmless: in total, and by `key` when given."""
    total = _blank()
    by: dict[str, dict[str, int]] = defaultdict(_blank)
    for case in cases:
        stopped = auto_guard.check_block_rules(case["command"]) is not None
        buckets = [total, by[case[key]]] if key else [total]
        for bucket in buckets:
            if must_stop(case):
                bucket["harmful"] += 1
                bucket["stopped"] += stopped
            else:
                bucket["harmless"] += 1
                bucket["ran"] += not stopped
    return {"total": total, **({key: dict(sorted(by.items()))} if key else {})}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> dict:
    dev = load(DEV)
    dev_commands = {case["command"] for case in dev}
    # a held-out command the dev corpus already holds is not unseen: it is left out of the score
    heldout = [case for case in load(HELDOUT) if case["command"] not in dev_commands]
    return {
        "dev": score(dev)["total"],
        "heldout": {
            **score(heldout, "group"),
            "technique": score(heldout, "technique")["technique"],
            "sha256": sha256(HELDOUT),
            "excluded_as_dev": sorted(
                case["id"] for case in load(HELDOUT) if case["command"] in dev_commands
            ),
        },
        "floor": json.loads(FLOOR.read_text(encoding="utf-8")),
    }


def below_floor(result: dict) -> list[str]:
    """What breaks the floor: a held-out set changed without it, or a lower score."""
    floor, held = result["floor"], result["heldout"]
    problems = []
    if held["sha256"] != floor["sha256"]:
        problems.append("the held-out set changed: write a new batch and its floor together")
    if held["excluded_as_dev"] != floor["excluded_as_dev"]:
        problems.append(
            "a dev case now repeats a held-out command: move it, or log it in the floor"
        )
    if held["total"]["stopped"] < floor["stopped"]:
        problems.append(f"held-out stopped {held['total']['stopped']} < floor {floor['stopped']}")
    if held["total"]["ran"] < floor["ran"]:
        problems.append(f"held-out ran {held['total']['ran']} < floor {floor['ran']}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(REPO / "temp" / "guard-benchmark" / "result.json"))
    args = ap.parse_args()
    result = run()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"{'set':12} {'stopped':>14} {'ran':>12}")
    for name, totals in (("dev", result["dev"]), ("held-out", result["heldout"]["total"])):
        print(
            f"{name:12} {totals['stopped']:>6}/{totals['harmful']:<7} "
            f"{totals['ran']:>5}/{totals['harmless']}"
        )
    print("\nheld-out by group (stopped of harmful)")
    for group, totals in result["heldout"]["group"].items():
        if totals["harmful"]:
            print(f"  {group:12} {totals['stopped']:>3}/{totals['harmful']}")
    problems = below_floor(result)
    for problem in problems:
        print(f"FLOOR: {problem}", file=sys.stderr)
    print(f"\nresult: {out}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
