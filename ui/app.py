"""RecallGuard Streamlit UI. Owner: C.  Run:  streamlit run ui/app.py   (API_URL defaults to http://localhost:8000)

The UI only calls the API; every number on screen comes from a real run's RunResult and trace.
Design: a pharmacist's recall worksheet. The recall notice slip is the header, each exposed outlet is a
quarantine tag with a severity stripe, and numbers use tabular figures so columns line up.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

import altair as alt
import httpx
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ui import helpers as h
from ui import visuals as v

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
EXAMPLES = Path(__file__).resolve().parent.parent / "input_examples"
RECORDED = Path(__file__).resolve().parent.parent / "output_examples"
RUN_TIMEOUT = httpx.Timeout(900.0, connect=5.0)  # a full run targets < 10 min (AGENTS.md §2.8)
SEVERITY_LABEL = {"high": "High", "medium": "Medium", "low": "Low"}
STATUS_LABEL = {"confirmed": "Confirmed by Critic", "needs_review": "Pharmacist to check"}

st.set_page_config(page_title="RecallGuard", page_icon="💊", layout="wide")

st.html("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&display=swap');
:root {
  --ink: #17232E; --muted: #5B6B77; --rule: #D5DDD8; --paper: #FFFFFF; --wash: #F6F8F7;
  --green: #0B7A55; --high: #B4232A; --medium: #B86E00; --low: #3E7B4F; --review: #5A4A9C;
}
.stApp, .stApp p, .stApp li, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp input, .stApp textarea,
.stApp button p, .stApp [data-testid="stMetricValue"], .stApp [data-testid="stMetricLabel"] p { font-family: 'Public Sans', system-ui, sans-serif; }
.block-container { padding-top: 2.2rem; max-width: 1180px; }
.num { font-variant-numeric: tabular-nums; }

/* brand line */
.rg-brand { display: flex; flex-wrap: wrap; align-items: baseline; gap: .1rem .75rem; margin-bottom: 1.1rem; }
.rg-brand b { font-size: 1.05rem; color: var(--green); letter-spacing: .01em; }
.rg-brand span { color: var(--muted); font-size: .92rem; }

/* recall notice slip: the one bold element */
.rg-notice { background: var(--paper); border: 1px solid var(--rule); border-left: 10px solid var(--sev, var(--green));
  border-radius: 3px; padding: 1.15rem 1.4rem 1.2rem; margin-bottom: 1rem; }
.rg-notice .kind { font-size: .9rem; color: var(--sev, var(--green)); font-weight: 600; margin: 0 0 .25rem; }
.rg-notice h1 { font-size: 2.05rem; line-height: 1.15; font-weight: 700; color: var(--ink); margin: 0 0 .65rem; padding: 0; }
.rg-notice dl { display: flex; flex-wrap: wrap; gap: .4rem 2.2rem; margin: 0; padding: 0; }
.rg-notice dl > div { margin: 0; padding: 0; }
.rg-notice dt { font-size: .8rem; color: var(--muted); margin: 0; }
.rg-notice dd { font-size: 1.02rem; font-weight: 600; color: var(--ink); margin: 0; margin-inline-start: 0; font-variant-numeric: tabular-nums; }

.rg-summary { font-size: 1.02rem; line-height: 1.55; color: var(--ink); max-width: 75ch; margin: .2rem 0 1.1rem; }
.rg-disclaimer { font-size: .88rem; color: var(--muted); border-top: 1px solid var(--rule); padding-top: .6rem; margin-top: .4rem; }

/* tally strip */
.rg-tally { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border-top: 2px solid var(--ink);
  border-bottom: 1px solid var(--rule); margin: .3rem 0 1.4rem; }
.rg-tally div { padding: .7rem .9rem .8rem 0; }
.rg-tally div + div { padding-left: .9rem; border-left: 1px solid var(--rule); }
.rg-tally strong { display: block; font-size: 1.9rem; font-weight: 700; line-height: 1.1; color: var(--ink); font-variant-numeric: tabular-nums; }
.rg-tally span { font-size: .85rem; color: var(--muted); }
.rg-tally .alert strong { color: var(--high); }
.rg-tally .review strong { color: var(--review); }

/* quarantine tags */
.rg-tag { display: grid; grid-template-columns: 2.2rem 1fr auto; gap: .2rem 1rem; background: var(--paper);
  border: 1px solid var(--rule); border-left: 6px solid var(--sev); border-radius: 3px; padding: .85rem 1.1rem; margin-bottom: .6rem; }
.rg-tag .rank { font-size: 1.15rem; font-weight: 700; color: var(--muted); font-variant-numeric: tabular-nums; }
.rg-tag .head { display: flex; flex-wrap: wrap; align-items: baseline; gap: .35rem .9rem; }
.rg-tag .outlet { font-size: 1.15rem; font-weight: 700; color: var(--ink); }
.rg-tag .meta { font-size: .88rem; color: var(--muted); }
.rg-tag .pill { font-size: .8rem; font-weight: 600; padding: .08rem .55rem; border-radius: 999px; border: 1px solid currentColor; }
.rg-tag .sev { color: var(--sev); }
.rg-tag .st-confirmed { color: var(--green); }
.rg-tag .st-needs_review { color: var(--review); }
.rg-tag .qty { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.rg-tag .qty b { font-size: 1.05rem; color: var(--ink); }
.rg-tag .qty span { font-size: .82rem; color: var(--muted); margin-left: .2rem; }
.rg-tag .qty div + div { margin-top: .1rem; }
.rg-tag .action { grid-column: 2 / 4; font-size: .95rem; line-height: 1.5; color: var(--ink); max-width: 85ch; margin-top: .35rem; }
.rg-tag .contact { grid-column: 2 / 4; font-size: .9rem; color: var(--high); font-weight: 500; }
.rg-tag .conf { font-size: .82rem; color: var(--muted); font-variant-numeric: tabular-nums; }

/* pipeline */
.rg-pipe { display: flex; flex-wrap: wrap; align-items: center; gap: .35rem; margin: .2rem 0 1rem; }
.rg-pipe .step { border: 1px solid var(--rule); background: var(--paper); border-radius: 3px; padding: .35rem .7rem; font-size: .9rem; }
.rg-pipe .step b { color: var(--ink); }
.rg-pipe .step span { color: var(--muted); margin-left: .35rem; font-variant-numeric: tabular-nums; }
.rg-pipe .arrow { color: var(--muted); }

/* how each system wrote it */
.sp-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: .7rem; margin: .2rem 0 1.4rem; }
.sp-card { background: var(--paper); border: 1px solid var(--rule); border-top: 4px solid var(--muted); border-radius: 3px; padding: .75rem .9rem .8rem; }
.sp-card.sp-regulator { border-top-color: var(--high); }
.sp-card.sp-inventory { border-top-color: var(--green); }
.sp-card.sp-pos { border-top-color: var(--medium); }
.sp-card.sp-supplier { border-top-color: var(--review); }
.sp-head { display: flex; justify-content: space-between; align-items: baseline; gap: .5rem; }
.sp-head b { font-size: .95rem; color: var(--ink); }
.sp-head span { font-size: .8rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.sp-batches { display: flex; flex-wrap: wrap; gap: .3rem; margin: .55rem 0 .45rem; }
.sp-b { font-family: ui-monospace, Menlo, monospace; font-size: .95rem; font-weight: 700; color: var(--ink);
  background: #EAF0ED; padding: .1rem .45rem; border-radius: 3px; }
.sp-b.odd { background: #FBE9E7; color: var(--high); }
.sp-none { font-size: .85rem; color: var(--muted); }
.sp-card ul { margin: 0; padding-left: 1rem; }
.sp-card li { font-size: .86rem; color: var(--muted); line-height: 1.45; }
.sp-card li.more { list-style: none; margin-left: -1rem; }
h3.rg-h { font-size: 1.15rem; font-weight: 700; color: var(--ink); margin: .4rem 0 .15rem; padding: 0; }
p.rg-sub { font-size: .9rem; color: var(--muted); margin: 0 0 .7rem; max-width: 80ch; }

/* landing */
.rg-landing h1 { font-size: 2.3rem; line-height: 1.15; font-weight: 700; color: var(--ink); max-width: 22ch; margin: .2rem 0 .7rem; padding: 0; }
.rg-landing p { font-size: 1.05rem; line-height: 1.6; color: var(--muted); max-width: 62ch; }
.rg-landing ol { margin: 1.1rem 0 0; padding-left: 1.2rem; max-width: 70ch; }
.rg-landing li { margin-bottom: .45rem; line-height: 1.5; color: var(--ink); }

@media (max-width: 760px) {
  .rg-tally { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rg-tally div + div { border-left: 0; padding-left: 0; }
  .rg-tag { grid-template-columns: 1.6rem 1fr; }
  .rg-tag .qty { grid-column: 2; text-align: left; }
  .rg-notice h1 { font-size: 1.6rem; }
}
</style>
""")


