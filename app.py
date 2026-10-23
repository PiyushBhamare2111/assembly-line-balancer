"""Assembly Line Balancer - Streamlit app.

Run:  streamlit run app.py
"""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from linebalance import PrecedenceError, compute_metrics, run_methods, takt_time
from linebalance import viz
from linebalance.io import (bundled_examples, dataframe_to_problem, metrics_dataframe,
                            read_tasks_csv, stations_dataframe, summary_pdf_bytes, to_csv_bytes,
                            to_excel_bytes)
from linebalance.model import Solution
from linebalance.solve import ALL_METHODS

st.set_page_config(page_title="Assembly Line Balancer", page_icon="🏭", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.6rem;}
      div[data-testid="stMetric"] {background:#14161b;border:1px solid #262a31;border-radius:10px;
                                    padding:10px 14px;}
      div[data-testid="stMetricValue"] {color:#ff8a3d;}
      .hero h1 {margin-bottom:0;}
      .hero p {color:#9a9ca3;margin-top:.2rem;}
      .pill {display:inline-block;padding:2px 10px;border-radius:999px;border:1px solid #ff8a3d;
             color:#ff8a3d;font-size:.8rem;margin-right:6px;}
    </style>
    <div class="hero">
      <h1>Assembly Line Balancer</h1>
      <p>Balance a single-model assembly line against takt time &mdash; compare classic heuristics with an
      exact CP-SAT optimisation model, then export the balanced line.</p>
      <span class="pill">SALBP-1</span><span class="pill">SALBP-2</span>
      <span class="pill">RPW</span><span class="pill">LCR</span><span class="pill">Kilbridge-Wester</span>
      <span class="pill">OR-Tools CP-SAT</span>
    </div>
    """,
    unsafe_allow_html=True,
)

EXAMPLES = bundled_examples()
SHORT = {"Optimal (CP-SAT)": "Optimal (CP-SAT)", "Ranked Positional Weight": "RPW",
         "Largest Candidate Rule": "LCR", "Kilbridge-Wester": "Kilbridge-Wester"}

# ----------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("1 · Task list")
    source = st.radio("Source", ["Bundled example", "Upload CSV"], key="source", horizontal=True)
    example = None
    uploaded = None
    if source == "Bundled example":
        keys = list(EXAMPLES)
        key = st.selectbox("Example", keys, format_func=lambda k: EXAMPLES[k].title, key="example")
        example = EXAMPLES[key]
        st.caption(example.notes)
    else:
        uploaded = st.file_uploader("CSV with columns task_id, description, time, predecessors",
                                    type=["csv"], key="upload")
        st.caption("Predecessors: separate several ids with `;` (also `,` `|` or spaces). "
                   "Optional `current_station` column draws the as-is line.")

    st.header("2 · Problem")
    mode_label = st.radio("Objective", ["SALBP-1: minimise stations", "SALBP-2: minimise cycle time"],
                          key="mode")
    mode = "salbp1" if mode_label.startswith("SALBP-1") else "salbp2"

    time_unit = example.time_unit if example else st.text_input("Task time unit", "s", key="unit")
    takt = None
    cycle_time = None
    n_stations = None
    if mode == "salbp1":
        default_takt_mode = 0 if (example is None or example.kind == "realistic") else 1
        how = st.radio("Cycle time", ["From demand (takt time)", "Enter directly"],
                       index=default_takt_mode, key=f"how_{source}_{example.key if example else 'up'}")
        if how.startswith("From demand"):
            avail_default = (example.available_time / 60) if example and example.available_time else 420.0
            demand_default = float(example.demand) if example and example.demand else 360.0
            c1, c2 = st.columns(2)
            avail_min = c1.number_input("Available min/shift", min_value=1.0, value=float(avail_default),
                                        step=10.0, key="avail")
            shifts = c2.number_input("Shifts/day", min_value=1, value=1, step=1, key="shifts")
            demand = st.number_input("Demand (units/day)", min_value=1.0, value=demand_default,
                                     step=10.0, key="demand")
            unit_factor = 60.0 if time_unit.lower() in {"s", "sec", "seconds"} else 1.0
            takt = takt_time(avail_min * shifts * unit_factor, demand)
            cycle_time = round(takt, 6)
            st.metric("Takt time", f"{takt:.2f} {time_unit}")
        else:
            default_c = example.default_cycle_time if example and example.default_cycle_time else 10.0
            options = sorted(example.salbp1_optima) if example and example.salbp1_optima else None
            if options:
                cycle_time = st.select_slider("Cycle time (benchmark instances)", options=options,
                                              value=default_c,
                                              key=f"c_{example.key}")
                st.caption(f"Published optimum m* = **{example.salbp1_optima[cycle_time]}** stations")
            else:
                cycle_time = st.number_input("Cycle time", min_value=0.001, value=float(default_c),
                                             key="c_direct")
            takt = cycle_time
    else:
        options = sorted(example.salbp2_optima) if example and example.salbp2_optima else None
        if options:
            n_stations = st.select_slider("Number of stations", options=options,
                                          value=example.default_stations, key=f"m_{example.key}")
            st.caption(f"Published optimum c* = **{example.salbp2_optima[n_stations]:g}**")
        else:
            n_stations = int(st.number_input("Number of stations", min_value=1, value=8, step=1,
                                             key="m_direct"))

    st.header("3 · Methods")
    methods = st.multiselect("Compare", ALL_METHODS, default=ALL_METHODS, key="methods")
    time_limit = st.slider("CP-SAT time limit (s)", 1, 120, 20, key="tlimit")
    solve_clicked = st.button("Balance the line", type="primary", use_container_width=True, key="solve")

# ------------------------------------------------------------ task table
if source == "Bundled example":
    base_df = pd.read_csv(example.path, dtype={"task_id": str, "predecessors": str})
    table_key = f"editor_{example.key}"
    problem_name = example.title.split(" (")[0]
else:
    if uploaded is None:
        st.info("Upload a CSV in the sidebar, or switch to a bundled example. "
                "A template lives in `data/sample_tasks_template.csv`.")
        st.stop()
    raw = uploaded.getvalue()
    base_df = pd.read_csv(uploaded, dtype=str)
    table_key = "editor_upload_" + hashlib.md5(raw).hexdigest()[:8]
    problem_name = uploaded.name.rsplit(".", 1)[0]

base_df["predecessors"] = base_df.get("predecessors", pd.Series(dtype=str)).fillna("")

st.subheader("Task list")
st.caption("Edit times or precedence directly in the table — add or delete rows as needed.")
edited = st.data_editor(base_df, num_rows="dynamic", use_container_width=True, key=table_key,
                        height=min(420, 38 + 35 * len(base_df)))

try:
    table = dataframe_to_problem(edited, name=problem_name)
except PrecedenceError as exc:
    st.error(f"Precedence problem: {exc}")
    st.stop()
except ValueError as exc:
    st.error(str(exc))
    st.stop()
problem = table.problem

c1, c2, c3, c4 = st.columns(4)
c1.metric("Tasks", len(problem))
c2.metric("Total work content", f"{problem.total_time:g} {time_unit}")
c3.metric("Longest task", f"{problem.max_task_time:g} {time_unit}")
if mode == "salbp1":
    c4.metric("Theoretical min stations", f"{max(1, -(-problem.total_time // cycle_time)):.0f}")
else:
    c4.metric("Cycle-time lower bound",
              f"{max(problem.max_task_time, problem.total_time / n_stations):.2f}")

with st.expander("Precedence diagram", expanded=True):
    st.plotly_chart(viz.precedence_figure(problem, title="Precedence diagram (input)"),
                    use_container_width=True)

# ------------------------------------------------------------------ solve
signature = (mode, cycle_time, n_stations, tuple(methods), time_limit,
             edited.to_csv(index=False))
if solve_clicked:
    if not methods:
        st.warning("Pick at least one method.")
        st.stop()
    if mode == "salbp1" and problem.max_task_time > cycle_time + 1e-9:
        st.error(f"Cycle time {cycle_time:g} is shorter than the longest task "
                 f"({problem.max_task_time:g}). Split that task or lower demand.")
        st.stop()
    with st.spinner("Balancing…"):
        sols = run_methods(problem, mode, cycle_time=cycle_time, n_stations=n_stations,
                           methods=methods, time_limit=time_limit)
    st.session_state["results"] = {"sig": signature, "sols": sols}

res = st.session_state.get("results")
if not res or res["sig"] != signature:
    st.info("Set the inputs in the sidebar and press **Balance the line**.")
    st.stop()

sols: list[Solution] = res["sols"]
eval_c = cycle_time if mode == "salbp1" else None
mets = [compute_metrics(s, eval_c) for s in sols]

st.divider()
st.subheader("Method comparison")
cmp = metrics_dataframe(mets)[["method", "n_stations", "cycle_time", "theoretical_min_stations",
                               "line_efficiency_pct", "balance_delay_pct", "smoothness_index",
                               "total_idle_time", "feasible", "optimal", "solve_seconds"]]
known = None
if example is not None and example.kind == "benchmark":
    if mode == "salbp1" and example.salbp1_optima and cycle_time in example.salbp1_optima:
        known = ("stations", example.salbp1_optima[cycle_time])
    if mode == "salbp2" and example.salbp2_optima and n_stations in example.salbp2_optima:
        known = ("cycle time", example.salbp2_optima[n_stations])
if known:
    st.success(f"Published optimum for this instance (Scholl 1993): {known[0]} = **{known[1]:g}**")
cmp = cmp.rename(columns={
    "method": "Method", "n_stations": "Stations", "cycle_time": "Cycle time",
    "theoretical_min_stations": "Theoretical min", "line_efficiency_pct": "Efficiency %",
    "balance_delay_pct": "Balance delay %", "smoothness_index": "Smoothness index",
    "total_idle_time": "Idle / cycle", "feasible": "Feasible", "optimal": "Proven optimal",
    "solve_seconds": "Solve time (s)"})
cmp["Proven optimal"] = cmp["Proven optimal"].map({True: "yes", False: "no"}).fillna("—")
st.dataframe(
    cmp.style.format({"Cycle time": "{:g}", "Efficiency %": "{:.1f}", "Balance delay %": "{:.1f}",
                      "Smoothness index": "{:.2f}", "Idle / cycle": "{:g}", "Solve time (s)": "{:.3f}"}),
    use_container_width=True, hide_index=True)
st.plotly_chart(viz.comparison_figure(sols, cycle_time, mode=mode), use_container_width=True)

st.subheader("Balanced line")
names = [s.method for s in sols]
pick = st.radio("Show details for", names, horizontal=True, key="detail",
                format_func=lambda n: SHORT.get(n, n))
sol = sols[names.index(pick)]
m = compute_metrics(sol, eval_c)
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Stations", m.n_stations, delta=m.n_stations - m.theoretical_min_stations or None,
          delta_color="inverse", help="Delta = stations above the theoretical minimum")
k2.metric("Cycle time", f"{m.cycle_time:g} {time_unit}")
k3.metric("Line efficiency", f"{m.line_efficiency_pct:.1f}%")
k4.metric("Balance delay", f"{m.balance_delay_pct:.1f}%")
k5.metric("Smoothness index", f"{m.smoothness_index:.2f}")
if sol.notes and not sol.optimal and sol.method.startswith("Optimal"):
    st.warning(sol.notes)

shared_max = None
if table.current_stations:
    as_is = Solution(problem, table.current_stations, cycle_time or sol.cycle_time,
                     "Current state (as-is)")
    shared_max = max(as_is.station_times + sol.station_times + [takt or sol.cycle_time]) * 1.15

tab1, tab2, tab3, tab4 = st.tabs(["Yamazumi", "Station Gantt", "Precedence by station", "Station table"])
with tab1:
    if table.current_stations:
        a, b = st.columns(2)
        a.plotly_chart(viz.yamazumi_figure(as_is, takt=takt, time_unit=time_unit, y_max=shared_max,
                                           title="Before: current line (as-is)"),
                       use_container_width=True)
        b.plotly_chart(viz.yamazumi_figure(sol, takt=takt, time_unit=time_unit, y_max=shared_max,
                                           title=f"After: {SHORT.get(sol.method, sol.method)}"),
                       use_container_width=True)
        over = [f"S{i + 1}" for i, s in enumerate(as_is.station_times) if takt and s > takt]
        if over:
            st.caption(f"As-is stations over takt: {', '.join(over)} (red). Bottleneck "
                       f"{max(as_is.station_times):g} {time_unit} limits output to "
                       f"{takt / max(as_is.station_times) * 100:.0f}% of demand.")
    else:
        st.plotly_chart(viz.yamazumi_figure(sol, takt=takt, time_unit=time_unit),
                        use_container_width=True)
with tab2:
    st.plotly_chart(viz.gantt_figure(sol, takt=takt, time_unit=time_unit), use_container_width=True)
with tab3:
    st.plotly_chart(viz.precedence_figure(problem, sol), use_container_width=True)
with tab4:
    st.dataframe(stations_dataframe(sol, eval_c), use_container_width=True, hide_index=True)

viol = sol.violations()
if viol:
    st.error("Feasibility check failed: " + "; ".join(viol))
else:
    st.caption("✔ Feasibility check passed: every precedence respected, no station above the cycle time.")

st.subheader("Export")
fname = f"{problem.name.replace(' ', '_').lower()}_{SHORT.get(sol.method, sol.method).split(' ')[0].lower()}"
d1, d2, d3 = st.columns(3)
d1.download_button("Balanced line (CSV)", to_csv_bytes(sol), f"{fname}.csv", "text/csv",
                   use_container_width=True)
d2.download_button("Workbook (Excel)", to_excel_bytes(sol, eval_c, comparison=mets), f"{fname}.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                   use_container_width=True)
d3.download_button("One-page summary (PDF)",
                   summary_pdf_bytes(sol, eval_c, takt=takt, time_unit=time_unit,
                                     title=f"Line balance summary — {problem.name}"),
                   f"{fname}_summary.pdf", "application/pdf", use_container_width=True)
