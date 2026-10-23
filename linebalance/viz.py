"""Charts: precedence diagram, yamazumi, station Gantt, method comparison.

Interactive charts use Plotly (no system binaries needed); the one-page PDF
summary uses Matplotlib. Everything shares one dark theme with accent #ff8a3d.
"""
from __future__ import annotations

from typing import Sequence

import plotly.graph_objects as go
import plotly.io as pio

from .metrics import compute_metrics
from .model import Problem, Solution

# ------------------------------------------------------------------ theme
BG = "#0b0c0f"
PANEL = "#14161b"
GRID = "#262a31"
TEXT = "#ecebe8"
MUTED = "#9a9ca3"
ACCENT = "#ff8a3d"
ACCENT_SOFT = "#ffb27d"
BLUE = "#3987e5"
AQUA = "#199e70"
VIOLET = "#9085e9"
CRITICAL = "#e66767"

METHOD_COLORS = {
    "Optimal (CP-SAT)": ACCENT,
    "Ranked Positional Weight": BLUE,
    "Largest Candidate Rule": AQUA,
    "Kilbridge-Wester": VIOLET,
    "Current state (as-is)": "#6b6e76",
}
# alternating station tones: neighbours always contrast, station number is always labelled
STATION_TONES = [ACCENT, BLUE]
FONT = "Inter, Segoe UI, Helvetica, Arial, sans-serif"

pio.templates["linebalance_dark"] = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(family=FONT, color=TEXT, size=13),
        title=dict(font=dict(size=18, color=TEXT), x=0.01, xanchor="left"),
        xaxis=dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickcolor=GRID,
                   tickfont=dict(color=MUTED)),
        yaxis=dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickcolor=GRID,
                   tickfont=dict(color=MUTED)),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT)),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=ACCENT, font=dict(color=TEXT, family=FONT)),
        margin=dict(l=60, r=30, t=70, b=55),
        colorway=[ACCENT, BLUE, AQUA, VIOLET],
    )
)
TEMPLATE = "linebalance_dark"


def method_color(name: str) -> str:
    return METHOD_COLORS.get(name, MUTED)


def _short(text: str, n: int = 34) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


# ------------------------------------------------------------ precedence
def precedence_layout(problem: Problem) -> dict[str, tuple[float, float]]:
    """Kilbridge-Wester columns on x; tasks of a column spread on y (barycentre ordered)."""
    cols: dict[int, list[str]] = {}
    for t in problem.topological_order:
        cols.setdefault(problem.columns[t], []).append(t)
    order = sorted(cols)
    y: dict[str, float] = {}

    def place(c):
        n = len(cols[c])
        for i, t in enumerate(cols[c]):
            y[t] = (n - 1) / 2 - i

    for c in order:
        place(c)

    def bary(t, nbrs):
        vals = [y[v] for v in nbrs if v in y]
        return -sum(vals) / len(vals) if vals else -y[t]

    # a few barycentre sweeps (Sugiyama-style) to reduce edge crossings
    for _ in range(4):
        for c in order[1:]:
            cols[c].sort(key=lambda t: bary(t, problem.tasks[t].predecessors))
            place(c)
        for c in reversed(order[:-1]):
            cols[c].sort(key=lambda t: bary(t, problem.successors[t]))
            place(c)
    for c in order[1:]:
        cols[c].sort(key=lambda t: bary(t, problem.tasks[t].predecessors))
        place(c)
    return {t: (float(problem.columns[t]), y[t]) for t in problem.tasks}