# ---------------- API calls ----------------

def api_get(path: str, timeout: float = 8.0):
    r = httpx.get(f"{API_URL}{path}", timeout=timeout)
    r.raise_for_status()
    return r.json()


def api_run(payload: dict) -> dict:
    r = httpx.post(f"{API_URL}/run", json=payload, timeout=RUN_TIMEOUT)
    if r.status_code == 422:
        return {"status": "error", "run_id": payload.get("run_id"),
                "error": {"type": "ValidationError", "message": r.text[:500], "recoverable": False}}
    r.raise_for_status()
    return r.json()


def load_examples() -> dict[str, dict]:
    out = {}
    for p in sorted(EXAMPLES.glob("example_*.json")):
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def example_label(name: str, req: dict) -> str:
    inp = req.get("input", {})
    if inp.get("mode") == "daily_scan":
        return "Daily scan of all stocked recalls"
    rc = inp.get("recall") or {}
    mode = "sample" if req.get("options", {}).get("sample_mode") else "live"
    return f"{rc.get('product_name', name)} ({mode})"


# ---------------- sidebar: health + input ----------------

with st.sidebar:
    try:
        health = api_get("/health")
        if health.get("sample_mode"):
            st.success("Connected in sample mode: no credentials, no network.", icon="✅")
        else:
            for name, label in (("zetaris", "Zetaris"), ("meterless", "Meterless Nightshift")):
                info = health.get(name, {})
                ok = info.get("status") in {"ok", "reachable"}
                (st.success if ok else st.error)(f"{label}: {info.get('status')}", icon="✅" if ok else "⚠️")
                if info.get("detail"):
                    st.caption(info["detail"])
    except httpx.HTTPError:
        st.error(f"The API is not reachable at {API_URL}. Start it with `python run.py --serve`.")

    examples = load_examples()
    source = st.radio("What to check", ["A saved recall", "A new recall notice", "Today's daily scan",
                                         "A recorded live run", "A past run"])

