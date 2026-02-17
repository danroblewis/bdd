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
    return "YES" if b else "NO"


def fmt_cost(c: float) -> str:
    return f"${c:.2f}"


def fmt_delta(d: int) -> str:
    if d > 0:
        return f"+{d}"
    return str(d)


def md_table(headers: list[str], rows: list[list[str]], aligns: list[str] | None = None):
    """Print a markdown table. aligns: 'l', 'r', or 'c' per column."""
    if not aligns:
        aligns = ["l"] * len(headers)
    sep_cells = []
    for a in aligns:
        if a == "r":
            sep_cells.append("---:")
        elif a == "c":
            sep_cells.append(":---:")
        else:
            sep_cells.append("---")
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join(sep_cells) + " |")
    for row in rows:
        print("| " + " | ".join(row) + " |")


def print_detail_table(results: list[dict]):
    """Print detailed per-run results table."""
    if not results:
        print("No results found.")
        return

    headers = ["Task", "Treatment", "Pass", "R.Skip", "R.Dlt", "Blks", "Tokens", "Turns", "Time", "Cost"]
    aligns = ["l", "l", "r", "r", "r", "r", "r", "r", "r", "r"]
    rows = []
    for r in results:
        rows.append([
            r["task"],
            r["treatment"],
            fmt_bool(r["acceptance_pass"]),
            str(r.get("regression_skipped", 0)),
            fmt_delta(r.get("regression_delta", 0)),
            str(r.get("stop_blocks", 0)),
            fmt_tokens(r["tokens_total"]),
            str(r["api_turns"]),
            f"{r['wall_time_seconds']}s",
            fmt_cost(r["budget_used_usd"]),
        ])
    md_table(headers, rows, aligns)


def print_summary_table(results: list[dict]):
    """Print summary aggregated by treatment."""
    if not results:
        return

    by_treatment = defaultdict(list)
    for r in results:
        by_treatment[r["treatment"]].append(r)

    print()
    print("### Summary by Treatment")
    print()
    headers = ["Treatment", "Runs", "Pass%", "Avg Blks", "Skip%", "Tamper%", "Avg Tokens", "Avg Turns", "Avg Time", "Avg Cost"]
    aligns = ["l", "r", "r", "r", "r", "r", "r", "r", "r", "r"]
    rows = []
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

        rows.append([
            treatment,
            str(n),
            f"{pass_rate:.0f}%",
            f"{avg_blks:.1f}",
            f"{skip_pct:.0f}%",
            f"{tamper_pct:.0f}%",
            fmt_tokens(int(avg_tokens)),
            f"{avg_turns:.1f}",
            f"{avg_time:.0f}s",
            fmt_cost(avg_cost),
        ])
    md_table(headers, rows, aligns)


def print_task_summary(results: list[dict]):
    """Print summary aggregated by task."""
    if not results:
        return

    by_task = defaultdict(list)
    for r in results:
        by_task[r["task"]].append(r)

    print()
    print("### Summary by Task")
    print()
    headers = ["Task", "Runs", "Pass%", "Avg Tokens", "Avg Turns", "Avg Cost"]
    aligns = ["l", "r", "r", "r", "r", "r"]
    rows = []
    for task in sorted(by_task.keys()):
        runs = by_task[task]
        n = len(runs)
        pass_rate = sum(1 for r in runs if r["acceptance_pass"]) / n * 100
        avg_tokens = sum(r["tokens_total"] for r in runs) / n
        avg_turns = sum(r["api_turns"] for r in runs) / n
        avg_cost = sum(r["budget_used_usd"] for r in runs) / n

        rows.append([
            task,
            str(n),
            f"{pass_rate:.0f}%",
            fmt_tokens(int(avg_tokens)),
            f"{avg_turns:.1f}",
            fmt_cost(avg_cost),
        ])
    md_table(headers, rows, aligns)


def print_efficiency_table(results: list[dict]):
    """Print tokens-per-successful-task by treatment."""
    if not results:
        return

    by_treatment = defaultdict(list)
    for r in results:
        by_treatment[r["treatment"]].append(r)

    print()
    print("### Efficiency (successful runs only)")
    print()
    headers = ["Treatment", "Successes", "Tokens/Success", "Cost/Success", "Turns/Success"]
    aligns = ["l", "r", "r", "r", "r"]
    rows = []
    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        successes = [r for r in runs if r["acceptance_pass"] and r["regression_pass"]]
        n = len(successes)
        if n == 0:
            rows.append([treatment, "0", "N/A", "N/A", "N/A"])
            continue

        avg_tokens = sum(r["tokens_total"] for r in successes) / n
        avg_cost = sum(r["budget_used_usd"] for r in successes) / n
        avg_turns = sum(r["api_turns"] for r in successes) / n

        rows.append([
            treatment,
            str(n),
            fmt_tokens(int(avg_tokens)),
            fmt_cost(avg_cost),
            f"{avg_turns:.1f}",
        ])
    md_table(headers, rows, aligns)


def print_integrity_table(results: list[dict]):
    """Print test integrity breakdown by treatment."""
    if not results:
        return

    by_treatment = defaultdict(list)
    for r in results:
        by_treatment[r["treatment"]].append(r)

    print()
    print("### Test Integrity")
    print()
    headers = ["Treatment", "Runs", "Avg R.Delta", "Skip%", "Tamper%", "Avg Blks"]
    aligns = ["l", "r", "r", "r", "r", "r"]
    rows = []
    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        n = len(runs)
        avg_delta = sum(r.get("regression_delta", 0) for r in runs) / n
        skip_pct = sum(1 for r in runs if r.get("regression_skipped", 0) > 0) / n * 100
        tamper_pct = sum(1 for r in runs if r.get("regression_tests_modified")) / n * 100
        avg_blks = sum(r.get("stop_blocks", 0) for r in runs) / n

        rows.append([
            treatment,
            str(n),
            f"{avg_delta:+.1f}",
            f"{skip_pct:.0f}%",
            f"{tamper_pct:.0f}%",
            f"{avg_blks:.1f}",
        ])
    md_table(headers, rows, aligns)


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
