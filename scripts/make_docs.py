"""Regenerate every chart in docs/ and the showcase PNGs in docs/media/, plus the benchmark table.

    python scripts/make_docs.py

Plotly figures are rendered to PNG by loading them in headless Chromium (Playwright),
so no kaleido/Chrome install is needed beyond `python -m playwright install chromium`.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from linebalance import compute_metrics, run_methods, takt_time  # noqa: E402
from linebalance import viz  # noqa: E402
from linebalance.io import DATA_DIR, bundled_examples, read_tasks_csv  # noqa: E402
from linebalance.model import Solution  # noqa: E402

DOCS = ROOT / "docs"
MEDIA = DOCS / "media"
PLOTLY_JS = get_plotlyjs()


# ------------------------------------------------------------ rendering
def page_html(body: str, w: int, h: int) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
  html,body{{margin:0;background:{viz.BG};color:{viz.TEXT};font-family:{viz.FONT};}}
  .frame{{width:{w}px;height:{h}px;box-sizing:border-box;padding:56px 72px;display:flex;
          flex-direction:column;gap:18px;overflow:hidden;}}
  .eyebrow{{color:{viz.ACCENT};font-size:20px;letter-spacing:.18em;text-transform:uppercase;font-weight:700}}
  h1{{margin:0;font-size:56px;line-height:1.05;font-weight:800}}
  .sub{{color:{viz.MUTED};font-size:24px;margin:0}}
  .row{{display:flex;gap:28px;flex:1;min-height:0}}
  .col{{flex:1;min-width:0;display:flex;flex-direction:column;overflow:hidden}}
  .kpis{{display:flex;gap:18px}}
  .kpi{{flex:1;background:{viz.PANEL};border:1px solid {viz.GRID};border-radius:14px;padding:16px 22px}}
  .kpi .l{{color:{viz.MUTED};font-size:16px;text-transform:uppercase;letter-spacing:.08em}}
  .kpi .v{{font-size:40px;font-weight:800;margin-top:4px}}
  .kpi .v.bad{{color:{viz.CRITICAL}}} .kpi .v.good{{color:{viz.ACCENT}}}
  .foot{{color:{viz.MUTED};font-size:18px;display:flex;justify-content:space-between}}
  .chart{{flex:1;min-height:0;width:100%}}
</style><script>{PLOTLY_JS}</script></head>
<body><div class="frame">{body}</div>
<script>window.addEventListener('load',()=>document.querySelectorAll('.chart').forEach(d=>Plotly.Plots.resize(d)));</script>
</body></html>"""


def fig_div(fig: go.Figure, div_id: str) -> str:
    return f'<div class="chart" id="{div_id}"></div><script>' \
           f'(function(){{var f={fig.to_json()};f.layout.autosize=true;delete f.layout.width;' \
           f'delete f.layout.height;Plotly.newPlot("{div_id}",f.data,f.layout,' \
           f'{{displayModeBar:false,responsive:true}});}})();</script>'


class Renderer:
    def __init__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()
        self.tmp = Path(tempfile.mkdtemp())

    def html(self, html: str, path: Path, w: int, h: int, scale: float = 1):
        f = self.tmp / (path.stem + ".html")
        f.write_text(html, encoding="utf-8")
        page = self.browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
        page.goto(f.as_uri())
        page.wait_for_timeout(500)
        page.evaluate("document.querySelectorAll('.chart').forEach(d=>Plotly.Plots.resize(d))")
        page.wait_for_timeout(900)
        page.screenshot(path=str(path))
        page.close()
        print("wrote", path.relative_to(ROOT))

    def figure(self, fig: go.Figure, path: Path, w: int, h: int, scale: float = 2):
        body = fig_div(fig, "c")
        html = page_html(body, w, h).replace("padding:56px 72px", "padding:0")
        self.html(html, path, w, h, scale)

    def close(self):
        self.browser.close()
        self._pw.stop()


# ------------------------------------------------------------- content
def gearbox():
    ex = bundled_examples()["gearbox"]
    table = read_tasks_csv(ex.path, name="Gearbox subassembly")
    takt = takt_time(ex.available_time, ex.demand)
    sols = run_methods(table.problem, "salbp1", cycle_time=takt)
    as_is = Solution(table.problem, table.current_stations, takt, "Current state (as-is)")
    return table.problem, takt, sols, as_is