def precedence_figure(problem: Problem, solution: Solution | None = None,
                      title: str | None = None, height: int | None = None) -> go.Figure:
    pos = precedence_layout(problem)
    station = solution.station_of() if solution else {}
    fig = go.Figure()
    # edges as arrows
    for p, s in problem.edges:
        x0, y0 = pos[p]
        x1, y1 = pos[s]
        fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                           showarrow=True, arrowhead=3, arrowsize=1.1, arrowwidth=1.4,
                           arrowcolor="#4a4f59", standoff=17, startstandoff=15, text="")
    ids = problem.ids
    colors, labels, hover = [], [], []
    for t in ids:
        task = problem.tasks[t]
        if station:
            k = station[t]
            colors.append(STATION_TONES[k % 2])
        else:
            colors.append(ACCENT)
        labels.append(t)
        h = f"<b>Task {t}</b><br>{task.description}<br>time: {task.time:g}"
        if task.predecessors:
            h += f"<br>after: {', '.join(task.predecessors)}"
        if station:
            h += f"<br>station: S{station[t] + 1}"
        hover.append(h)
    fig.add_trace(go.Scatter(
        x=[pos[t][0] for t in ids], y=[pos[t][1] for t in ids], mode="markers+text",
        marker=dict(size=30, color=colors, line=dict(color=BG, width=2)),
        text=labels, textfont=dict(color=BG, size=12, family=FONT), textposition="middle center",
        hovertext=hover, hoverinfo="text", showlegend=False,
    ))
    # task time (and station) under each node
    sub = [f"{problem.time(t):g}" + (f" · S{station[t] + 1}" if station else "") for t in ids]
    fig.add_trace(go.Scatter(
        x=[pos[t][0] for t in ids], y=[pos[t][1] - 0.34 for t in ids], mode="text",
        text=sub, textfont=dict(color=MUTED, size=10), hoverinfo="skip", showlegend=False,
    ))
    ncols = max(problem.columns.values())
    nrows = max(sum(1 for c in problem.columns.values() if c == k) for k in range(1, ncols + 1))
    fig.update_layout(
        template=TEMPLATE,
        title=title or ("Precedence diagram" + (" — colour alternates by station" if station else "")),
        height=height or max(360, 70 * nrows + 140),
        xaxis=dict(visible=False, range=[0.5, ncols + 0.5]),
        yaxis=dict(visible=False, range=[-(nrows / 2) - 0.3, nrows / 2 + 0.1]),
        margin=dict(l=20, r=20, t=60, b=20),
    )
    return fig


# --------------------------------------------------------------- yamazumi
def yamazumi_figure(solution: Solution, takt: float | None = None, title: str | None = None,
                    time_unit: str = "", height: int = 480, y_max: float | None = None) -> go.Figure:
    """Stacked task times per station vs the takt line (Toyota 'yamazumi' / operator balance chart)."""
    p = solution.problem
    fig = go.Figure()
    limit = takt if takt is not None else solution.cycle_time
    for k, st in enumerate(solution.stations):
        over = sum(p.time(t) for t in st) > limit + 1e-9
        base = 0.0
        for t in st:
            d = p.time(t)
            fig.add_trace(go.Bar(
                x=[f"S{k + 1}"], y=[d], base=[base], width=0.62,
                marker=dict(color=CRITICAL if over else ACCENT, line=dict(color=BG, width=2)),
                text=[t] if d >= 0.06 * limit else None, textposition="inside",
                insidetextanchor="middle", textfont=dict(color=BG, size=11),
                hovertemplate=(f"<b>S{k + 1} · task {t}</b><br>{_short(p.tasks[t].description, 60)}"
                               f"<br>time: {d:g} {time_unit}<extra></extra>"),
                showlegend=False,
            ))
            base += d
        fig.add_annotation(x=f"S{k + 1}", y=base, text=f"<b>{base:g}</b>", showarrow=False,
                           yshift=12, font=dict(color=TEXT, size=12))
    if takt is not None:
        fig.add_hline(y=takt, line=dict(color=TEXT, width=2, dash="dash"),
                      annotation_text=f"Takt {takt:g} {time_unit}", annotation_position="top left",
                      annotation_font=dict(color=TEXT))
    if takt is None or abs(solution.cycle_time - takt) > 1e-9:
        fig.add_hline(y=solution.cycle_time, line=dict(color=ACCENT_SOFT, width=1.5, dash="dot"),
                      annotation_text=f"Cycle time {solution.cycle_time:g}",
                      annotation_position="bottom right", annotation_font=dict(color=ACCENT_SOFT))
    top = max(solution.station_times + [limit, solution.cycle_time]) * 1.15
    fig.update_layout(
        template=TEMPLATE, barmode="overlay", height=height, bargap=0.25,
        title=title or f"Yamazumi chart — {solution.method}",
        yaxis=dict(title=f"Station work content{f' ({time_unit})' if time_unit else ''}",
                   range=[0, y_max or top]),
        xaxis=dict(title="Station", type="category"),
    )
    return fig


