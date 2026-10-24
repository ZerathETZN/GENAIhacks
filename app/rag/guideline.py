"""Optional RAG over the NPRA recall guideline (AGENTS.md §5.4). Owner: C. First item on the cut list.

Offline BM25 over text in data/docs/ (convert the guideline PDF once: `pdftotext -layout guideline.pdf
data/docs/npra_recall_guideline.txt` and commit the .txt with its source URL). No network and no embeddings, so it
works the same in SAMPLE_MODE. The Reporter uses `search()` to quote the guideline section behind an action; the
model call, if any, still goes through app.llm.generate.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

TOKEN = re.compile(r"[a-z0-9]+")
HEADING = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+([A-Z][^\n]{2,80})$")
STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "is", "are", "be", "by", "with", "as", "at",
        "that", "this", "it", "from", "shall", "should", "must", "may", "dan", "yang", "di", "ke"}


@dataclass(frozen=True)
class Passage:
    source: str
    section: str
    text: str
    score: float = 0.0

    def cite(self) -> str:
        return f"{self.source} §{self.section}" if self.section else self.source


def _tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP and len(t) > 1]


def _chunks(text: str, source: str, max_words: int = 180) -> list[Passage]:
    """Split on numbered headings ("4.2 Recall classification"); long sections split by paragraphs."""
    out, section, buf = [], "", []

    def flush():
        body = " ".join(" ".join(buf).split())
        words = body.split()
        for i in range(0, len(words), max_words):
            piece = " ".join(words[i:i + max_words])
            if piece:
                out.append(Passage(source, section, piece))

    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            flush()
            section, buf = m.group(1), [line.strip()]
        else:
            buf.append(line)
    flush()
    return out


class GuidelineIndex:
    def __init__(self, passages: list[Passage], k1: float = 1.5, b: float = 0.75) -> None:
        self.passages = passages
        self.k1, self.b = k1, b
        self._tf = [Counter(_tokens(p.text)) for p in passages]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / len(self._len)) if self._len else 0.0
        df = Counter(t for tf in self._tf for t in tf)
        n = len(passages)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    @classmethod
    def from_dir(cls, path: str | Path = "data/docs") -> GuidelineIndex:
        passages: list[Passage] = []
        for f in sorted(Path(path).glob("*")):
            if f.suffix.lower() in {".txt", ".md"}:
                passages += _chunks(f.read_text(encoding="utf-8", errors="ignore"), f.name)
        return cls(passages)

    def __len__(self) -> int:
        return len(self.passages)

    def search(self, query: str, k: int = 3) -> list[Passage]:
        q = _tokens(query)
        if not q or not self.passages:
            return []
        scored = []
        for i, tf in enumerate(self._tf):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self._idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self._len[i] / self._avg))
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        return [Passage(**{**self.passages[i].__dict__, "score": round(s, 3)}) for s, i in scored[:k]]