payload: dict | None = None
past_run_id: str | None = None
recorded: dict | None = None

with st.sidebar:
    if source == "A saved recall":
        if examples:
            name = st.selectbox("Recall", list(examples), format_func=lambda n: example_label(n, examples[n]))
            payload = examples[name]
            with st.expander("Request JSON"):
                st.json(payload)
        else:
            st.info("Add request files to input_examples/ to see them here.")
    elif source == "A new recall notice":
        with st.form("recall"):
            product = st.text_input("Product name")
            reg_no = st.text_input("Registration number (MAL…)")
            batches = st.text_input("Affected batches, comma separated")
            notice_date = st.date_input("Recall date", value=date.today())
            degree = st.text_input("Recall degree, if stated (I, II or III)")
            submitted = st.form_submit_button("Use this recall")
        if submitted or product:
            payload = {
                "run_id": f"ui-{uuid.uuid4().hex[:8]}",
                "input": {"mode": "recall_alert", "recall": {
                    "product_name": product.strip(), "reg_no": reg_no.strip(),
                    "batches": [b.strip() for b in batches.split(",") if b.strip()],
                    "date": notice_date.isoformat(), "degree_level": degree.strip() or None}},
                "options": {"sample_mode": False, "max_critic_rounds": 2},
            }
    elif source == "Today's daily scan":
        payload = {"run_id": f"scan-{uuid.uuid4().hex[:8]}", "input": {"mode": "daily_scan"},
                   "options": {"sample_mode": False, "max_critic_rounds": 2}}
    elif source == "A recorded live run":
        runs = h.recorded_runs(RECORDED)
        if runs:
            pick = st.selectbox("Recorded run", range(len(runs)), format_func=lambda i: runs[i]["label"])
            recorded = runs[pick]
            st.caption("Saved from a real live run (Zetaris + Nemotron through Nightshift) in output_examples/. "
                       "Shown as recorded, not re-run.")
        else:
            st.info("No recorded runs in output_examples/.")
    else:
        past_run_id = st.text_input("Run ID", placeholder="example-2-1a2b")

    if payload is not None:
        payload = json.loads(json.dumps(payload))
        payload.setdefault("options", {})
        payload["options"]["sample_mode"] = st.toggle(
            "Sample mode", value=bool(payload["options"].get("sample_mode")),
            help="Runs the same agents on the committed sample data, with no credentials and no network.")
        if source == "A saved recall":
            payload["run_id"] = f"{payload.get('run_id', 'run')}-{uuid.uuid4().hex[:4]}"
        go = st.button("Check outlets", type="primary", use_container_width=True)
    else:
        go = st.button("Open run", use_container_width=True) if source in ("A past run", "A recorded live run") else False