# ------------------------------------------------------------------ gantt
def gantt_figure(solution: Solution, takt: float | None = None, title: str | None = None,
                 time_unit: str = "", height: int | None = None) -> go.Figure:
    """Each station is a row; its tasks run back to back within the cycle."""
    p = solution.problem
    fig = go.Figure()
    rows = [f"S{k + 1}" for k in range(solution.n_stations)]
    for k, st in enumerate(solution.stations):
        clock = 0.0
        for t in st:
            d = p.time(t)
            fig.add_trace(go.Bar(
                y=[rows[k]], x=[d], base=[clock], orientation="h", width=0.6,
                marker=dict(color=STATION_TONES[k % 2], line=dict(color=BG, width=2)),
                text=[t] if d > 0 else None, textposition="inside", insidetextanchor="middle",
                textfont=dict(color=BG, size=11),
                hovertemplate=(f"<b>S{k + 1} · task {t}</b><br>{_short(p.tasks[t].description, 60)}"
                               f"<br>{clock:g} → {clock + d:g} {time_unit}<extra></extra>"),
                showlegend=False,
            ))
            clock += d
        idle = solution.cycle_time - clock
        if idle > 1e-9:
            fig.add_trace(go.Bar(
                y=[rows[k]], x=[idle], base=[clock], orientation="h", width=0.6,
                marker=dict(color="rgba(0,0,0,0)", line=dict(color="#3a3e47", width=1),
                            pattern=dict(shape="/", fgcolor="#3a3e47", size=6)),
                hovertemplate=f"<b>S{k + 1} idle</b><br>{idle:g} {time_unit}<extra></extra>",
                showlegend=False,
            ))
    fig.add_vline(x=solution.cycle_time, line=dict(color=ACCENT_SOFT, width=1.5, dash="dot"),
                  annotation_text=f"Cycle {solution.cycle_time:g}", annotation_position="top",
                  annotation_font=dict(color=ACCENT_SOFT))
    if takt is not None and abs(takt - solution.cycle_time) > 1e-9:
        fig.add_vline(x=takt, line=dict(color=TEXT, width=2, dash="dash"),
                      annotation_text=f"Takt {takt:g}", annotation_position="bottom",
                      annotation_font=dict(color=TEXT))
    fig.update_layout(
        template=TEMPLATE, barmode="overlay", height=height or max(320, 42 * solution.n_stations + 140),
        title=title or f"Station Gantt view — {solution.method} (hatched = idle)",
        xaxis=dict(title=f"Time within cycle{f' ({time_unit})' if time_unit else ''}"),
        yaxis=dict(autorange="reversed", type="category"),
    )
    return fig


# ------------------------------------------------------------- comparison
def comparison_figure(solutions: Sequence[Solution], cycle_time: float | None = None,
                      mode: str = "salbp1", title: str | None = None, height: int = 420) -> go.Figure:
    """Bar chart of the objective (stations or cycle time) and efficiency for each method."""
    from plotly.subplots import make_subplots

    names = [s.method for s in solutions]
    mets = [compute_metrics(s, cycle_time if mode == "salbp1" else None) for s in solutions]
    if mode == "salbp1":
        obj = [m.n_stations for m in mets]
        obj_title = "Stations (lower is better)"
    else:
        obj = [m.cycle_time for m in mets]
        obj_title = "Cycle time (lower is better)"
    eff = [m.line_efficiency_pct for m in mets]
    fig = make_subplots(rows=1, cols=2, subplot_titles=(obj_title, "Line efficiency % (higher is better)"),
                        horizontal_spacing=0.12)
    colors = [method_color(n) for n in names]
    short = [n.replace("Optimal (CP-SAT)", "Optimal CP-SAT").replace("Ranked Positional Weight", "RPW")
             .replace("Largest Candidate Rule", "LCR").replace("Kilbridge-Wester", "Kilbridge-Wester")
             for n in names]
    fig.add_trace(go.Bar(x=short, y=obj, marker=dict(color=colors, line=dict(color=BG, width=2)),
                         text=[f"{v:g}" for v in obj], textposition="outside",
                         textfont=dict(color=TEXT), hovertemplate="%{x}: %{y}<extra></extra>",
                         showlegend=False), row=1, col=1)
    fig.add_trace(go.Bar(x=short, y=eff, marker=dict(color=colors, line=dict(color=BG, width=2)),
                         text=[f"{v:.1f}%" for v in eff], textposition="outside",
                         textfont=dict(color=TEXT), hovertemplate="%{x}: %{y:.1f}%<extra></extra>",
                         showlegend=False), row=1, col=2)
    fig.update_yaxes(range=[0, max(obj) * 1.2], row=1, col=1)
    fig.update_yaxes(range=[0, 110], row=1, col=2)
    fig.update_annotations(font=dict(color=MUTED, size=13))
    fig.update_layout(template=TEMPLATE, height=height, title=title or "Method comparison",
                      bargap=0.35)
    return fig


