#!/usr/bin/env python3
"""Reproduce the paper's illustrative game, not a banking or LLM experiment.

All input values are hypothetical. The numerical optimizer uses only Python's
standard library; matplotlib is used solely to render the publication figure.
Run from any directory: python3 analysis/audit_game.py
"""

from __future__ import annotations

import csv
import itertools
import json
import math
from fractions import Fraction
from pathlib import Path
from clean_metadata import clean_file


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results"
VALUES = (80.0, 60.0, 40.0)
DETECTION = (0.9, 0.9, 0.9)
ROUTES = ("Invoice legitimacy", "Payment history", "Contract entitlement")


def residuals(p, values=VALUES, detection=DETECTION):
    return tuple(v * (1.0 - d * x) for x, v, d in zip(p, values, detection))


def minimax(values, detection, budget):
    """Minimize max_j v_j(1-d_j p_j), with sum(p)<=budget and 0<=p<=1.

    A candidate bound t requires p_j >= max(0, (1-t/v_j)/d_j).
    Bisection finds the smallest feasible t. It returns a minimal-resource
    optimal policy, so some budget may remain unused once a detection floor
    is reached. There is no estimate from random trials in this calculation.
    """
    if len(values) != len(detection) or not values:
        raise ValueError("Matching nonempty vectors are required")
    if any(v <= 0 for v in values) or any(not 0 < d <= 1 for d in detection):
        raise ValueError("Values must be positive and detection in (0, 1]")
    if not 0 <= budget <= len(values):
        raise ValueError("Budget outside feasible range")
    lo = max(v * (1.0 - d) for v, d in zip(values, detection))
    hi = max(values)
    for _ in range(120):
        t = (lo + hi) / 2.0
        required = sum(max(0.0, (1.0 - t / v) / d)
                       for v, d in zip(values, detection))
        if required <= budget:
            hi = t
        else:
            lo = t
    p = tuple(max(0.0, min(1.0, (1.0 - hi / v) / d))
              for v, d in zip(values, detection))
    return {"audit_probabilities": p,
            "residuals": residuals(p, values, detection),
            "worst_case_loss": max(residuals(p, values, detection)),
            "expected_checks": sum(p)}


