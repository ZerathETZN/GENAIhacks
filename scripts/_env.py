"""Minimal .env reader shared by the scripts (no extra dependency). Real env vars win."""

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m:
            os.environ.setdefault(m.group(1), m.group(2))
