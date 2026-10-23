"""Line-balancing performance measures.

Definitions (Groover, *Automation, Production Systems and CIM*; Scholl 1999):

* Theoretical minimum stations  m_min = ceil( sum(t) / c )
* Line efficiency               E  = sum(t) / (m * c)            (x100 %)
* Balance delay                 BD = 1 - E = (m*c - sum(t)) / (m*c)
* Idle time at station k        I_k = c - S_k
* Smoothness index              SI = sqrt( sum_k (S_max - S_k)^2 )   (Moodie & Young 1965)

Here c is the cycle time the line runs at, m the number of stations and S_k the
work content of station k.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .model import Problem, Solution


def theoretical_min_stations(problem: Problem, cycle_time: float) -> int:
    return max(1, math.ceil(problem.total_time / cycle_time - 1e-9))


def line_efficiency(station_times: list[float], cycle_time: float) -> float:
    return sum(station_times) / (len(station_times) * cycle_time)


def balance_delay(station_times: list[float], cycle_time: float) -> float:
    return 1.0 - line_efficiency(station_times, cycle_time)


def idle_times(station_times: list[float], cycle_time: float) -> list[float]:
    return [cycle_time - s for s in station_times]


def smoothness_index(station_times: list[float]) -> float:
    smax = max(station_times)
    return math.sqrt(sum((smax - s) ** 2 for s in station_times))


@dataclass
class Metrics:
    method: str
    n_stations: int
    cycle_time: float
    theoretical_min_stations: int
    total_work_content: float
    max_station_time: float
    line_efficiency_pct: float
    balance_delay_pct: float
    total_idle_time: float
    smoothness_index: float
    idle_per_station: list[float]
    feasible: bool
    optimal: bool | None
    solve_seconds: float

    def as_row(self) -> dict:
        d = asdict(self)
        d.pop("idle_per_station")
        return d


def compute_metrics(sol: Solution, cycle_time: float | None = None) -> Metrics:
    """Metrics of a solution measured against ``cycle_time`` (default: the solution's own)."""
    c = sol.cycle_time if cycle_time is None else cycle_time
    st = sol.station_times
    idle = idle_times(st, c)
    return Metrics(
        method=sol.method,
        n_stations=sol.n_stations,
        cycle_time=c,
        theoretical_min_stations=theoretical_min_stations(sol.problem, c),
        total_work_content=sol.problem.total_time,
        max_station_time=max(st),
        line_efficiency_pct=100 * line_efficiency(st, c),
        balance_delay_pct=100 * balance_delay(st, c),
        total_idle_time=sum(idle),
        smoothness_index=smoothness_index(st),
        idle_per_station=idle,
        feasible=not sol.violations(),
        optimal=sol.optimal,
        solve_seconds=sol.solve_seconds,
    )
