"""Exact SALBP-1 / SALBP-2 models solved with Google OR-Tools CP-SAT.

Formulation (classic binary assignment model, e.g. Patterson & Albracht 1975;
Scholl 1999):

    x[i,k] = 1 if task i is done at station k        (binary)
    y[k]   = 1 if station k is used                  (binary, SALBP-1 only)

    sum_k x[i,k] = 1                       every task assigned exactly once
    sum_i t_i x[i,k] <= c * y[k]           station load within cycle time   (SALBP-1)
    sum_i t_i x[i,k] <= C                  station load within cycle time C (SALBP-2)
    sum_k k x[i,k] <= sum_k k x[j,k]       for every precedence i -> j
    y[k] >= y[k+1]                         use stations in order (symmetry breaking)

    SALBP-1: minimise sum_k y[k]           (number of stations, cycle time fixed)
    SALBP-2: minimise C                    (cycle time, number of stations fixed)

Each task's station is restricted to [earliest, latest] computed from the head
and tail work content (standard preprocessing), which shrinks the model a lot.
Task times are scaled to integers because CP-SAT works on integer data.
A heuristic solution is passed as a hint and its value as the upper bound.
"""
from __future__ import annotations

import math
import time as _time

from ortools.sat.python import cp_model

from . import heuristics
from .model import Problem, Solution

METHOD_NAME = "Optimal (CP-SAT)"


def _scale(problem: Problem) -> tuple[dict[str, int], int]:
    res = heuristics.time_resolution(problem)
    scale = int(round(1 / res))
    return {t: int(round(problem.time(t) * scale)) for t in problem.tasks}, scale


def _station_window(problem: Problem, ti: dict[str, int], c: int, m_max: int) -> dict[str, tuple[int, int]]:
    win = {}
    for t in problem.tasks:
        head = ti[t] + sum(ti[p] for p in problem.all_predecessors[t])
        tail = ti[t] + sum(ti[s] for s in problem.all_successors[t])
        e = max(1, math.ceil(head / c))
        l = min(m_max, m_max - math.ceil(tail / c) + 1)
        win[t] = (e, max(e, l))
    return win


def _extract(problem: Problem, solver: cp_model.CpSolver, x, m: int) -> list[list[str]]:
    topo = {t: i for i, t in enumerate(problem.topological_order)}
    stations: list[list[str]] = [[] for _ in range(m)]
    for (t, k), var in x.items():
        if solver.Value(var):
            stations[k - 1].append(t)
    return [sorted(st, key=topo.get) for st in stations if st]


def _solver(time_limit: float, workers: int) -> cp_model.CpSolver:
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = float(time_limit)
    s.parameters.num_search_workers = workers
    s.parameters.random_seed = 0
    return s


def best_heuristic_salbp1(problem: Problem, cycle_time: float) -> Solution:
    sols = [heuristics.solve_salbp1(problem, cycle_time, m) for m in heuristics.HEURISTICS]
    return min(sols, key=lambda s: (s.n_stations, s.max_station_time))


def best_heuristic_salbp2(problem: Problem, n_stations: int) -> Solution:
    sols = [heuristics.solve_salbp2(problem, n_stations, m) for m in heuristics.HEURISTICS]
    return min(sols, key=lambda s: (s.cycle_time, s.n_stations))


