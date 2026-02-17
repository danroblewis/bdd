#!/usr/bin/env python3
"""Analyze bench results and produce comparison tables."""

import json
import sys
from pathlib import Path
from collections import defaultdict


def load_results(results_dir: Path) -> list[dict]:
    """Load all metrics.json files from results directory."""
    results = []
    for metrics_file in sorted(results_dir.glob("*/metrics.json")):
        with open(metrics_file) as f:
            results.append(json.load(f))
    return results


def fmt_tokens(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.0f}k"
    return str(n)


def fmt_bool(b: bool) -> str:
    return "YES" if b else "NO "


def fmt_cost(c: float) -> str:
    return f"${c:.2f}"


def fmt_delta(d: int) -> str:
    if d > 0:
        return f"+{d}"
    return str(d)


def print_detail_table(results: list[dict]):
    """Print detailed per-run results table."""
    if not results:
        print("No results found.")
        return

    # Header
    header = (
        f"{'Task':<25} | {'Treatment':<14} | {'Pass':>4} | {'R.Skip':>6} | {'R.Dlt':>5} | {'Blks':>4} | "
        f"{'Tokens':>7} | {'Turns':>5} | {'Time':>6} | {'Cost':>6}"
    )
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)

    for r in results:
        task = r["task"]
        treatment = r["treatment"]
        accept = fmt_bool(r["acceptance_pass"])
        r_skip = str(r.get("regression_skipped", 0))
        r_delta = fmt_delta(r.get("regression_delta", 0))
        blks = str(r.get("stop_blocks", 0))
        tokens = fmt_tokens(r["tokens_total"])
        turns = str(r["api_turns"])
        time_s = f"{r['wall_time_seconds']}s"
        cost = fmt_cost(r["budget_used_usd"])

        print(
            f"{task:<25} | {treatment:<14} | {accept:>4} | {r_skip:>6} | {r_delta:>5} | {blks:>4} | "
            f"{tokens:>7} | {turns:>5} | {time_s:>6} | {cost:>6}"
        )

    print(sep)


def print_summary_table(results: list[dict]):
    """Print summary aggregated by treatment."""
    if not results:
        return

    # Group by treatment
    by_treatment = defaultdict(list)
    for r in results:
        by_treatment[r["treatment"]].append(r)

    print()
    print("=== Summary by Treatment ===")
    header = (
        f"{'Treatment':<14} | {'Runs':>4} | {'Pass%':>5} | {'Avg Blks':>8} | {'Skip%':>5} | {'Tamper%':>7} | "
        f"{'Avg Tokens':>10} | {'Avg Turns':>9} | {'Avg Time':>8} | {'Avg Cost':>8}"
    )
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)

    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        n = len(runs)
        pass_rate = sum(1 for r in runs if r["acceptance_pass"]) / n * 100
        avg_blks = sum(r.get("stop_blocks", 0) for r in runs) / n
        skip_pct = sum(1 for r in runs if r.get("regression_skipped", 0) > 0) / n * 100
        tamper_pct = sum(1 for r in runs if r.get("regression_tests_modified")) / n * 100
        avg_tokens = sum(r["tokens_total"] for r in runs) / n
        avg_turns = sum(r["api_turns"] for r in runs) / n
        avg_time = sum(r["wall_time_seconds"] for r in runs) / n
        avg_cost = sum(r["budget_used_usd"] for r in runs) / n

        print(
            f"{treatment:<14} | {n:>4} | {pass_rate:>4.0f}% | {avg_blks:>8.1f} | {skip_pct:>4.0f}% | {tamper_pct:>6.0f}% | "
            f"{fmt_tokens(int(avg_tokens)):>10} | {avg_turns:>9.1f} | {avg_time:>7.0f}s | {fmt_cost(avg_cost):>8}"
        )

    print(sep)


def print_task_summary(results: list[dict]):
    """Print summary aggregated by task."""
    if not results:
        return

    by_task = defaultdict(list)
    for r in results:
        by_task[r["task"]].append(r)

    print()
    print("=== Summary by Task ===")
    header = f"{'Task':<25} | {'Runs':>4} | {'Pass%':>5} | {'Avg Tokens':>10} | {'Avg Turns':>9} | {'Avg Cost':>8}"
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)

    for task in sorted(by_task.keys()):
        runs = by_task[task]
        n = len(runs)
        pass_rate = sum(1 for r in runs if r["acceptance_pass"]) / n * 100
        avg_tokens = sum(r["tokens_total"] for r in runs) / n
        avg_turns = sum(r["api_turns"] for r in runs) / n
        avg_cost = sum(r["budget_used_usd"] for r in runs) / n

        print(
            f"{task:<25} | {n:>4} | {pass_rate:>4.0f}% | "
            f"{fmt_tokens(int(avg_tokens)):>10} | {avg_turns:>9.1f} | {fmt_cost(avg_cost):>8}"
        )

    print(sep)


