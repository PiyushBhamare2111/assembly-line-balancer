"""Core data model: tasks, precedence graph, and line-balancing solutions."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import cached_property
from typing import Iterable, Sequence


class PrecedenceError(ValueError):
    """Raised when the precedence relations are invalid (unknown task or cycle)."""


class PrecedenceCycleError(PrecedenceError):
    """Raised when the precedence graph contains a cycle."""

    def __init__(self, cycle: Sequence[str]):
        self.cycle = list(cycle)
        super().__init__("Precedence cycle detected: " + " -> ".join(self.cycle))


@dataclass(frozen=True)
class Task:
    id: str
    time: float
    predecessors: tuple[str, ...] = ()
    description: str = ""


def takt_time(available_time: float, demand: float) -> float:
    """Takt time = available production time / customer demand (same period)."""
    if demand <= 0:
        raise ValueError("Demand must be positive.")
    if available_time <= 0:
        raise ValueError("Available time must be positive.")
    return available_time / demand


class Problem:
    """A single-model assembly line balancing instance.

    Task ids are strings; times are non-negative numbers in any consistent unit.
    The constructor validates the precedence graph (unknown ids, self loops, cycles).
    """

    def __init__(self, tasks: Iterable[Task], name: str = "problem"):
        self.name = name
        self.tasks: dict[str, Task] = {}
        for t in tasks:
            tid = str(t.id).strip()
            if not tid:
                raise ValueError("Task id must not be empty.")
            if tid in self.tasks:
                raise ValueError(f"Duplicate task id: {tid}")
            if t.time < 0 or not math.isfinite(t.time):
                raise ValueError(f"Task {tid} has an invalid time: {t.time}")
            preds = tuple(dict.fromkeys(str(p).strip() for p in t.predecessors if str(p).strip()))
            self.tasks[tid] = Task(tid, float(t.time), preds, t.description)
        if not self.tasks:
            raise ValueError("The problem has no tasks.")
        self._validate()

    # ------------------------------------------------------------------ graph
    def _validate(self) -> None:
        for t in self.tasks.values():
            for p in t.predecessors:
                if p not in self.tasks:
                    raise PrecedenceError(f"Task {t.id} lists unknown predecessor '{p}'.")
                if p == t.id:
                    raise PrecedenceCycleError([t.id, t.id])
        cycle = find_cycle(self.successors)
        if cycle:
            raise PrecedenceCycleError(cycle)

    @cached_property
    def successors(self) -> dict[str, list[str]]:
        succ: dict[str, list[str]] = {tid: [] for tid in self.tasks}
        for t in self.tasks.values():
            for p in t.predecessors:
                succ[p].append(t.id)
        return succ

    @property
    def ids(self) -> list[str]:
        return list(self.tasks)

    @property
    def edges(self) -> list[tuple[str, str]]:
        return [(p, t.id) for t in self.tasks.values() for p in t.predecessors]

    def time(self, tid: str) -> float:
        return self.tasks[tid].time

    @cached_property
    def topological_order(self) -> list[str]:
        indeg = {tid: len(t.predecessors) for tid, t in self.tasks.items()}
        ready = [tid for tid in self.tasks if indeg[tid] == 0]
        order: list[str] = []
        while ready:
            n = ready.pop(0)
            order.append(n)
            for s in self.successors[n]:
                indeg[s] -= 1
                if indeg[s] == 0:
                    ready.append(s)
        return order

    @cached_property
    def all_successors(self) -> dict[str, set[str]]:
        """Transitive closure of successors (every task that must come after)."""
        closure: dict[str, set[str]] = {}
        for n in reversed(self.topological_order):
            s: set[str] = set()
            for c in self.successors[n]:
                s.add(c)
                s |= closure[c]
            closure[n] = s
        return closure

    @cached_property
    def all_predecessors(self) -> dict[str, set[str]]:
        closure: dict[str, set[str]] = {}
        for n in self.topological_order:
            s: set[str] = set()
            for p in self.tasks[n].predecessors:
                s.add(p)
                s |= closure[p]
            closure[n] = s
        return closure

    @cached_property
    def columns(self) -> dict[str, int]:
        """Kilbridge-Wester column: 1 + length of the longest predecessor chain."""
        col: dict[str, int] = {}
        for n in self.topological_order:
            preds = self.tasks[n].predecessors
            col[n] = 1 + max((col[p] for p in preds), default=0)
        return col

    @property
    def total_time(self) -> float:
        return sum(t.time for t in self.tasks.values())

    @property
    def max_task_time(self) -> float:
        return max(t.time for t in self.tasks.values())

    def __len__(self) -> int:
        return len(self.tasks)

    def __repr__(self) -> str:
        return f"Problem({self.name!r}, n={len(self)}, total={self.total_time:g})"


def find_cycle(successors: dict[str, list[str]]) -> list[str] | None:
    """Return one cycle (as a closed list of ids) in a directed graph, or None."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in successors}
    parent: dict[str, str] = {}
    for root in successors:
        if color[root] != WHITE:
            continue
        stack = [(root, iter(successors[root]))]
        color[root] = GREY
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[node] = BLACK
                stack.pop()
                continue
            if color.get(nxt, WHITE) == GREY:
                cycle = [nxt]
                cur = node
                while cur != nxt:
                    cycle.append(cur)
                    cur = parent[cur]
                cycle.append(nxt)
                return list(reversed(cycle))
            if color.get(nxt, WHITE) == WHITE:
                color[nxt] = GREY
                parent[nxt] = node
                stack.append((nxt, iter(successors.get(nxt, []))))
    return None


