"""Snapshot the NPRA Product Recall tables (AGENTS.md §4.1). Run once; the CSV is committed.

  python scripts/scrape_npra.py              # one polite GET, then parse
  python scripts/scrape_npra.py --offline    # re-parse the newest saved page in data/raw/

Outputs
  data/raw/npra_recall_<YYYY-MM-DD>.html     the page as fetched (gitignored)
  data/sample/regulator/npra_recalls.csv     one row per recall notice
  data/sample/regulator/manifest.json        adds an "npra_recalls" entry

The page holds one table per year (2023 onwards) with columns:
No | Product Name | Registration Number | Active ingredients | Batch Number |
Reason for Recall | Degree and Level of Recall | Registration Holder | Date of recall.
robots.txt (checked 23 Oct 2026) does not disallow this path.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
SAMPLE_DIR = ROOT / "data" / "sample" / "regulator"
OUT_CSV = SAMPLE_DIR / "npra_recalls.csv"

URL = "https://www.npra.gov.my/index.php/en/consumers/safety-information/product-recall.html"
USER_AGENT = "RecallGuard-hackathon/0.1 (one-off research snapshot; github.com/ZerathETZN/GENAIhacks)"
TIMEOUT = httpx.Timeout(60.0, connect=15.0)

HEADER = [
    "no", "product_name", "reg_no", "active_ingredients", "batch_raw",
    "reason", "degree_level_raw", "holder", "date_raw",
]
CSV_COLUMNS = [
    "recall_id", "recall_date", "product_name", "reg_no", "batches", "all_batches",
    "batch_raw", "degree", "voluntary", "level", "degree_level_raw", "reason",
    "holder", "active_ingredients", "date_raw",
]
BATCH_SEP = "|"  # list separator inside the `batches` CSV cell


# ---------- HTML -> list of tables (rows of cell blocks) ----------


class _TableParser(HTMLParser):
    """Collects every <table>. Each cell is a list of text blocks: one per <p>, <li>
    or <br>-separated line, because NPRA puts one batch per line in many cells."""

    _BLOCK = {"p", "li", "br", "div"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[list[str]]]] = []
        self._row: list[list[str]] | None = None
        self._cell: list[str] | None = None
        self._buf: list[str] = []

    def _flush(self) -> None:
        if self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if text:
                self._cell.append(text)
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._buf = [], []
        elif tag in self._BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._flush()
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.tables[-1].append(self._row)
            self._row = None
        elif tag in self._BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._cell is not None:
            self._buf.append(data)


# ---------- field parsing ----------

_ALL_BATCHES = re.compile(r"\ball batch", re.I)
_NUMBERING = re.compile(r"(?:^|\s)\d{1,2}\)\s*")  # "1) ALT3 2) IC005"
_BULLET = re.compile(r"^[•●▪\-*]\s*")
_SPLIT = re.compile(r"\s*(?:,|;|&|\band\b)\s*", re.I)


def parse_batches(blocks: list[str]) -> tuple[list[str], bool]:
    """Return (batches, all_batches). Spaces inside a token are kept on purpose:
    'MA04LDV M1' is one batch, so we never split on whitespace."""
    joined = " ".join(blocks)
    if _ALL_BATCHES.search(joined):
        return [], True
    out: list[str] = []
    for block in blocks:
        block = _BULLET.sub("", block.strip())
        for part in _NUMBERING.split(block):
            for tok in _SPLIT.split(part):
                tok = _BULLET.sub("", tok).strip().strip(".:")
                # Notes such as "100mL Syrup" or "Batch Number:" contain lowercase
                # words; real batch codes on this page never do.
                if not tok or re.search(r"[a-z]{2,}", tok):
                    continue
                for b in _split_space_list(tok):
                    if b not in out:
                        out.append(b)
    return out, False


def _shape(s: str) -> str:
    return re.sub(r"[A-Z]", "A", re.sub(r"\d", "9", s))


def _split_space_list(tok: str) -> list[str]:
    """'BN2404/23 BN2405/23' is two batches, but 'S050 231101' or 'MA04LDV M1' is one.
    Split on spaces only when every piece is long and has the same letter/digit shape."""
    parts = tok.split()
    if len(parts) > 1 and all(len(p) >= 5 for p in parts) and len({_shape(p) for p in parts}) == 1:
        return parts
    return [tok]


_DEGREE = re.compile(r"\bdegree\s+(I{1,3})\b", re.I)
_LEVEL = re.compile(r"\b(?:up to|at)\s+the\s+point\s+of\s+([a-z\- ()]+)", re.I)
# Other wordings used on the page.
_LEVEL_OTHER = [
    (re.compile(r"\bhospital and consumers\b", re.I), "hospital and consumer"),
    (re.compile(r"\ball consumers\b|\bend users?\b", re.I), "consumer"),
    (re.compile(r"\bdistributor level\b", re.I), "distributor"),
]


def parse_degree_level(text: str) -> tuple[str | None, bool, str | None]:
    m = _DEGREE.search(text)
    lvl = _LEVEL.search(text)
    level = re.sub(r"\s+", " ", lvl.group(1)).strip().lower() if lvl else None
    if level is None:
        level = next((name for pat, name in _LEVEL_OTHER if pat.search(text)), None)
    return (m.group(1).upper() if m else None), bool(re.search(r"\bvoluntary\b", text, re.I)), level


# Some rows are written in Malay ("7 Oktober 2025", "13 Mac 2026").
_MALAY_MONTHS = {
    "januari": "January", "februari": "February", "mac": "March", "mei": "May", "jun": "June",
    "julai": "July", "ogos": "August", "oktober": "October", "disember": "December",
}


def parse_date(text: str) -> str | None:
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.strip())
    t = re.sub(r"[A-Za-z]+", lambda m: _MALAY_MONTHS.get(m.group(0).lower(), m.group(0)), t)
    for fmt in ("%d %B %Y", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def is_recall_header(row: list[list[str]]) -> bool:
    text = " ".join(" ".join(c) for c in row).lower()
    return "registration number" in text and "batch number" in text


def parse_page(html: str) -> list[dict]:
    p = _TableParser()
    p.feed(html)
    records: list[dict] = []
    for table in p.tables:
        if not table or not is_recall_header(table[0]):
            continue
        for row in table[1:]:
            if len(row) != len(HEADER):  # e.g. the "Last updated dd/mm/yyyy" footer
                continue
            cells = dict(zip(HEADER, row))
            flat = {k: " ".join(v) for k, v in cells.items()}
            if not flat["reg_no"] and not flat["product_name"]:
                continue
            batches, all_batches = parse_batches(cells["batch_raw"])
            degree, voluntary, level = parse_degree_level(flat["degree_level_raw"])
            # Keep the MAL number only: one row reads "MAL15070027HA (FOR USE IN ANIMALS)".
            reg_raw = re.sub(r"\s+", "", flat["reg_no"]).upper()
            m = re.match(r"MAL\d{8}[A-Z]*?(?=\(|$)", reg_raw)
            reg_no = m.group(0) if m else reg_raw
            key = f"{reg_no}|{flat['batch_raw']}|{flat['date_raw']}"
            records.append({
                "recall_id": "NPRA-" + hashlib.sha1(key.encode()).hexdigest()[:10],
                "recall_date": parse_date(flat["date_raw"]),
                "product_name": flat["product_name"],
                "reg_no": reg_no,
                "batches": BATCH_SEP.join(batches),
                "all_batches": all_batches,
                "batch_raw": " / ".join(cells["batch_raw"]),
                "degree": degree,
                "voluntary": voluntary,
                "level": level,
                "degree_level_raw": flat["degree_level_raw"],
                "reason": flat["reason"],
                "holder": flat["holder"],
                "active_ingredients": flat["active_ingredients"],
                "date_raw": flat["date_raw"],
            })
    records.sort(key=lambda r: (r["recall_date"] or "", r["recall_id"]))
    return records


# ---------- IO ----------


def fetch(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = httpx.get(URL, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    dest.write_bytes(r.content)


def latest_raw() -> Path | None:
    files = sorted(RAW_DIR.glob("npra_recall_[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].html"))
    return files[-1] if files else None


def write_csv(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(records)


def update_manifest(raw: Path, records: list[dict]) -> None:
    path = SAMPLE_DIR / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"datasets": {}}
    manifest.setdefault("datasets", {})["npra_recalls"] = {
        "source_url": URL,
        "fetched_on": raw.stem.rsplit("_", 1)[-1],
        "licence": "NPRA public website content; cited, not redistributed beyond this snapshot. TODO(verify) reuse terms.",
        "rows_in_sample": len(records),
        "rows_without_date": sum(1 for r in records if not r["recall_date"]),
        "rows_all_batches": sum(1 for r in records if r["all_batches"]),
        "file": OUT_CSV.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(OUT_CSV.read_bytes()).hexdigest(),
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="skip download, parse newest page in data/raw/")
    args = ap.parse_args(argv)

    if args.offline:
        raw = latest_raw()
        if raw is None:
            print(f"no saved page in {RAW_DIR}, run without --offline first", file=sys.stderr)
            return 1
    else:
        raw = RAW_DIR / f"npra_recall_{datetime.now(timezone.utc).date().isoformat()}.html"
        print(f"fetching {URL}")
        fetch(raw)

    records = parse_page(raw.read_text(encoding="utf-8"))
    if not records:
        print("no recall rows found: the page layout probably changed", file=sys.stderr)
        return 1
    write_csv(records, OUT_CSV)
    update_manifest(raw, records)

    no_batch = [r["recall_id"] for r in records if not r["batches"] and not r["all_batches"]]
    print(f"  -> {OUT_CSV.relative_to(ROOT).as_posix()}: {len(records)} recalls, "
          f"{sum(len(r['batches'].split(BATCH_SEP)) for r in records if r['batches'])} batches")
    if no_batch:
        print(f"  warning: {len(no_batch)} rows with no parsed batch: {no_batch[:5]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