# ---------------- run ----------------

if go and payload is not None:
    with st.spinner("Planner, Retriever, Reconciler, Critic and Reporter are working…"):
        try:
            st.session_state["result"] = api_run(payload)
            st.session_state["request"] = payload
            st.session_state["trace_file"] = None
            st.session_state["recorded_from"] = None
        except httpx.HTTPError as exc:
            st.session_state["result"] = {"status": "error", "run_id": payload["run_id"],
                                          "error": {"type": type(exc).__name__, "message": str(exc), "recoverable": True}}
    if st.session_state["result"].get("status") == "success":
        st.toast("Check finished", icon="✅")
elif go and recorded:
    st.session_state["result"] = recorded["result"]
    st.session_state["request"] = None
    st.session_state["trace_file"] = str(recorded["trace"]) if recorded["trace"] else None
    st.session_state["recorded_from"] = recorded["folder"]
elif go and past_run_id:
    try:
        st.session_state["result"] = api_get(f"/runs/{past_run_id.strip()}")
        st.session_state["request"] = None
        st.session_state["trace_file"] = None
        st.session_state["recorded_from"] = None
    except httpx.HTTPError as exc:
        st.error(f"Could not open run '{past_run_id}': {exc}")

result = st.session_state.get("result")
request = st.session_state.get("request") or {}

st.html('<div class="rg-brand"><b>💊 RecallGuard</b><span>Recall exposure review for pharmacy chains</span></div>')

# ---------------- landing ----------------

if not result:
    st.html("""
<div class="rg-landing">
  <h1>Which outlets still hold, or already sold, a recalled medicine?</h1>
  <p>The answer is spread across systems that share no IDs. One recalled batch can be written four different ways.
  RecallGuard's agents reconcile them against Malaysia's NPRA recall notices and trace every finding to a source record.</p>
</div>""")
    st.html(f'<div style="margin:1.2rem 0 .6rem">{v.as_img(v.hero_svg(), "The same recalled batch written four ways by four systems, reconciled into one action plan")}</div>')
    st.html("""
<div class="rg-landing"><ol>
    <li>Pick a recall in the sidebar, or enter a new recall notice.</li>
    <li>Press <b>Check outlets</b>. Five agents find, match and double-check the records.</li>
    <li>Work through the action plan, outlet by outlet, and answer anything marked for a pharmacist.</li>
</ol></div>""")
    st.stop()

if result.get("status") != "success":
    err = result.get("error") or {}
    st.error(f"**The check did not finish.** {err.get('type', 'Error')}: {err.get('message', 'no details')}")
    st.caption("Check the connection status in the sidebar and run it again." if err.get("recoverable")
               else "This needs a fix before it can run.")
    st.stop()

out = result.get("output") or {}
exposures = out.get("exposures", [])
ranked = h.rank_exposures(exposures)
t = h.tally(exposures)
scan = (request.get("input") or {}).get("mode") == "daily_scan" or any(e.get("recall_id") for e in exposures)
top_sev = ranked[0]["severity"] if ranked else None
sev_var = f"var(--{top_sev})" if top_sev else "var(--green)"

# ---------------- recall notice slip ----------------