@dataclass
class Solution:
    """A line balance: an ordered list of stations, each an ordered list of task ids."""

    problem: Problem
    stations: list[list[str]]
    cycle_time: float
    method: str
    optimal: bool | None = None  # True if proven optimal (exact solver), None for heuristics
    solve_seconds: float = 0.0
    notes: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def n_stations(self) -> int:
        return len(self.stations)

    @property
    def station_times(self) -> list[float]:
        return [sum(self.problem.time(t) for t in st) for st in self.stations]

    @property
    def max_station_time(self) -> float:
        return max(self.station_times) if self.stations else 0.0

    def station_of(self) -> dict[str, int]:
        return {t: k for k, st in enumerate(self.stations) for t in st}

    def violations(self, tol: float = 1e-9) -> list[str]:
        return check_assignment(self.problem, self.stations, self.cycle_time, tol)

    @property
    def feasible(self) -> bool:
        return not self.violations()


def check_assignment(problem: Problem, stations: Sequence[Sequence[str]], cycle_time: float,
                     tol: float = 1e-9) -> list[str]:
    """Return a list of human-readable violations (empty list means feasible)."""
    issues: list[str] = []
    where: dict[str, int] = {}
    for k, st in enumerate(stations):
        for t in st:
            if t in where:
                issues.append(f"Task {t} assigned twice (stations {where[t] + 1} and {k + 1}).")
            where[t] = k
    for t in problem.tasks:
        if t not in where:
            issues.append(f"Task {t} is not assigned.")
    for t in where:
        if t not in problem.tasks:
            issues.append(f"Unknown task {t} in assignment.")
    for k, st in enumerate(stations):
        load = sum(problem.time(t) for t in st if t in problem.tasks)
        if load > cycle_time + tol:
            issues.append(f"Station {k + 1} load {load:g} exceeds cycle time {cycle_time:g}.")
        # order inside a station must also respect precedence
        pos = {t: i for i, t in enumerate(st)}
        for t in st:
            for p in problem.tasks.get(t, Task(t, 0)).predecessors:
                if p in pos and pos[p] > pos[t]:
                    issues.append(f"In station {k + 1}, task {p} must precede task {t}.")
    for p, s in problem.edges:
        if p in where and s in where and where[p] > where[s]:
            issues.append(f"Precedence {p} -> {s} violated (station {where[p] + 1} after {where[s] + 1}).")
    return issues