def csv_write(name, rows):
    with (OUT / name).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(exist_ok=True)
    solution = minimax(VALUES, DETECTION, 1.0)
    optimum = solution["audit_probabilities"]
    policies = {
        "No extra audit": (0.0, 0.0, 0.0),
        "Best fixed one-route audit": (1.0, 0.0, 0.0),
        "Uniform random one-route audit": (1/3, 1/3, 1/3),
        "Risk-proportional one-route audit": tuple(v / sum(VALUES) for v in VALUES),
        "Minimax one-route audit": optimum,
        "Audit every route (three checks)": (1.0, 1.0, 1.0),
    }
    baseline_rows = []
    for name, p in policies.items():
        r = residuals(p)
        baseline_rows.append({"policy": name, "expected_checks": sum(p),
                              "p1": p[0], "p2": p[1], "p3": p[2],
                              "loss_route1": r[0], "loss_route2": r[1],
                              "loss_route3": r[2], "worst_case_loss": max(r)})

    budget_rows = []
    for b in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0):
        s = minimax(VALUES, DETECTION, b)
        budget_rows.append({"budget": b, "minimax_loss": s["worst_case_loss"],
                            "uniform_loss": max(residuals((b/3,) * 3)),
                            "used_budget": s["expected_checks"],
                            "p1": s["audit_probabilities"][0],
                            "p2": s["audit_probabilities"][1],
                            "p3": s["audit_probabilities"][2]})

    detection_rows = []
    for rho in (0.0, 0.25, 0.5, 0.75, 1.0):
        d = tuple((1.0 - rho) * x for x in DETECTION)
        # rho=1 makes all discretionary checks ineffective.
        s = minimax(VALUES, d, 1.0) if rho < 1.0 else {
            "worst_case_loss": max(VALUES), "audit_probabilities": (0., 0., 0.)}
        detection_rows.append({"shared_failure_probability": rho,
                               "effective_detection": d[0],
                               "nominal_policy_loss": max(residuals(optimum, VALUES, d)),
                               "reoptimized_loss": s["worst_case_loss"],
                               "uniform_loss": max(residuals((1/3,) * 3, VALUES, d)),
                               "p1": s["audit_probabilities"][0],
                               "p2": s["audit_probabilities"][1],
                               "p3": s["audit_probabilities"][2]})

    # Attacker learns the actual selected route before committing its attack.
    pure_policies = tuple(tuple(float(i == j) for j in range(3)) for i in range(3))
    revealed_losses = tuple(max(residuals(p)) for p in pure_policies)
    leaked_nominal_loss = sum(p * loss for p, loss in zip(optimum, revealed_losses))

    # Independent checks: exact rational certificate, adversary lower bound,
    # grid search, feasible-budget checks, and integer-budget pure strategies.
    rational_t = (Fraction(3) - Fraction(9, 10)) / sum(Fraction(1, v) for v in (80, 60, 40))
    rational_p = tuple((1 - rational_t / v) / Fraction(9, 10) for v in (80, 60, 40))
    assert math.isclose(solution["worst_case_loss"], float(rational_t), abs_tol=1e-10)
    assert all(math.isclose(a, float(b), abs_tol=1e-10) for a, b in zip(optimum, rational_p))
    attacker_weights = tuple((1/v) / sum(1/w for w in VALUES) for v in VALUES)
    certified_lower = min(sum(w*r for w, r in zip(attacker_weights, residuals(p)))
                          for p in pure_policies)
    assert math.isclose(certified_lower, solution["worst_case_loss"], abs_tol=1e-10)
    grid_min = math.inf
    for i in range(1001):
        for j in range(1001-i):
            p = (i/1000, j/1000, (1000-i-j)/1000)
            grid_min = min(grid_min, max(residuals(p)))
    assert grid_min >= solution["worst_case_loss"] - 1e-9
    assert grid_min - solution["worst_case_loss"] < 0.1
    previous = math.inf
    for row in budget_rows:
        assert row["used_budget"] <= row["budget"] + 1e-9
        assert row["minimax_loss"] <= row["uniform_loss"] + 1e-9
        assert row["minimax_loss"] <= previous + 1e-9
        previous = row["minimax_loss"]
    pure_best = {}
    for budget in (0, 1, 2, 3):
        feasible = [p for p in itertools.product((0., 1.), repeat=3) if sum(p) <= budget]
        pure_best[str(budget)] = min(max(residuals(p)) for p in feasible)
        assert minimax(VALUES, DETECTION, budget)["worst_case_loss"] <= pure_best[str(budget)] + 1e-9

    results = {
        "study_type": "Deterministic illustrative game; hypothetical inputs; no LLM or bank trials",
        "routes": ROUTES, "assumed_unaudited_loss": VALUES, "assumed_detection": DETECTION,
        "base_solution": solution, "exact_value": str(rational_t),
        "exact_policy": [str(p) for p in rational_p],
        "attacker_certificate_weights": attacker_weights,
        "certificate_lower_bound": certified_lower, "grid_search_upper_bound": grid_min,
        "grid_search_step": 0.001, "best_fixed_by_integer_budget": pure_best,
        "revealed_schedule": {"pure_route_losses": revealed_losses,
                              "nominal_policy_loss": leaked_nominal_loss,
                              "best_reoptimized_loss": min(revealed_losses)},
        "baseline_rows": baseline_rows, "budget_rows": budget_rows,
        "detection_rows": detection_rows, "verification": "all assertions passed",
    }
    (OUT / "audit_game_results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    csv_write("policy_comparison.csv", baseline_rows)
    csv_write("budget_sensitivity.csv", budget_rows)
    csv_write("shared_failure_sensitivity.csv", detection_rows)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.5), constrained_layout=True)
    xs = [i/100 for i in range(301)]
    axes[0].plot(xs, [minimax(VALUES, DETECTION, b)["worst_case_loss"] for b in xs],
                 color="#145b78", linewidth=2, label="Minimax allocation")
    axes[0].plot(xs, [max(residuals((b/3,) * 3)) for b in xs],
                 color="#b4672d", linestyle="--", linewidth=2, label="Uniform allocation")
    axes[0].set(xlabel="Expected extra checks per attacked request", ylabel="Worst-case expected loss (units)",
                title="A. Verification budget", xlim=(0, 3), ylim=(0, 85))
    axes[0].legend(frameon=False)
    rs = [i/100 for i in range(101)]
    nominal, reopt = [], []
    for rho in rs:
        d = tuple((1-rho)*x for x in DETECTION)
        nominal.append(max(residuals(optimum, VALUES, d)))
        reopt.append(minimax(VALUES, d, 1)["worst_case_loss"] if rho < 1 else max(VALUES))
    axes[1].plot(rs, nominal, color="#b4672d", linestyle="--", linewidth=2, label="Original policy retained")
    axes[1].plot(rs, reopt, color="#145b78", linewidth=2, label="Policy recalculated")
    axes[1].set(xlabel="Probability the verification source fails", ylabel="Worst-case expected loss (units)",
                title="B. Verification source reliability", xlim=(0, 1), ylim=(30, 85))
    axes[1].legend(frameon=False)
    for ax in axes:
        ax.grid(alpha=.18)
    fig.savefig(OUT / "audit_sensitivity.pdf")
    fig.savefig(OUT / "audit_sensitivity.png", dpi=220)
    plt.close(fig)
    clean_file(OUT/'audit_sensitivity.pdf')
    clean_file(OUT/'audit_sensitivity.png')
    print(json.dumps({k: results[k] for k in ("base_solution", "exact_value", "exact_policy",
          "certificate_lower_bound", "grid_search_upper_bound", "revealed_schedule",
          "baseline_rows", "budget_rows", "detection_rows", "verification")}, indent=2))


if __name__ == "__main__":
    main()
