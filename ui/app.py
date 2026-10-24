"""RecallGuard Streamlit UI. Owner: C.  Run:  streamlit run ui/app.py   (API_URL defaults to http://localhost:8000)

The UI only calls the API; every number on screen comes from a real run's RunResult and trace.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ui import helpers as h

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
EXAMPLES = Path(__file__).resolve().parent.parent / "input_examples"
RUN_TIMEOUT = httpx.Timeout(900.0, connect=5.0)  # a full run targets < 10 min (AGENTS.md §2.8)

st.set_page_config(page_title="RecallGuard", page_icon="💊", layout="wide")


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


# ---------------- sidebar: health + input ----------------

with st.sidebar:
    st.markdown("## 💊 RecallGuard")
    st.caption("Recall exposure review for pharmacy chains")
    try:
        health = api_get("/health")
        icon = {"ok": "🟢", "degraded": "🟠"}.get(health.get("status"), "🔴")
        st.markdown(f"**API** {icon} {health.get('status')}" + (" · sample mode" if health.get("sample_mode") else ""))
        if not health.get("sample_mode"):
            for name, label in (("zetaris", "Zetaris"), ("meterless", "Meterless Nightshift")):
                info = health.get(name, {})
                ok = info.get("status") in {"ok", "reachable"}
                st.markdown(f"{'🟢' if ok else '🔴'} {label}: {info.get('status')}")
                if info.get("detail"):
                    st.caption(info["detail"])
    except httpx.HTTPError:
        st.error(f"API not reachable at {API_URL}. Start it with `python run.py --serve`.")

    st.divider()
    examples = load_examples()
    source = st.radio("Input", ["Example", "New recall alert", "Daily scan", "Open past run"], index=0)

payload: dict | None = None
past_run_id: str | None = None

with st.sidebar:
    if source == "Example":
        if examples:
            name = st.selectbox("Example input", list(examples))
            payload = examples[name]
            with st.expander("Request JSON"):
                st.json(payload)
        else:
            st.info("No files in input_examples/ yet.")
    elif source == "New recall alert":
        with st.form("recall"):
            product = st.text_input("Product name")
            reg_no = st.text_input("Registration no. (MAL…)")
            batches = st.text_input("Affected batches (comma separated)")
            notice_date = st.date_input("Recall / cancellation date", value=date.today())
            degree = st.text_input("Recall degree / level (optional)")
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
    elif source == "Daily scan":
        payload = {"run_id": f"scan-{uuid.uuid4().hex[:8]}", "input": {"mode": "daily_scan"},
                   "options": {"sample_mode": False, "max_critic_rounds": 2}}
    else:
        past_run_id = st.text_input("run_id", placeholder="demo-001")

    if payload is not None:
        payload = json.loads(json.dumps(payload))
        payload.setdefault("options", {})
        payload["options"]["sample_mode"] = st.toggle(
            "Sample mode (no credentials, no network)", value=bool(payload["options"].get("sample_mode")))
        if source == "Example":
            payload["run_id"] = f"{payload.get('run_id', 'run')}-{uuid.uuid4().hex[:4]}"
        go = st.button("▶ Run agents", type="primary", use_container_width=True)
    else:
        go = st.button("Load run", use_container_width=True) if source == "Open past run" else False

# ---------------- run ----------------

if go and payload is not None:
    with st.status("Agents working: Planner → Retriever → Reconciler → Critic → Reporter…", expanded=False) as s:
        try:
            st.session_state["result"] = api_run(payload)
            s.update(label="Run finished", state="complete")
        except httpx.HTTPError as exc:
            st.session_state["result"] = {"status": "error", "run_id": payload["run_id"],
                                          "error": {"type": type(exc).__name__, "message": str(exc), "recoverable": True}}
            s.update(label="Run failed", state="error")
elif go and past_run_id:
    try:
        st.session_state["result"] = api_get(f"/runs/{past_run_id.strip()}")
    except httpx.HTTPError as exc:
        st.error(f"Could not load run '{past_run_id}': {exc}")

result = st.session_state.get("result")

# ---------------- results ----------------

st.title("RecallGuard")
st.caption("Finds every outlet that still holds, or has sold, a recalled or deregistered product, "
           "across inventory, POS, supplier and regulator systems that share no IDs.")

if not result:
    st.info("Pick an input in the sidebar and press **Run agents**.")
    st.stop()

if result.get("status") != "success":
    err = result.get("error") or {}
    st.error(f"**{err.get('type', 'Error')}**: {err.get('message', 'unknown error')}")
    st.caption("Recoverable: retry or check /health." if err.get("recoverable") else "Not recoverable without a fix.")
    st.stop()

out = result.get("output") or {}
exposures = out.get("exposures", [])
c = h.counts(exposures)

st.warning(f"**{out.get('disclaimer', 'For pharmacist review. Not a compliance verdict.')}**")
if out.get("summary"):
    st.markdown(out["summary"])

m = st.columns(6)
m[0].metric("Exposures", c["exposures"])
m[1].metric("High severity", c["high"])
m[2].metric("Confirmed", c["confirmed"])
m[3].metric("Needs review", c["needs_review"])
m[4].metric("Outlets", c["outlets"])
m[5].metric("Run time", f"{result.get('execution_time_seconds', 0):.1f}s")
st.caption(f"run_id `{result.get('run_id')}` · data via **{result.get('adapter') or '-'}** · "
           f"models via **{', '.join(result.get('providers_used') or []) or '-'}**")

tab_actions, tab_detail, tab_review, tab_trace, tab_raw = st.tabs(
    ["Action list", "Evidence", "Pharmacist review", "Agent trace", "Raw JSON"])

with tab_actions:
    if exposures:
        st.dataframe(
            pd.DataFrame(h.action_rows(exposures)), hide_index=True, use_container_width=True,
            column_config={"Confidence": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.2f")},
        )
    else:
        st.success("No exposed outlets found for this input.")
    if out.get("unresolved_conflicts"):
        st.subheader(f"Needs a pharmacist ({len(out['unresolved_conflicts'])})")
        rows = [{"Recall": c.get("recall_id") or "", "Outlet": c.get("outlet_id") or "", "Batch": c.get("batch") or "",
                 "Why": "; ".join(dict.fromkeys(c.get("reasons") or ([c["error"]] if c.get("error") else []))),
                 "Open questions": len(c.get("doubts") or [])} for c in out["unresolved_conflicts"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

with tab_detail:
    for rank, e in enumerate(h.rank_exposures(exposures), start=1):
        title = (f"#{rank} {h.SEVERITY_BADGE.get(e.get('severity'), '')} · {e.get('outlet_id')} · "
                 f"{e.get('product_name')} · batch {e.get('batch')} · {h.STATUS_BADGE.get(e.get('status'), '')}")
        with st.expander(title, expanded=rank == 1):
            st.markdown(f"**Action:** {e.get('recommended_action')}  \n`{e.get('rule_ref')}` · "
                        f"confidence {e.get('confidence', 0):.2f}")
            line = h.contact_line(e)
            if line:
                st.info(line)
            cc = e.get("critic_check")
            if cc:
                st.markdown(f"**Critic verification query** {'✅ passed' if cc.get('passed') else '❌ mismatch'}: "
                            f"expected `{cc.get('expected')}`, observed `{cc.get('observed')}`")
                st.code(cc.get("query", ""), language="sql")
            if e.get("evidence"):
                st.markdown("**Evidence (source system → record)**")
                st.dataframe(pd.DataFrame(e["evidence"]), hide_index=True, use_container_width=True)

with tab_review:
    items = h.review_items(out.get("unresolved_conflicts", []))
    st.markdown("The agents could not settle these spellings on their own. Answer them **between runs**: download the "
                "lines, append them to `data/feedback/decisions.jsonl`, and run again. H-MEM learns every `same` "
                "verdict, so the next run escalates fewer items. Nothing here changes the current run.")
    if not items:
        st.success("No open questions in this run.")
    else:
        who = st.text_input("Your name or handle (decided_by)", key="decided_by")
        lines = []
        for i, d in enumerate(items):
            c1, c2, c3 = st.columns([3, 2, 3])
            c1.markdown(f"**{d['field']}** `{d['alias']}` vs `{d['canonical']}`  \n{d.get('outlet_id') or ''} · "
                        f"{d.get('record_ref') or ''}")
            v = c2.radio("Verdict", ["skip", "same", "different"], key=f"v{i}", horizontal=True, label_visibility="collapsed")
            note = c3.text_input("Note", key=f"n{i}", label_visibility="collapsed", placeholder="why (optional)")
            if v != "skip":
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                lines.append(h.verdict_line(d, v, who.strip(), now, result.get("run_id", ""), note.strip()))
        if lines and not who.strip():
            st.warning("Add your name first: every verdict must name the person who made it.")
        elif lines:
            try:
                from app.schemas import HumanVerdict
                for ln in lines:
                    HumanVerdict.model_validate(ln)
                body = "".join(json.dumps(ln, ensure_ascii=False) + "\n" for ln in lines)
                st.code(body, language="json")
                st.download_button(f"Download {len(lines)} verdict line(s)", body, file_name="decisions-new.jsonl",
                                   mime="application/x-ndjson")
            except (ImportError, ValueError) as exc:
                st.error(f"Verdict does not match the decisions.jsonl format: {exc}")

with tab_trace:
    try:
        events = api_get(f"/runs/{result['run_id']}/trace")
    except httpx.HTTPError:
        events = []
    if not events:
        st.info("No trace events recorded for this run.")
    else:
        t = h.trace_summary(events)
        st.markdown("**Pipeline:** " + " → ".join(t["agents"]))
        k = st.columns(5)
        k[0].metric("Trace events", t["events"])
        k[1].metric("Agent handoffs", t["handoffs"])
        k[2].metric("Critic checks", t["critic_checks"])
        k[3].metric("Critic rejections", t["critic_revisions"])
        k[4].metric("Escalated to review", t["needs_review"])
        st.caption("Sponsor calls: " + (", ".join(f"{k_}×{v}" for k_, v in t["sponsor_calls"].items()) or "none")
                   + " · served by: " + (", ".join(t["served_by"]) or "-")
                   + (" · fallbacks: " + ", ".join(t["fallbacks"]) if t["fallbacks"] else ""))
        st.dataframe(pd.DataFrame(h.trace_rows(events)), hide_index=True, use_container_width=True,
                     height=min(480, 40 + 36 * len(events)))
        st.caption(f"Written by the real run to `{result.get('log_file')}`.")

with tab_raw:
    st.download_button("Download result JSON", json.dumps(result, indent=2),
                       file_name=f"result-{result.get('run_id')}.json", mime="application/json")
    st.json(result)

st.divider()
st.caption(h.DATA_CAVEAT)
