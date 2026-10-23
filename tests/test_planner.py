import json

import pytest

from app.adapters.factory import get_adapter
from app.agents.planner import PlannerAgent, PlannerError


def test_plans_on_the_real_duckdb_catalogue_and_traces_the_statements():
    events = []
    plan = PlannerAgent(get_adapter(sample_mode=True), "r1", events.append).plan()
    assert plan["view"] == "recallguard.product_exposure_v"
    assert events[0].action == "catalogue_discovery" and "information_schema" in events[0].input_summary and events[0].status == "ok"


def test_missing_table_stops_the_run_with_a_clear_error():
    a = get_adapter(sample_mode=True)
    cat = a.catalogue()
    cat["tables"] = [t for t in cat["tables"] if t["table"] != "pos_pg.sales"]
    a.catalogue = lambda: cat
    with pytest.raises(PlannerError, match="pos_pg.sales"):
        PlannerAgent(a, "r1").plan()
