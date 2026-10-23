"""Assembly line balancing (SALBP-1 / SALBP-2): heuristics, exact CP-SAT model, metrics, charts."""
from .model import (Problem, PrecedenceCycleError, PrecedenceError, Solution, Task,
                    check_assignment, takt_time)
from .metrics import compute_metrics
from .solve import run_methods, ALL_METHODS

__all__ = [
    "Problem", "Task", "Solution", "PrecedenceError", "PrecedenceCycleError",
    "check_assignment", "takt_time", "compute_metrics", "run_methods", "ALL_METHODS",
]
__version__ = "1.0.0"