def benchmark_table():
    meta = json.loads((DATA_DIR / "benchmarks" / "optima.json").read_text())["instances"]
    rows = []
    for key, e in meta.items():
        p = read_tasks_csv(DATA_DIR / "benchmarks" / f"{key}.csv", name=key).problem
        for c, m_star in e["salbp1_optima"].items():
            sols = run_methods(p, "salbp1", cycle_time=float(c), time_limit=60)
            row = {"instance": e["name"], "n": e["n_tasks"], "type": "SALBP-1", "given": f"c={c}",
                   "known_opt": m_star}
            for s in sols:
                row[s.method] = s.n_stations
                assert s.feasible
            row["cpsat_seconds"] = round(sols[0].solve_seconds, 3)
            rows.append(row)
        for m, c_star in e["salbp2_optima"].items():
            sols = run_methods(p, "salbp2", n_stations=int(m), time_limit=60)
            row = {"instance": e["name"], "n": e["n_tasks"], "type": "SALBP-2", "given": f"m={m}",
                   "known_opt": c_star}
            for s in sols:
                row[s.method] = s.cycle_time
                assert s.feasible
            row["cpsat_seconds"] = round(sols[0].solve_seconds, 3)
            rows.append(row)
    return pd.DataFrame(rows)


METHODS = ["Optimal (CP-SAT)", "Ranked Positional Weight", "Largest Candidate Rule", "Kilbridge-Wester"]
SHORT = {"Optimal (CP-SAT)": "Optimal CP-SAT", "Ranked Positional Weight": "RPW",
         "Largest Candidate Rule": "LCR", "Kilbridge-Wester": "Kilbridge-Wester"}


def benchmark_figure(df: pd.DataFrame) -> go.Figure:
    s1 = df[df.type == "SALBP-1"]
    s2 = df[df.type == "SALBP-2"]
    hit1 = [100 * (s1[m] == s1.known_opt).mean() for m in METHODS]
    gap2 = [100 * ((s2[m] - s2.known_opt) / s2.known_opt).mean() for m in METHODS]
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.1, subplot_titles=(
        f"SALBP-1 · optimum reached (% of {len(s1)} instances)",
        f"SALBP-2 · avg cycle-time gap to optimum (% over {len(s2)} instances)"))
    colors = [viz.method_color(m) for m in METHODS]
    names = [SHORT[m] for m in METHODS]
    fig.add_trace(go.Bar(x=names, y=hit1, marker=dict(color=colors, line=dict(color=viz.BG, width=2)),
                         text=[f"{v:.0f}%" for v in hit1], textposition="outside",
                         textfont=dict(color=viz.TEXT, size=15), showlegend=False), 1, 1)
    fig.add_trace(go.Bar(x=names, y=gap2, marker=dict(color=colors, line=dict(color=viz.BG, width=2)),
                         text=[f"+{v:.1f}%" for v in gap2], textposition="outside",
                         textfont=dict(color=viz.TEXT, size=15), showlegend=False), 1, 2)
    fig.update_yaxes(range=[0, 115], ticksuffix="%", row=1, col=1)
    fig.update_yaxes(range=[0, max(gap2) * 1.35 + 0.5], ticksuffix="%", row=1, col=2)
    fig.update_annotations(font=dict(color=viz.MUTED, size=15))
    fig.update_layout(template=viz.TEMPLATE, title="Heuristics vs exact model on Scholl benchmark instances",
                      bargap=0.35, barcornerradius=4)
    return fig


def markdown_table(df: pd.DataFrame) -> str:
    lines = ["| Instance | n | Problem | Given | Known optimum | CP-SAT | RPW | LCR | KW | CP-SAT time (s) |",
             "|---|---:|---|---|---:|---:|---:|---:|---:|---:|"]
    for _, row in df.iterrows():
        def fmt(m):
            s = f"{row[m]:g}"
            return f"**{s}**" if row[m] == row.known_opt else s

        lines.append(f"| {row.instance} | {row.n} | {row.type} | {row.given} | {row.known_opt:g} | "
                     + " | ".join(fmt(m) for m in METHODS) + f" | {row.cpsat_seconds:.2f} |")
    return "\n".join(lines)