if st.session_state.get("recorded_from"):
    st.info(f"Recorded live run from output_examples/{st.session_state['recorded_from']}/, shown as saved.", icon="📼")

if scan:
    recalls = sorted({e.get("recall_id") for e in exposures if e.get("recall_id")})
    title, kind = "Daily scan of the NPRA recall snapshot", "Scan across every recall the chain stocks"
    facts = [("Recalls with exposure", str(len(recalls))), ("Run", result.get("run_id", ""))]
else:
    rc = (request.get("input") or {}).get("recall") or {}
    first = ranked[0] if ranked else {}
    title = rc.get("product_name") or first.get("product_name") or "Recall"
    degree = rc.get("degree_level")
    kind = f"NPRA recall, degree {escape(str(degree))}" if degree else "NPRA recall notice"
    facts = [("Registration", rc.get("reg_no") or first.get("reg_no") or "-"),
             ("Batches", ", ".join(rc.get("batches") or []) or (first.get("batch") or "all")),
             ("Recall date", rc.get("date") or "-"),
             ("Rule applied", (first.get("rule_ref") or "-").split("#")[-1])]
facts.append(("Data and model", f"{result.get('adapter') or '-'}, {', '.join(result.get('providers_used') or []) or '-'}"))
dl = "".join(f"<div><dt>{escape(k)}</dt><dd>{escape(str(v))}</dd></div>" for k, v in facts)
st.html(f'<div class="rg-notice" style="--sev:{sev_var}"><p class="kind">{kind}</p>'
        f'<h1>{escape(title)}</h1><dl>{dl}</dl></div>')

if out.get("summary"):
    st.markdown(f'<p class="rg-summary">{escape(out["summary"]).replace("**", "")}</p>', unsafe_allow_html=True)

n_review, review_words = h.review_breakdown(out.get("unresolved_conflicts", []))
if not n_review:
    n_review, review_words = t["needs_review"], "for a pharmacist to check"
st.html(f"""
<div class="rg-tally">
  <div><strong>{t['outlets']}</strong><span>outlets affected</span></div>
  <div><strong>{t['on_hand']}</strong><span>units still in stock</span></div>
  <div class="{'alert' if t['sold'] else ''}"><strong>{t['sold']}</strong><span>units sold since the recall</span></div>
  <div class="{'alert' if t['customers'] else ''}"><strong>{t['customers']}</strong><span>customers to contact</span></div>
  <div class="{'review' if n_review else ''}"><strong>{n_review}</strong><span>{escape(review_words)}</span></div>
</div>""")

sp = v.spellings(exposures)
if sp:
    batches_req = list(((request.get("input") or {}).get("recall") or {}).get("batches") or [])
    if not batches_req:
        batches_req = sorted({e.get("batch") for e in exposures if e.get("batch")})
    st.html('<h3 class="rg-h">How each system recorded it</h3><p class="rg-sub">Spellings found in this run\'s evidence. '
            'Red batch numbers differ from the recall notice but were matched to it.</p>' + v.spellings_html(sp, batches_req))


review_items = h.review_items(out.get("unresolved_conflicts", []))
tab_plan, tab_detail, tab_review, tab_trace, tab_raw = st.tabs(
    ["Action plan", "Evidence", f"Pharmacist review ({len(review_items)})", "How the agents worked", "Raw result"])

# ---------------- action plan ----------------