def solve_salbp1(problem: Problem, cycle_time: float, time_limit: float = 30.0,
                 workers: int = 8) -> Solution:
    """Minimum number of stations for the given cycle time."""
    t0 = _time.perf_counter()
    ti, scale = _scale(problem)
    c = int(math.floor(cycle_time * scale + 1e-9))
    if max(ti.values()) > c:
        raise ValueError(f"Cycle time {cycle_time:g} is shorter than the longest task.")
    start = best_heuristic_salbp1(problem, cycle_time)
    ub = start.n_stations
    lb = math.ceil(sum(ti.values()) / c)
    win = _station_window(problem, ti, c, ub)

    model = cp_model.CpModel()
    x = {(t, k): model.NewBoolVar(f"x_{t}_{k}") for t in problem.tasks
         for k in range(win[t][0], win[t][1] + 1)}
    y = {k: model.NewBoolVar(f"y_{k}") for k in range(1, ub + 1)}
    for t in problem.tasks:
        model.AddExactlyOne(x[t, k] for k in range(win[t][0], win[t][1] + 1))
    st = {t: sum(k * x[t, k] for k in range(win[t][0], win[t][1] + 1)) for t in problem.tasks}
    for p, s in problem.edges:
        model.Add(st[p] <= st[s])
    for k in range(1, ub + 1):
        terms = [ti[t] * x[t, k] for t in problem.tasks if (t, k) in x]
        model.Add(sum(terms) <= c * y[k])
        for t in problem.tasks:
            if (t, k) in x:
                model.AddImplication(x[t, k], y[k])
        if k < ub:
            model.AddImplication(y[k + 1], y[k])
    for k in range(1, lb + 1):
        model.Add(y[k] == 1)
    model.Minimize(sum(y.values()))
    # warm start from the best heuristic
    where = start.station_of()
    for (t, k), var in x.items():
        model.AddHint(var, int(where[t] + 1 == k))

    solver = _solver(time_limit, workers)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        start.method, start.optimal = METHOD_NAME, False
        start.notes = "CP-SAT found no solution in the time limit; showing best heuristic."
        return start
    stations = _extract(problem, solver, x, ub)
    return Solution(problem, stations, cycle_time, METHOD_NAME,
                    optimal=status == cp_model.OPTIMAL,
                    solve_seconds=_time.perf_counter() - t0,
                    notes=solver.StatusName(status),
                    extra={"lower_bound": lb, "heuristic_upper_bound": ub})


def solve_salbp2(problem: Problem, n_stations: int, time_limit: float = 30.0,
                 workers: int = 8) -> Solution:
    """Minimum cycle time for the given number of stations."""
    t0 = _time.perf_counter()
    if n_stations < 1:
        raise ValueError("Number of stations must be at least 1.")
    ti, scale = _scale(problem)
    m = n_stations
    start = best_heuristic_salbp2(problem, m)
    c_ub = int(round(start.cycle_time * scale))
    c_lb = max(max(ti.values()), math.ceil(sum(ti.values()) / m))
    win = _station_window(problem, ti, c_ub, m)

    model = cp_model.CpModel()
    x = {(t, k): model.NewBoolVar(f"x_{t}_{k}") for t in problem.tasks
         for k in range(win[t][0], win[t][1] + 1)}
    C = model.NewIntVar(c_lb, c_ub, "C")
    for t in problem.tasks:
        model.AddExactlyOne(x[t, k] for k in range(win[t][0], win[t][1] + 1))
    st = {t: sum(k * x[t, k] for k in range(win[t][0], win[t][1] + 1)) for t in problem.tasks}
    for p, s in problem.edges:
        model.Add(st[p] <= st[s])
    for k in range(1, m + 1):
        terms = [ti[t] * x[t, k] for t in problem.tasks if (t, k) in x]
        if terms:
            model.Add(sum(terms) <= C)
    model.Minimize(C)
    where = start.station_of()
    for (t, k), var in x.items():
        model.AddHint(var, int(where[t] + 1 == k))
    model.AddHint(C, c_ub)

    solver = _solver(time_limit, workers)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        start.method, start.optimal = METHOD_NAME, False
        start.notes = "CP-SAT found no solution in the time limit; showing best heuristic."
        return start
    stations = _extract(problem, solver, x, m)
    cyc = solver.Value(C) / scale
    sol = Solution(problem, stations, cyc, METHOD_NAME,
                   optimal=status == cp_model.OPTIMAL,
                   solve_seconds=_time.perf_counter() - t0,
                   notes=solver.StatusName(status),
                   extra={"lower_bound": c_lb / scale, "heuristic_upper_bound": c_ub / scale,
                          "target_stations": m})
    return sol
