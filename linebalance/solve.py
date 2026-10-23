"""One entry point that runs any combination of methods on SALBP-1 or SALBP-2."""
from __future__ import annotations

from typing import Iterable

from . import heuristics, optimal
from .model import Problem, Solution

ALL_METHODS = [optimal.METHOD_NAME, *heuristics.HEURISTICS]


def run_methods(problem: Problem, mode: str, *, cycle_time: float | None = None,
                n_stations: int | None = None, methods: Iterable[str] = ALL_METHODS,
                time_limit: float = 30.0) -> list[Solution]:
    """mode = 'salbp1' (needs cycle_time) or 'salbp2' (needs n_stations)."""
    out = []
    for name in methods:
        if mode == "salbp1":
            if cycle_time is None:
                raise ValueError("SALBP-1 needs a cycle time.")
            if name == optimal.METHOD_NAME:
                out.append(optimal.solve_salbp1(problem, cycle_time, time_limit=time_limit))
            else:
                out.append(heuristics.solve_salbp1(problem, cycle_time, name))
        elif mode == "salbp2":
            if n_stations is None:
                raise ValueError("SALBP-2 needs a number of stations.")
            if name == optimal.METHOD_NAME:
                out.append(optimal.solve_salbp2(problem, n_stations, time_limit=time_limit))
            else:
                out.append(heuristics.solve_salbp2(problem, n_stations, name))
        else:
            raise ValueError(f"Unknown mode {mode!r}")
    return out
