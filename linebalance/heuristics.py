"""Classic priority-rule heuristics for SALBP-1 and SALBP-2.

All three heuristics share the same station-oriented loop (the textbook procedure):

1. Open a station with the full cycle time available.
2. Among the *eligible* tasks -- all predecessors already assigned and the task
   still fits in the station's remaining time -- pick the one with the best priority.
3. Repeat until nothing fits, then open the next station.

Only the priority rule differs:

* Ranked Positional Weight (Helgeson & Birnie, 1961): positional weight =
  own time + time of every task that (transitively) follows it.
* Largest Candidate Rule: longest task time first.
* Kilbridge & Wester (1961): tasks are grouped into precedence-diagram columns;
  lower columns first, longest time first inside a column.
"""
from __future__ import annotations

import math
import time as _time
from typing import Callable

from .model import Problem, Solution

PriorityKey = Callable[[Problem, str], tuple]

EPS = 1e-9


def rpw_weights(problem: Problem) -> dict[str, float]:
    return {
        t: problem.time(t) + sum(problem.time(s) for s in problem.all_successors[t])
        for t in problem.tasks
    }


def _key_rpw(problem: Problem) -> Callable[[str], tuple]:
    w = rpw_weights(problem)
    return lambda t: (w[t], problem.time(t), len(problem.all_successors[t]))


def _key_lcr(problem: Problem) -> Callable[[str], tuple]:
    return lambda t: (problem.time(t), len(problem.all_successors[t]))


def _key_kw(problem: Problem) -> Callable[[str], tuple]:
    col = problem.columns
    return lambda t: (-col[t], problem.time(t), len(problem.all_successors[t]))


HEURISTICS: dict[str, Callable[[Problem], Callable[[str], tuple]]] = {
    "Ranked Positional Weight": _key_rpw,
    "Largest Candidate Rule": _key_lcr,
    "Kilbridge-Wester": _key_kw,
}

SHORT_NAMES = {
    "Ranked Positional Weight": "RPW",
    "Largest Candidate Rule": "LCR",
    "Kilbridge-Wester": "KW",
}


def assign_stations(problem: Problem, cycle_time: float, key: Callable[[str], tuple]) -> list[list[str]]:
    """Station-oriented greedy assignment; higher key = higher priority.

    Ties are broken by original task order (earlier first) so results are deterministic.
    """
    if problem.max_task_time > cycle_time + EPS:
        raise ValueError(
            f"Cycle time {cycle_time:g} is shorter than the longest task "
            f"({problem.max_task_time:g}); no feasible balance exists without splitting tasks."
        )
    order = {t: i for i, t in enumerate(problem.ids)}
    remaining_preds = {t: set(problem.tasks[t].predecessors) for t in problem.tasks}
    unassigned = set(problem.tasks)
    stations: list[list[str]] = []
    while unassigned:
        station: list[str] = []
        idle = cycle_time
        while True:
            eligible = [
                t for t in unassigned
                if not remaining_preds[t] and problem.time(t) <= idle + EPS
            ]
            if not eligible:
                break
            best = max(eligible, key=lambda t: (key(t), -order[t]))
            station.append(best)
            unassigned.discard(best)
            idle -= problem.time(best)
            for s in problem.successors[best]:
                remaining_preds[s].discard(best)
        if not station:  # cannot happen when cycle_time >= max task time
            raise RuntimeError("Heuristic could not place any task in a new station.")
        stations.append(station)
    return stations


def solve_salbp1(problem: Problem, cycle_time: float, method: str = "Ranked Positional Weight") -> Solution:
    """Minimise the number of stations for a given cycle (takt) time."""
    key = HEURISTICS[method](problem)
    t0 = _time.perf_counter()
    stations = assign_stations(problem, cycle_time, key)
    return Solution(problem, stations, cycle_time, method, optimal=None,
                    solve_seconds=_time.perf_counter() - t0)


def time_resolution(problem: Problem, max_decimals: int = 3) -> float:
    """Smallest step 10^-k (k <= max_decimals) that represents every task time exactly."""
    for k in range(max_decimals + 1):
        scale = 10 ** k
        if all(abs(t.time * scale - round(t.time * scale)) < 1e-6 for t in problem.tasks.values()):
            return 1.0 / scale
    return 10.0 ** -max_decimals


def salbp2_lower_bound(problem: Problem, n_stations: int) -> float:
    return max(problem.max_task_time, problem.total_time / n_stations)


def solve_salbp2(problem: Problem, n_stations: int, method: str = "Ranked Positional Weight",
                 max_steps: int = 20000) -> Solution:
    """Minimise cycle time for a given number of stations.

    Standard approach for priority-rule heuristics: start at the lower bound
    max(t_max, sum(t)/m) and increase the cycle time in the smallest meaningful
    step until the SALBP-1 heuristic fits the line into ``n_stations`` stations.
    """
    if n_stations < 1:
        raise ValueError("Number of stations must be at least 1.")
    key = HEURISTICS[method](problem)
    step = time_resolution(problem)
    t0 = _time.perf_counter()
    c = math.ceil(salbp2_lower_bound(problem, n_stations) / step - 1e-9) * step
    upper = problem.total_time
    steps = 0
    while True:
        stations = assign_stations(problem, c, key)
        if len(stations) <= n_stations or c >= upper - EPS:
            break
        steps += 1
        if steps > max_steps:  # extremely fine-grained data: fall back to coarser steps
            step *= 10
            steps = 0
        c = round(c + step, 9)
    # Report the realised cycle time (the bottleneck station), never above the trial value.
    realised = max(sum(problem.time(t) for t in st) for st in stations)
    sol = Solution(problem, stations, realised, method, optimal=None,
                   solve_seconds=_time.perf_counter() - t0)
    sol.extra["target_stations"] = n_stations
    return sol