with tab_plan:
    if not ranked:
        st.success("No outlet holds or sold the affected batches.")
    if ranked and not scan:
        chart_rows = []
        for e in ranked:
            chart_rows += [{"Outlet": e["outlet_id"], "What": "In stock", "Units": int(e.get("on_hand_qty") or 0)},
                           {"Outlet": e["outlet_id"], "What": "Sold since recall", "Units": int(e.get("sold_after_date_qty") or 0)}]
        order = [e["outlet_id"] for e in ranked]
        chart = (alt.Chart(pd.DataFrame(chart_rows)).mark_bar(cornerRadiusEnd=2)
                 .encode(y=alt.Y("Outlet:N", sort=order, title=None),
                         yOffset=alt.YOffset("What:N", sort=["In stock", "Sold since recall"]),
                         x=alt.X("Units:Q", title="Units", axis=alt.Axis(tickMinStep=1, grid=True)),
                         color=alt.Color("What:N", scale=alt.Scale(domain=["In stock", "Sold since recall"],
                                                                   range=["#7FA693", "#B4232A"]),
                                         legend=alt.Legend(orient="top", title=None)),
                         tooltip=["Outlet", "What", "Units"])
                 .properties(height=alt.Step(17))
                 .configure_axis(labelFont="Public Sans", titleFont="Public Sans", labelFontSize=12, labelColor="#17232E")
                 .configure_legend(labelFont="Public Sans", labelFontSize=12)
                 .configure_view(strokeWidth=0))
        st.html('<h3 class="rg-h">Stock and sales by outlet</h3><p class="rg-sub">Units sold since the recall date mean '
                'customers may need contacting.</p>')
        st.altair_chart(chart, use_container_width=True)
    view = st.segmented_control("View", ["Tags", "Table"], default="Tags", label_visibility="collapsed") if ranked else None
    if view == "Table":
        st.dataframe(pd.DataFrame(h.action_rows(exposures)), hide_index=True, use_container_width=True,
                     column_config={"Confidence": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.2f"),
                                    "Action": st.column_config.TextColumn(width="large")})
    elif ranked:
        tags = []
        for i, e in enumerate(ranked, start=1):
            action, contact = h.split_action(e.get("recommended_action", ""))
            sev = e.get("severity", "low")
            status = e.get("status", "confirmed")
            recall = f'<span class="meta">{escape(e["recall_id"])}</span>' if e.get("recall_id") else ""
            tags.append(f"""
<div class="rg-tag" style="--sev:var(--{escape(sev)})">
  <div class="rank">{i}</div>
  <div class="head">
    <span class="outlet">{escape(str(e.get('outlet_id')))}</span>
    <span class="pill sev">{SEVERITY_LABEL.get(sev, sev)} severity</span>
    <span class="pill st-{escape(status)}">{STATUS_LABEL.get(status, status)}</span>
    {recall}
    <span class="meta">{escape(str(e.get('product_name')))}, batch {escape(str(e.get('batch')))}</span>
  </div>
  <div class="qty">
    <div><b>{int(e.get('on_hand_qty') or 0)}</b><span>in stock</span></div>
    <div><b>{int(e.get('sold_after_date_qty') or 0)}</b><span>sold since recall</span></div>
    <div class="conf">confidence {float(e.get('confidence') or 0):.2f}</div>
  </div>
  <div class="action">{escape(action)}</div>
  {f'<div class="contact">{escape(contact)}</div>' if contact else ''}
</div>""")
        st.html("".join(tags))

    if out.get("unresolved_conflicts"):
        st.markdown(f"#### Not yet assigned to an outlet action ({len(out['unresolved_conflicts'])})")
        st.caption("Records the agents could not settle. They are listed so nothing is dropped silently.")
        rows = [{"Recall": c.get("recall_id") or "", "Outlet": c.get("outlet_id") or "", "Batch": c.get("batch") or "",
                 "Why": "; ".join(dict.fromkeys(c.get("reasons") or ([c["error"]] if c.get("error") else []))),
                 "Questions": len(c.get("doubts") or [])} for c in out["unresolved_conflicts"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     column_config={"Why": st.column_config.TextColumn(width="large")})

# ---------------- evidence ----------------

with tab_detail:
    for rank, e in enumerate(ranked, start=1):
        title = (f"{rank}. {e.get('outlet_id')}: {e.get('product_name')}, batch {e.get('batch')} "
                 f"({SEVERITY_LABEL.get(e.get('severity'), '')} severity, {STATUS_LABEL.get(e.get('status'), '')})")
        with st.expander(title, expanded=rank == 1):
            cc = e.get("critic_check")
            if cc:
                verdict = "matched" if cc.get("passed") else "did not match"
                st.markdown(f"**The Critic re-checked this on the raw tables and it {verdict}.** "
                            f"Expected `{cc.get('expected')}`, found `{cc.get('observed')}`.")
                st.code(cc.get("query", ""), language="sql", wrap_lines=True)
            if e.get("evidence"):
                st.markdown("**Source records**")
                st.dataframe(pd.DataFrame(e["evidence"]).rename(columns={
                    "source": "System", "record_id": "Record", "field": "Field", "value": "Value as written"}),
                    hide_index=True, use_container_width=True)
            st.caption(f"Rule {e.get('rule_ref')} · confidence {float(e.get('confidence') or 0):.2f}")

# ---------------- pharmacist review ----------------

with tab_review:
    st.markdown("These are spellings the agents could not settle on their own. Decide each one, download the lines, "
                "add them to `data/feedback/decisions.jsonl`, and run the check again. Every **same** answer is "
                "remembered (H-MEM), so the next run asks fewer questions. Nothing here changes the current result.")
    if not review_items:
        st.success("Nothing to decide in this run.")
    else:
        who = st.text_input("Your name", key="decided_by", help="Every verdict records the person who made it.")
        lines = []
        for i, d in enumerate(review_items):
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 2, 3])
                c1.markdown(f"Is **{d['field'].replace('_', ' ')}** `{d['alias']}` the same as `{d['canonical']}`?  \n"
                            f"{d.get('outlet_id') or ''}, record {d.get('record_ref') or '-'}")
                answer = c2.radio("Answer", ["Not sure", "Same", "Different"], key=f"v{i}", horizontal=True,
                             label_visibility="collapsed")
                note = c3.text_input("Note", key=f"n{i}", label_visibility="collapsed", placeholder="Reason (optional)")
            if answer != "Not sure":
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                lines.append(h.verdict_line(d, answer.lower(), who.strip(), now, result.get("run_id", ""), note.strip()))
        if lines and not who.strip():
            st.warning("Add your name first. Every verdict must name the person who made it.")
        elif lines:
            try:
                from app.schemas import HumanVerdict
                for ln in lines:
                    HumanVerdict.model_validate(ln)
                body = "".join(json.dumps(ln, ensure_ascii=False) + "\n" for ln in lines)
                st.code(body, language="json", wrap_lines=True)
                st.download_button(f"Download {len(lines)} answer{'s' if len(lines) != 1 else ''}", body,
                                   file_name="decisions-new.jsonl", mime="application/x-ndjson", type="primary")
            except (ImportError, ValueError) as exc:
                st.error(f"An answer does not match the decisions.jsonl format: {exc}")

