"""Reading task lists and exporting balanced lines (CSV, Excel, one-page PDF)."""
from __future__ import annotations

import io as _io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Union

import pandas as pd

from .metrics import Metrics, compute_metrics
from .model import Problem, Solution, Task

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

COLUMN_ALIASES = {
    "task_id": ["task_id", "id", "task", "task id", "element", "element_id"],
    "description": ["description", "desc", "name", "task_description", "work element"],
    "time": ["time", "task_time", "duration", "time_s", "time_min", "std_time", "standard_time"],
    "predecessors": ["predecessors", "preds", "predecessor", "precedence", "immediate_predecessors"],
    "current_station": ["current_station", "as_is_station", "station"],
}

_SPLIT = re.compile(r"[;,|\s]+")


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    lookup = {c.strip().lower(): c for c in df.columns}
    rename = {}
    for canon, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a in lookup:
                rename[lookup[a]] = canon
                break
    df = df.rename(columns=rename)
    missing = [c for c in ("task_id", "time") if c not in df.columns]
    if missing:
        raise ValueError(
            f"CSV is missing required column(s): {', '.join(missing)}. "
            "Expected columns: task_id, description, time, predecessors."
        )
    return df


def parse_predecessors(value) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "-", "—"}:
        return []
    out = []
    for p in _SPLIT.split(s):
        p = p.strip()
        if p.endswith(".0") and p[:-2].isdigit():  # "3.0" from numeric CSV columns
            p = p[:-2]
        if p:
            out.append(p)
    return out


def _clean_id(v) -> str:
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


@dataclass
class TaskTable:
    problem: Problem
    current_stations: list[list[str]] | None  # optional as-is line from the CSV


def dataframe_to_problem(df: pd.DataFrame, name: str = "uploaded") -> TaskTable:
    df = _normalise_columns(df.copy())
    df = df[df["task_id"].notna() & (df["task_id"].astype(str).str.strip() != "")]
    tasks = []
    for _, r in df.iterrows():
        try:
            t = float(r["time"])
        except (TypeError, ValueError):
            raise ValueError(f"Task {r['task_id']}: time '{r['time']}' is not a number.") from None
        desc = r.get("description", "")
        tasks.append(Task(
            id=_clean_id(r["task_id"]),
            time=t,
            predecessors=tuple(parse_predecessors(r.get("predecessors"))),
            description="" if pd.isna(desc) else str(desc),
        ))
    problem = Problem(tasks, name=name)
    current = None
    if "current_station" in df.columns and df["current_station"].notna().all():
        groups: dict = {}
        for _, r in df.iterrows():
            groups.setdefault(int(r["current_station"]), []).append(_clean_id(r["task_id"]))
        topo = {t: i for i, t in enumerate(problem.topological_order)}
        current = [sorted(groups[k], key=topo.get) for k in sorted(groups)]
    return TaskTable(problem, current)


def read_tasks_csv(source: Union[str, Path, IO], name: str | None = None) -> TaskTable:
    df = pd.read_csv(source, dtype={"task_id": str, "predecessors": str}, keep_default_na=True)
    if name is None:
        name = Path(str(getattr(source, "name", source))).stem
    return dataframe_to_problem(df, name=name)


def problem_to_dataframe(problem: Problem) -> pd.DataFrame:
    return pd.DataFrame([
        {"task_id": t.id, "description": t.description, "time": t.time,
         "predecessors": ";".join(t.predecessors)}
        for t in problem.tasks.values()
    ])


# ---------------------------------------------------------------- examples
@dataclass
class Example:
    key: str
    title: str
    path: Path
    kind: str  # "benchmark" or "realistic"
    default_cycle_time: float | None = None
    default_stations: int | None = None
    salbp1_optima: dict | None = None  # cycle time -> optimal stations
    salbp2_optima: dict | None = None  # stations -> optimal cycle time
    demand: float | None = None
    available_time: float | None = None
    time_unit: str = "time units"
    notes: str = ""