def print_efficiency_table(results: list[dict]):
    """Print tokens-per-successful-task by treatment."""
    if not results:
        return

    by_treatment = defaultdict(list)
    for r in results:
        by_treatment[r["treatment"]].append(r)

    print()
    print("=== Efficiency (successful runs only) ===")
    header = f"{'Treatment':<14} | {'Successes':>9} | {'Tokens/Success':>14} | {'Cost/Success':>12} | {'Turns/Success':>13}"
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)

    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        successes = [r for r in runs if r["acceptance_pass"] and r["regression_pass"]]
        n = len(successes)
        if n == 0:
            print(f"{treatment:<14} | {0:>9} | {'N/A':>14} | {'N/A':>12} | {'N/A':>13}")
            continue

        avg_tokens = sum(r["tokens_total"] for r in successes) / n
        avg_cost = sum(r["budget_used_usd"] for r in successes) / n
        avg_turns = sum(r["api_turns"] for r in successes) / n

        print(
            f"{treatment:<14} | {n:>9} | {fmt_tokens(int(avg_tokens)):>14} | {fmt_cost(avg_cost):>12} | {avg_turns:>13.1f}"
        )

    print(sep)


def print_integrity_table(results: list[dict]):
    """Print test integrity breakdown by treatment."""
    if not results:
        return

    by_treatment = defaultdict(list)
    for r in results:
        by_treatment[r["treatment"]].append(r)

    print()
    print("=== Test Integrity ===")
    header = f"{'Treatment':<14} | {'Runs':>4} | {'Avg R.Delta':>11} | {'Skip%':>5} | {'Tamper%':>7} | {'Avg Blks':>8}"
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)

    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        n = len(runs)
        avg_delta = sum(r.get("regression_delta", 0) for r in runs) / n
        skip_pct = sum(1 for r in runs if r.get("regression_skipped", 0) > 0) / n * 100
        tamper_pct = sum(1 for r in runs if r.get("regression_tests_modified")) / n * 100
        avg_blks = sum(r.get("stop_blocks", 0) for r in runs) / n

        print(
            f"{treatment:<14} | {n:>4} | {avg_delta:>+10.1f} | {skip_pct:>4.0f}% | {tamper_pct:>6.0f}% | {avg_blks:>8.1f}"
        )

    print(sep)


def export_csv(results: list[dict], output_path: Path):
    """Export results as CSV."""
    if not results:
        return

    fields = [
        "task", "treatment", "timestamp",
        "acceptance_pass", "regression_pass",
        "acceptance_total", "acceptance_passed", "acceptance_failed",
        "acceptance_skipped", "acceptance_errors",
        "regression_total", "regression_passed", "regression_failed",
        "regression_skipped", "regression_errors",
        "regression_baseline", "regression_delta", "regression_tests_modified",
        "stop_blocks",
        "tokens_input", "tokens_output", "tokens_total",
        "tool_calls", "api_turns", "wall_time_seconds",
        "files_changed", "lines_added", "lines_removed",
        "budget_used_usd",
    ]

    with open(output_path, "w") as f:
        f.write(",".join(fields) + "\n")
        for r in results:
            row = [str(r.get(field, "")) for field in fields]
            f.write(",".join(row) + "\n")

    print(f"\nCSV exported to: {output_path}")


def main():
    bench_dir = Path(__file__).parent
    results_dir = bench_dir / "results"

    if not results_dir.exists():
        print(f"Results directory not found: {results_dir}")
        sys.exit(1)

    results = load_results(results_dir)

    if not results:
        print("No results found. Run some benchmarks first:")
        print("  ./bench/run.sh --task 001-add-search --treatment baseline")
        sys.exit(0)

    print(f"Loaded {len(results)} result(s) from {results_dir}\n")

    print_detail_table(results)
    print_summary_table(results)
    print_task_summary(results)
    print_efficiency_table(results)
    print_integrity_table(results)

    # Export CSV if requested
    if "--csv" in sys.argv:
        csv_path = results_dir / "results.csv"
        export_csv(results, csv_path)


if __name__ == "__main__":
    main()
