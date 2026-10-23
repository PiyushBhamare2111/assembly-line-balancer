import io
import json
import math

import pandas as pd
import pytest

from linebalance import (PrecedenceCycleError, PrecedenceError, Problem, Solution, Task,
                         check_assignment, compute_metrics, run_methods, takt_time)
from linebalance import heuristics, metrics, optimal
from linebalance.io import (DATA_DIR, bundled_examples, dataframe_to_problem, read_tasks_csv,
                            summary_pdf_bytes, to_csv_bytes, to_excel_bytes)
from linebalance import viz

OPTIMA = json.loads((DATA_DIR / "benchmarks" / "optima.json").read_text())["instances"]


def load(key):
    return read_tasks_csv(DATA_DIR / "benchmarks" / f"{key}.csv", name=key).problem


def assert_precedence_feasible(sol: Solution):
    where = sol.station_of()
    for p, s in sol.problem.edges:
        assert where[p] <= where[s], f"{sol.method}: {p}->{s} violated"
    assert sorted(where) == sorted(sol.problem.ids), "every task exactly once"
    assert sum(len(st) for st in sol.stations) == len(sol.problem)


def assert_within_cycle(sol: Solution, c: float):
    for k, load_ in enumerate(sol.station_times):
        assert load_ <= c + 1e-9, f"{sol.method}: station {k + 1} load {load_} > {c}"


SALBP1_CASES = [(k, float(c), m) for k, v in OPTIMA.items() for c, m in v["salbp1_optima"].items()]
SALBP2_CASES = [(k, int(m), float(c)) for k, v in OPTIMA.items() for m, c in v["salbp2_optima"].items()]


# --------------------------------------------------------- data integrity
def test_benchmark_files_match_published_totals():
    # sum of task times as tabulated by Scholl (1993) in the "Precedence graphs" sheet
    expected = {"mertens": 29, "bowman": 75, "jaeschke": 37, "jackson": 46, "mitchell": 105,
                "heskiaoff": 1024, "buxey": 324, "sawyer": 324, "kilbridge": 552}
    for key, total in expected.items():
        p = load(key)
        assert p.total_time == total
        assert len(p) == OPTIMA[key]["n_tasks"]


def test_jackson_structure():
    p = load("jackson")
    assert [p.time(str(i)) for i in range(1, 12)] == [6, 2, 5, 7, 1, 2, 3, 6, 5, 5, 4]
    assert p.tasks["7"].predecessors == ("3", "4", "5")
    assert p.tasks["11"].predecessors == ("9", "10")


# ------------------------------------------------------------- SALBP-1
@pytest.mark.parametrize("key,c,m_star", SALBP1_CASES)
def test_salbp1_all_methods_feasible_and_optimal_hits_known_optimum(key, c, m_star):
    p = load(key)
    sols = run_methods(p, "salbp1", cycle_time=c, time_limit=60)
    for sol in sols:
        assert_precedence_feasible(sol)
        assert_within_cycle(sol, c)
        assert sol.violations() == []
        assert sol.n_stations >= metrics.theoretical_min_stations(p, c)
        assert sol.n_stations >= m_star  # nobody can beat the proven optimum
    opt = sols[0]
    assert opt.method == optimal.METHOD_NAME
    assert opt.optimal is True
    assert opt.n_stations == m_star


# ------------------------------------------------------------- SALBP-2
@pytest.mark.parametrize("key,m,c_star", SALBP2_CASES)
def test_salbp2_all_methods_feasible_and_optimal_hits_known_optimum(key, m, c_star):
    p = load(key)
    sols = run_methods(p, "salbp2", n_stations=m, time_limit=60)
    for sol in sols:
        assert_precedence_feasible(sol)
        assert sol.n_stations <= m
        assert_within_cycle(sol, sol.cycle_time)
        assert sol.cycle_time == pytest.approx(sol.max_station_time)
        assert sol.cycle_time >= c_star - 1e-9
    assert sols[0].optimal is True
    assert sols[0].cycle_time == pytest.approx(c_star)


def test_heuristics_feasible_on_realistic_example_and_fractional_times():
    ex = bundled_examples()["gearbox"]
    p = read_tasks_csv(ex.path).problem
    c = takt_time(ex.available_time, ex.demand)
    assert c == pytest.approx(70.0)
    for name in heuristics.HEURISTICS:
        sol = heuristics.solve_salbp1(p, c, name)
        assert_precedence_feasible(sol)
        assert_within_cycle(sol, c)
    # fractional task times (e.g. 0.1 s time-study resolution)
    frac = Problem([Task("a", 1.5), Task("b", 2.25, ("a",)), Task("c", 0.75, ("a",)),
                    Task("d", 3.1, ("b", "c"))])
    for mode, kw in (("salbp1", {"cycle_time": 4.0}), ("salbp2", {"n_stations": 2})):
        for sol in run_methods(frac, mode, **kw):
            assert_precedence_feasible(sol)
            assert_within_cycle(sol, kw.get("cycle_time", sol.cycle_time))
    assert run_methods(frac, "salbp1", cycle_time=4.0)[0].n_stations == 2  # {a,b}=3.75, {c,d}=3.85
    assert run_methods(frac, "salbp2", n_stations=2)[0].cycle_time == pytest.approx(3.85)