def bundled_examples() -> dict[str, Example]:
    out: dict[str, Example] = {}
    real = DATA_DIR / "examples.json"
    if real.exists():
        for key, e in json.loads(real.read_text()).items():
            out[key] = Example(key=key, path=DATA_DIR / e["file"], kind="realistic",
                               **{k: v for k, v in e.items() if k != "file"})
    meta = json.loads((DATA_DIR / "benchmarks" / "optima.json").read_text())
    for key, e in meta["instances"].items():
        o1 = {float(k): int(v) for k, v in e["salbp1_optima"].items()}
        o2 = {int(k): float(v) for k, v in e["salbp2_optima"].items()}
        c_default = sorted(o1)[len(o1) // 2] if o1 else None
        m_default = sorted(o2)[len(o2) // 2] if o2 else None
        out[key] = Example(
            key=key, title=f"{e['name']} ({e['n_tasks']} tasks) - Scholl benchmark",
            path=DATA_DIR / "benchmarks" / f"{key}.csv", kind="benchmark",
            default_cycle_time=c_default, default_stations=m_default,
            salbp1_optima=o1, salbp2_optima=o2,
            notes=f"Source file {e['source_file']} from the Scholl (1993) SALBP data set.",
        )
    return out


# ------------------------------------------------------------------ export
def assignment_dataframe(sol: Solution) -> pd.DataFrame:
    rows = []
    for k, st in enumerate(sol.stations, start=1):
        clock = 0.0
        for t in st:
            task = sol.problem.tasks[t]
            rows.append({
                "station": k, "task_id": t, "description": task.description,
                "time": task.time, "start": clock, "finish": clock + task.time,
                "predecessors": ";".join(task.predecessors),
            })
            clock += task.time
    return pd.DataFrame(rows)


def stations_dataframe(sol: Solution, cycle_time: float | None = None) -> pd.DataFrame:
    c = sol.cycle_time if cycle_time is None else cycle_time
    return pd.DataFrame([
        {"station": k, "tasks": ", ".join(st), "n_tasks": len(st), "work_content": s,
         "idle_time": c - s, "utilisation_pct": 100 * s / c}
        for k, (st, s) in enumerate(zip(sol.stations, sol.station_times), start=1)
    ])


def metrics_dataframe(metrics: list[Metrics]) -> pd.DataFrame:
    return pd.DataFrame([m.as_row() for m in metrics])


def to_csv_bytes(sol: Solution) -> bytes:
    return assignment_dataframe(sol).to_csv(index=False).encode("utf-8")


def to_excel_bytes(sol: Solution, cycle_time: float | None = None,
                   comparison: list[Metrics] | None = None) -> bytes:
    buf = _io.BytesIO()
    m = compute_metrics(sol, cycle_time)
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        assignment_dataframe(sol).to_excel(xw, sheet_name="Assignment", index=False)
        stations_dataframe(sol, cycle_time).to_excel(xw, sheet_name="Stations", index=False)
        pd.DataFrame(list(m.as_row().items()), columns=["metric", "value"]).to_excel(
            xw, sheet_name="Metrics", index=False)
        if comparison:
            metrics_dataframe(comparison).to_excel(xw, sheet_name="Method comparison", index=False)
        problem_to_dataframe(sol.problem).to_excel(xw, sheet_name="Task list", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col) + 2
                ws.column_dimensions[col[0].column_letter].width = min(width, 60)
    return buf.getvalue()


def summary_pdf_bytes(sol: Solution, cycle_time: float | None = None, takt: float | None = None,
                      title: str | None = None, time_unit: str = "time units") -> bytes:
    """One-page A4 landscape summary: KPIs, yamazumi chart and station table."""
    from .viz import matplotlib_summary_figure

    fig = matplotlib_summary_figure(sol, cycle_time=cycle_time, takt=takt, title=title,
                                    time_unit=time_unit)
    buf = _io.BytesIO()
    fig.savefig(buf, format="pdf")
    import matplotlib.pyplot as plt

    plt.close(fig)
    return buf.getvalue()
