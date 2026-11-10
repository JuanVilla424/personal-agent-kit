#!/usr/bin/env python3
"""Real token counter for the agent footprint (MODELS.md / bin/measure-footprint.sh).

Uses tiktoken ``cl100k_base`` — a genuine BPE tokenizer, NOT the crude ``bytes/4`` estimate. It is a
close PROXY for Claude (~±10%); the exact Claude count is only via the Anthropic ``count_tokens`` API
(which needs an API key, unavailable here).

Usage: ``count_tokens.py <file|dir|md|md1> <path>``
  file  one file                 dir   every file under path (recursive)
  md    ``*.md`` recursive        md1   ``*.md`` top-level only
Prints the token total (0 on error / missing path).
"""

import glob
import os
import sys

import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")


def _toks(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return len(_ENC.encode(fh.read(), disallowed_special=()))
    except (OSError, ValueError):
        return 0


def _paths(mode: str, path: str) -> list:
    if mode == "file":
        return [path]
    if mode == "dir":
        return [os.path.join(r, f) for r, _, fs in os.walk(path) for f in fs]
    if mode == "md":
        return glob.glob(os.path.join(path, "**", "*.md"), recursive=True)
    if mode == "md1":
        return glob.glob(os.path.join(path, "*.md"))
    raise SystemExit(f"unknown mode: {mode}")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: count_tokens.py <file|dir|md|md1> <path>")
    print(sum(_toks(p) for p in _paths(sys.argv[1], sys.argv[2])))


if __name__ == "__main__":
    main()