# ----------------------------------------------------- matplotlib summary
def matplotlib_summary_figure(sol: Solution, cycle_time: float | None = None, takt: float | None = None,
                              title: str | None = None, time_unit: str = "time units"):
    """A4-landscape one-page summary (light theme, printer friendly)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    c = sol.cycle_time if cycle_time is None else cycle_time
    m = compute_metrics(sol, c)
    p = sol.problem
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.patch.set_facecolor("white")
    fig.text(0.04, 0.95, title or f"Line balance summary — {p.name}", fontsize=18, weight="bold",
             color="#111")
    fig.text(0.04, 0.915, f"Method: {sol.method}" + ("  (proven optimal)" if sol.optimal else ""),
             fontsize=11, color="#555")
    kpis = [
        ("Stations", f"{m.n_stations}"),
        ("Theoretical min", f"{m.theoretical_min_stations}"),
        ("Cycle time", f"{c:g} {time_unit}"),
        ("Takt time", f"{takt:g} {time_unit}" if takt else "—"),
        ("Line efficiency", f"{m.line_efficiency_pct:.1f}%"),
        ("Balance delay", f"{m.balance_delay_pct:.1f}%"),
        ("Smoothness index", f"{m.smoothness_index:.2f}"),
        ("Total idle / cycle", f"{m.total_idle_time:g} {time_unit}"),
    ]
    for i, (k, v) in enumerate(kpis):
        x = 0.04 + (i % 4) * 0.235
        y = 0.83 - (i // 4) * 0.075
        fig.text(x, y + 0.025, k.upper(), fontsize=8, color="#777")
        fig.text(x, y - 0.005, v, fontsize=15, weight="bold", color="#c4570f" if i == 0 else "#111")
    ax = fig.add_axes([0.06, 0.1, 0.5, 0.56])
    for k, st in enumerate(sol.stations):
        base = 0.0
        over = sum(p.time(t) for t in st) > (takt or c) + 1e-9
        for t in st:
            d = p.time(t)
            ax.bar(k + 1, d, bottom=base, color="#d64545" if over else "#ff8a3d",
                   edgecolor="white", linewidth=1.5, width=0.65)
            if d >= 0.07 * c:
                ax.text(k + 1, base + d / 2, t, ha="center", va="center", fontsize=7, color="#111")
            base += d
    ax.axhline(c, color="#c4570f", ls=":", lw=1.2, label=f"Cycle time {c:g}")
    if takt:
        ax.axhline(takt, color="#111", ls="--", lw=1.4, label=f"Takt {takt:g}")
    ax.set_xticks(range(1, sol.n_stations + 1), [f"S{k}" for k in range(1, sol.n_stations + 1)],
                  fontsize=8)
    ax.set_ylabel(f"Work content ({time_unit})")
    ax.set_title("Yamazumi — stacked task times per station", fontsize=11, loc="left")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    # station table
    tx = fig.add_axes([0.6, 0.1, 0.37, 0.56])
    tx.axis("off")
    rows = []
    for k, (st, s) in enumerate(zip(sol.stations, sol.station_times), start=1):
        tasks = ", ".join(st)
        rows.append([f"S{k}", tasks if len(tasks) < 34 else tasks[:31] + "…", f"{s:g}", f"{c - s:g}"])
    tbl = tx.table(cellText=rows, colLabels=["Stn", "Tasks", "Load", "Idle"], loc="upper center",
                   colWidths=[0.1, 0.6, 0.15, 0.15], cellLoc="left")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7 if len(rows) > 14 else 8)
    tbl.scale(1, 1.25 if len(rows) <= 16 else 0.9)
    for (r, _), cell in tbl.get_celld().items():
        cell.set_edgecolor("#ddd")
        if r == 0:
            cell.set_facecolor("#111")
            cell.get_text().set_color("white")
    fig.text(0.04, 0.03, "Generated by Assembly Line Balancer · github.com/PiyushBhamare2111/assembly-line-balancer",
             fontsize=8, color="#999")
    return fig