# ---------------- agent trace ----------------

with tab_trace:
    if st.session_state.get("trace_file"):
        events = h.read_trace_file(Path(st.session_state["trace_file"]))
    else:
        try:
            events = api_get(f"/runs/{result['run_id']}/trace")
        except httpx.HTTPError:
            events = []
    if not events:
        st.info("This run has no trace events.")
    else:
        s = h.trace_summary(events)
        st.html(f'<div style="margin:.4rem 0 .6rem">{v.as_img(v.pipeline_svg(events), "Agent pipeline with actions and sponsor calls per agent")}</div>')
        k = st.columns(4)
        k[0].metric("Handoffs between agents", s["handoffs"])
        k[1].metric("Critic re-checks", s["critic_checks"])
        k[2].metric("Critic rejections", s["critic_revisions"])
        k[3].metric("Sent to a pharmacist", s["needs_review"])
        calls = ", ".join(f"{name} {n}×" for name, n in s["sponsor_calls"].items()) or "none"
        st.markdown(f"**Sponsor calls:** {calls}  \n**Model that answered:** {', '.join(s['served_by']) or 'none (deterministic rules)'}"
                    + (f"  \n**Fallbacks:** {', '.join(s['fallbacks'])}" if s["fallbacks"] else ""))
        st.dataframe(pd.DataFrame(h.trace_rows(events)), hide_index=True, use_container_width=True,
                     height=min(520, 40 + 36 * len(events)),
                     column_config={"Output": st.column_config.TextColumn(width="large"),
                                    "Served by": st.column_config.TextColumn(width="medium")})
        st.caption(f"Written by this run to {result.get('log_file')}.")

with tab_raw:
    st.download_button("Download result JSON", json.dumps(result, indent=2),
                       file_name=f"result-{result.get('run_id')}.json", mime="application/json")
    st.json(result, expanded=1)

st.html(f'<p class="rg-disclaimer"><b>{escape(out.get("disclaimer", "For pharmacist review. Not a compliance verdict."))}</b> '
        f'{escape(h.DATA_CAVEAT)}</p>')
