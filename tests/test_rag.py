from app.rag import GuidelineIndex

DOC = """1. Introduction
This guideline describes product recall procedures in Malaysia.

4.1 Recall classification
Class I recall: products that may cause serious adverse health consequences or death.
Class II recall: products that may cause temporary adverse health consequences.

5.2 Customer level recall
Pharmacies must contact patients who received the affected batch and quarantine remaining stock.
"""


def test_search_finds_section(tmp_path):
    (tmp_path / "guideline.txt").write_text(DOC)
    idx = GuidelineIndex.from_dir(tmp_path)
    hits = idx.search("contact patients affected batch quarantine")
    assert hits and hits[0].section == "5.2" and hits[0].cite() == "guideline.txt §5.2"


def test_empty_corpus_and_query_are_safe(tmp_path):
    assert GuidelineIndex.from_dir(tmp_path).search("recall") == []
    (tmp_path / "g.txt").write_text(DOC)
    assert GuidelineIndex.from_dir(tmp_path).search("the and of") == []
