"""Offline tests for scripts/scrape_npra.py, using cell shapes seen on the real page."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "scrape_npra", Path(__file__).resolve().parents[1] / "scripts" / "scrape_npra.py"
)
sn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sn)


@pytest.mark.parametrize(
    "blocks, expected",
    [
        (["19574, 19616"], ["19574", "19616"]),
        (["2311021 and 2311022"], ["2311021", "2311022"]),
        (["F10753P2 & G19850P2"], ["F10753P2", "G19850P2"]),
        (["1) ALT3", "2) IC005"], ["ALT3", "IC005"]),
        (["1) 19A01S 2) 1ZA01S 3) 225A01S"], ["19A01S", "1ZA01S", "225A01S"]),
        (["19121372,", "20040326,", "21010027"], ["19121372", "20040326", "21010027"]),
        (["• 100mL Syrup", "Batch Number:", "• S050 231101", "• S050 231201"], ["S050 231101", "S050 231201"]),
        (["MA04LDV M1, MA04LDV M2"], ["MA04LDV M1", "MA04LDV M2"]),  # space is part of the batch
        (["2401-24A07"], ["2401-24A07"]),  # hyphen is part of the batch
        (["BN2404/23 BN2405/23 BN2401/24"], ["BN2404/23", "BN2405/23", "BN2401/24"]),  # same-shape list
        (["S050 231101"], ["S050 231101"]),  # different shapes: one batch
        (["TAAAZA 112-23"], ["TAAAZA 112-23"]),
        (["1770600A (182/AO), 1770600A (182/AO)"], ["1770600A (182/AO)"]),  # de-duplicated
    ],
)
def test_parse_batches(blocks, expected):
    assert sn.parse_batches(blocks) == (expected, False)


@pytest.mark.parametrize("text", ["All batches", "All batches manufactured from February 2024 until December 2025"])
def test_all_batches(text):
    assert sn.parse_batches([text]) == ([], True)


def test_degree_and_level():
    assert sn.parse_degree_level("Degree II recall up to the point of sales") == ("II", False, "sales")
    assert sn.parse_degree_level("Voluntary recall at the point of sub-distributor (wholesaler)") == (
        None, True, "sub-distributor (wholesaler)",
    )
    assert sn.parse_degree_level("Degree II recall up to all consumers level (end users)") == ("II", False, "consumer")
    assert sn.parse_degree_level("Voluntary recall up to the level of hospital and consumers")[2] == "hospital and consumer"
    assert sn.parse_degree_level("Voluntary recall at the distributor level") == (None, True, "distributor")


def test_dates():
    assert sn.parse_date("30 January 2026") == "2026-01-30"
    assert sn.parse_date("01 February 2024") == "2024-02-01"
    assert sn.parse_date("7 Oktober 2025") == "2025-10-07"
    assert sn.parse_date("13 Mac 2026") == "2026-03-13"
    assert sn.parse_date("soon") is None


PAGE = """
<table><tr><th>Degree</th><th>Definition</th></tr><tr><td>I</td><td>x</td></tr></table>
<table>
<tr><td>No</td><td>Product Name</td><td>Registration Number</td><td>Active ingredients</td>
<td>Batch Number</td><td>Reason for Recall</td><td>Degree and Level of Recall</td>
<td>Registration Holder</td><td>Date of recall</td></tr>
<tr><td>1</td><td>Vamlo Tablets 10mg</td><td>MAL07010993AZ</td><td>Amlodipine</td>
<td><p>24030132</p></td><td>OOT &ldquo;Impurity D&rdquo;</td><td>Voluntary recall up to the point of sales</td>
<td>RANBAXY</td><td>13 February 2026</td></tr>
<tr><td colspan="9">Last updated 07/08/2026</td></tr>
</table>"""


def test_parse_page_skips_other_tables_and_footer():
    rows = sn.parse_page(PAGE)
    assert len(rows) == 1
    r = rows[0]
    assert (r["reg_no"], r["batches"], r["recall_date"], r["level"]) == ("MAL07010993AZ", "24030132", "2026-02-13", "sales")
    assert r["reason"] == "OOT “Impurity D”"
    assert r["recall_id"] == sn.parse_page(PAGE)[0]["recall_id"]  # stable id
