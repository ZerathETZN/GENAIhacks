"""Every hand-written line in data/feedback/decisions.jsonl must match the §7.5 format."""

import json
from datetime import datetime
from pathlib import Path

from app.schemas import HumanVerdict

FILE = Path(__file__).resolve().parents[1] / "data" / "feedback" / "decisions.jsonl"


def test_decisions_file_is_valid():
    keys = set()
    for n, line in enumerate(FILE.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        v = HumanVerdict.model_validate(json.loads(line))
        datetime.fromisoformat(v.decided_at.replace("Z", "+00:00"))
        key = (v.field, v.alias)
        assert key not in keys, f"line {n}: duplicate verdict for {key}; edit the old line instead"
        keys.add(key)