def main():
    DOCS.mkdir(exist_ok=True)
    MEDIA.mkdir(exist_ok=True)
    problem, takt, sols, as_is = gearbox()
    opt = sols[0]
    r = Renderer()
    try:
        ymax = max(as_is.station_times + [takt]) * 1.15
        before = viz.yamazumi_figure(as_is, takt=takt, time_unit="s", y_max=ymax,
                                     title="BEFORE · current line (as-is): 9 stations, S9 over takt")
        after = viz.yamazumi_figure(opt, takt=takt, time_unit="s", y_max=ymax,
                                    title="AFTER · optimal balance: 8 stations, all under takt")
        prec = viz.precedence_figure(problem, opt,
                                     title="Gearbox precedence diagram · colour alternates by assigned station")
        gantt = viz.gantt_figure(opt, takt=takt, time_unit="s")
        comp = viz.comparison_figure(sols, takt, title="Gearbox subassembly · method comparison at takt 70 s")

        # ---- README charts (2x scale for crisp GitHub rendering)
        r.html(page_html('<div class="row">' + f'<div class="col">{fig_div(before, "b")}</div>'
                         f'<div class="col">{fig_div(after, "a")}</div></div>', 1600, 560)
               .replace("padding:56px 72px", "padding:8px"), DOCS / "yamazumi_before_after.png", 1600, 560, 2)
        r.figure(prec, DOCS / "precedence_gearbox.png", 1600, 560)
        r.figure(gantt, DOCS / "gantt_gearbox.png", 1600, 520)
        r.figure(comp, DOCS / "comparison_gearbox.png", 1600, 460)

        df = benchmark_table()
        df.to_csv(DOCS / "benchmark_results.csv", index=False)
        bfig = benchmark_figure(df)
        r.figure(bfig, DOCS / "comparison_benchmarks.png", 1600, 500)

        # one-page PDF summary preview
        import matplotlib.pyplot as plt

        mfig = viz.matplotlib_summary_figure(opt, takt=takt, time_unit="s",
                                             title="Line balance summary — Gearbox subassembly")
        mfig.savefig(DOCS / "summary_page.png", dpi=110)
        mfig.savefig(DOCS / "summary_example.pdf")
        plt.close(mfig)
        print("wrote docs/summary_page.png, docs/summary_example.pdf")

        # ---- showcase media
        m_after = compute_metrics(opt, takt)
        bott = max(as_is.station_times)
        kpis = f"""<div class="kpis">
          <div class="kpi"><div class="l">Takt time</div><div class="v">{takt:g} s</div></div>
          <div class="kpi"><div class="l">As-is bottleneck</div><div class="v bad">{bott:g} s</div></div>
          <div class="kpi"><div class="l">Stations</div><div class="v good">9 → {opt.n_stations}</div></div>
          <div class="kpi"><div class="l">Line efficiency</div><div class="v good">{m_after.line_efficiency_pct:.1f}%</div></div>
          <div class="kpi"><div class="l">Output vs demand</div><div class="v good">{100 * takt / bott:.0f}% → 100%</div></div>
        </div>"""
        hero = (f'<div class="eyebrow">Assembly Line Balancer · Lean / Industrial Engineering</div>'
                f'<h1>From an unbalanced line to takt — one station fewer</h1>'
                f'<p class="sub">20-task gearbox subassembly · SALBP-1 solved exactly with OR-Tools CP-SAT</p>'
                f'{kpis}<div class="row"><div class="col">{fig_div(before, "b")}</div>'
                f'<div class="col">{fig_div(after, "a")}</div></div>'
                f'<div class="foot"><span>Piyush Bhamare</span><span>github.com/PiyushBhamare2111/assembly-line-balancer</span></div>')
        r.html(page_html(hero, 1920, 1080), MEDIA / "01_before_after_yamazumi_1920x1080.png", 1920, 1080)

        prec_page = (f'<div class="eyebrow">Step 1 · Precedence</div><h1>Which work must happen first?</h1>'
                     f'<p class="sub">Tasks laid out by precedence column; colour alternates by the station the '
                     f'optimiser assigned. Label under each node = time (s) · station.</p>'
                     f'{fig_div(prec, "p")}'
                     f'<div class="foot"><span>Piyush Bhamare</span><span>Assembly Line Balancer</span></div>')
        r.html(page_html(prec_page, 1920, 1080), MEDIA / "02_precedence_diagram_1920x1080.png", 1920, 1080)

        bench_page = (f'<div class="eyebrow">Validated on textbook benchmarks</div>'
                      f'<h1>Exact model hits every published optimum</h1>'
                      f'<p class="sub">{len(df)} Scholl (1993) instances: Jackson, Mertens, Bowman, Jaeschke, '
                      f'Mitchell, Heskiaoff, Buxey, Sawyer, Kilbridge-Wester · 7–45 tasks</p>'
                      f'{fig_div(bfig, "c")}'
                      f'<div class="foot"><span>Piyush Bhamare</span><span>RPW · LCR · Kilbridge-Wester · CP-SAT</span></div>')
        r.html(page_html(bench_page, 1920, 1080), MEDIA / "03_benchmark_comparison_1920x1080.png", 1920, 1080)

        sq_after = viz.yamazumi_figure(opt, takt=takt, time_unit="s", y_max=ymax, title=" ")
        square = (f'<div class="eyebrow">Yamazumi · after balancing</div>'
                  f'<h1 style="font-size:48px">8 stations, every one under the 70 s takt</h1>'
                  f'{fig_div(sq_after, "s")}'
                  f'<div class="foot"><span>Piyush Bhamare</span><span>Assembly Line Balancer</span></div>')
        r.html(page_html(square, 1080, 1080), MEDIA / "06_yamazumi_after_1080x1080.png", 1080, 1080)
    finally:
        r.close()
    print()
    print(markdown_table(df))


if __name__ == "__main__":
    main()