def test_heuristic_rules_pick_expected_first_task():
    # a(4)->b(3), a->c(5); d(6) independent.  RPW(a)=12 > d=6 ; LCR picks d (6) first.
    p = Problem([Task("a", 4), Task("b", 3, ("a",)), Task("c", 5, ("a",)), Task("d", 6)])
    assert heuristics.rpw_weights(p) == {"a": 12, "b": 3, "c": 5, "d": 6}
    assert heuristics.solve_salbp1(p, 10, "Ranked Positional Weight").stations[0][0] == "a"
    assert heuristics.solve_salbp1(p, 10, "Largest Candidate Rule").stations[0][0] == "d"
    # KW: column 1 = {a, d}; inside the column longest first -> d
    assert p.columns == {"a": 1, "b": 2, "c": 2, "d": 1}
    assert heuristics.solve_salbp1(p, 10, "Kilbridge-Wester").stations[0][0] == "d"


def test_cycle_time_shorter_than_longest_task_raises():
    p = load("jackson")
    with pytest.raises(ValueError):
        heuristics.solve_salbp1(p, 6.5)
    with pytest.raises(ValueError):
        optimal.solve_salbp1(p, 6.5)


# --------------------------------------------------------------- metrics
def test_metrics_hand_computed_example():
    # 4 tasks, c = 10. Stations: S1={A(5),B(3)}=8, S2={C(4),D(6)}=10
    p = Problem([Task("A", 5), Task("B", 3, ("A",)), Task("C", 4, ("A",)), Task("D", 6, ("B", "C"))])
    sol = Solution(p, [["A", "B"], ["C", "D"]], 10, "manual")
    m = compute_metrics(sol)
    assert m.theoretical_min_stations == 2            # ceil(18/10)
    assert m.line_efficiency_pct == pytest.approx(90)  # 18 / (2*10)
    assert m.balance_delay_pct == pytest.approx(10)    # (20-18)/20
    assert m.idle_per_station == [2, 0]
    assert m.total_idle_time == 2
    assert m.smoothness_index == pytest.approx(2.0)    # sqrt((10-8)^2 + 0)
    assert m.max_station_time == 10
    # 3 stations, c = 8: loads 5, 7, 6 -> SI = sqrt(4 + 0 + 1)
    sol3 = Solution(p, [["A"], ["B", "C"], ["D"]], 8, "manual")
    m3 = compute_metrics(sol3)
    assert m3.line_efficiency_pct == pytest.approx(100 * 18 / 24)
    assert m3.balance_delay_pct == pytest.approx(25)
    assert m3.smoothness_index == pytest.approx(math.sqrt(5))
    assert m3.idle_per_station == [3, 1, 2]
    assert m3.theoretical_min_stations == 3  # ceil(18/8)


def test_takt_time():
    assert takt_time(25200, 360) == pytest.approx(70)
    with pytest.raises(ValueError):
        takt_time(100, 0)


# ------------------------------------------------- feasibility checking
def test_check_assignment_detects_violations():
    p = Problem([Task("A", 5), Task("B", 3, ("A",)), Task("C", 4, ("B",))])
    assert check_assignment(p, [["A", "B"], ["C"]], 8) == []
    assert any("Precedence" in v for v in check_assignment(p, [["B"], ["A", "C"]], 10))
    assert any("exceeds" in v for v in check_assignment(p, [["A", "B", "C"]], 10))
    assert any("not assigned" in v for v in check_assignment(p, [["A", "B"]], 10))
    assert any("must precede" in v for v in check_assignment(p, [["B", "A"], ["C"]], 10))


# ----------------------------------------------------- cycle detection
def test_cycle_detection_in_precedence_input():
    with pytest.raises(PrecedenceCycleError) as e:
        Problem([Task("1", 2, ("3",)), Task("2", 3, ("1",)), Task("3", 1, ("2",)), Task("4", 1)])
    cyc = e.value.cycle
    assert cyc[0] == cyc[-1] and set(cyc) == {"1", "2", "3"}


def test_self_loop_and_unknown_predecessor():
    with pytest.raises(PrecedenceCycleError):
        Problem([Task("a", 1, ("a",))])
    with pytest.raises(PrecedenceError):
        Problem([Task("a", 1, ("zzz",))])


def test_cycle_detection_from_csv():
    csv = "task_id,description,time,predecessors\nA,x,1,C\nB,y,2,A\nC,z,3,B\n"
    with pytest.raises(PrecedenceCycleError):
        read_tasks_csv(io.StringIO(csv))


# --------------------------------------------------------------- io
def test_csv_parsing_flexible_separators_and_headers():
    df = pd.DataFrame({"ID": [1, 2, 3, 4], "Time": [2, 3, 4, 5],
                       "Preds": [None, "1", "1,2", "2 | 3"]})
    p = dataframe_to_problem(df).problem
    assert p.tasks["3"].predecessors == ("1", "2")
    assert p.tasks["4"].predecessors == ("2", "3")
    with pytest.raises(ValueError):
        dataframe_to_problem(pd.DataFrame({"id": [1], "duration_x": [2]}))


def test_exports_and_charts_build():
    ex = bundled_examples()["gearbox"]
    table = read_tasks_csv(ex.path)
    assert table.current_stations is not None and len(table.current_stations) == 9
    sol = optimal.solve_salbp1(table.problem, 70)
    assert sol.n_stations == 8
    csv_bytes = to_csv_bytes(sol)
    assert csv_bytes.startswith(b"station,task_id")
    xl = to_excel_bytes(sol, comparison=[compute_metrics(sol)])
    sheets = pd.read_excel(io.BytesIO(xl), sheet_name=None)
    assert {"Assignment", "Stations", "Metrics", "Task list"} <= set(sheets)
    assert len(sheets["Assignment"]) == len(table.problem)
    pdf = summary_pdf_bytes(sol, takt=70, time_unit="s")
    assert pdf[:4] == b"%PDF"
    for fig in (viz.precedence_figure(table.problem, sol), viz.yamazumi_figure(sol, takt=70),
                viz.gantt_figure(sol, takt=70), viz.comparison_figure([sol], 70)):
        assert fig.data
