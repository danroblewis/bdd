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


def print_engagement_table(results: list[dict]):
    """Print BDD engagement breakdown by treatment."""
    if not results:
        return

    by_treatment = defaultdict(list)
    for r in results:
        by_treatment[r["treatment"]].append(r)

    print()
    print("### BDD Engagement by Treatment")
    print()
    headers = ["Treatment", "Runs", "MCP Calls", "bdd_test", "Hooks", "Injected", "Failed", "Uniq Facets", "Edits"]
    aligns = ["l", "r", "r", "r", "r", "r", "r", "r", "r"]
    rows = []
    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        n = len(runs)
        avg_mcp = sum(r.get("mcp_tool_calls", 0) for r in runs) / n
        avg_test = sum(r.get("bdd_test_calls", 0) for r in runs) / n
        avg_hooks = sum(r.get("hook_begins", 0) for r in runs) / n
        avg_inj = sum(r.get("hook_injections", 0) for r in runs) / n
        avg_fail = sum(r.get("hook_failures", 0) for r in runs) / n
        avg_facets = sum(r.get("hook_unique_facets", 0) for r in runs) / n
        avg_edits = sum(r.get("edit_log_entries", 0) for r in runs) / n

        rows.append([
            treatment,
            str(n),
            f"{avg_mcp:.1f}",
            f"{avg_test:.1f}",
            f"{avg_hooks:.1f}",
            f"{avg_inj:.1f}",
            f"{avg_fail:.1f}",
            f"{avg_facets:.1f}",
            f"{avg_edits:.1f}",
        ])
    md_table(headers, rows, aligns)


def print_reliability_table(results: list[dict]):
    """Print tool and hook reliability by treatment."""
    if not results:
        return

    by_treatment = defaultdict(list)
    for r in results:
        by_treatment[r["treatment"]].append(r)

    print()
    print("### Tool & Hook Reliability by Treatment")
    print()
    headers = ["Treatment", "Runs", "Tool Errs", "Hook Starts", "Hook Fails", "Fail%", "Top Error"]
    aligns = ["l", "r", "r", "r", "r", "r", "l"]
    rows = []
    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        n = len(runs)
        avg_errs = sum(r.get("tool_errors", 0) for r in runs) / n
        avg_starts = sum(r.get("hook_begins", 0) for r in runs) / n
        avg_fails = sum(r.get("hook_failures", 0) for r in runs) / n
        total_starts = sum(r.get("hook_begins", 0) for r in runs)
        total_fails = sum(r.get("hook_failures", 0) for r in runs)
        fail_pct = f"{total_fails / total_starts * 100:.0f}%" if total_starts > 0 else "-"

        # Find most common error type across runs
        error_counts: dict[str, int] = defaultdict(int)
        for r in runs:
            for msg, cnt in r.get("tool_error_types", {}).items():
                error_counts[msg] += cnt
        top_error = max(error_counts, key=error_counts.get) if error_counts else "-"
        if len(top_error) > 40:
            top_error = top_error[:37] + "..."

        rows.append([
            treatment,
            str(n),
            f"{avg_errs:.1f}",
            f"{avg_starts:.1f}",
            f"{avg_fails:.1f}",
            fail_pct,
            top_error,
        ])
    md_table(headers, rows, aligns)


def print_correlation_table(results: list[dict]):
    """Print pass rate stratified by BDD engagement level."""
    if not results:
        return

    buckets: dict[str, list[dict]] = {
        "No BDD (mcp=0, hooks=0)": [],
        "Hooks only (mcp=0, hooks>0)": [],
        "MCP only (mcp>0, hooks=0)": [],
        "MCP + Hooks": [],
    }

    for r in results:
        mcp = r.get("mcp_tool_calls", 0)
        hooks = r.get("hook_begins", 0)
        if mcp > 0 and hooks > 0:
            buckets["MCP + Hooks"].append(r)
        elif mcp > 0:
            buckets["MCP only (mcp>0, hooks=0)"].append(r)
        elif hooks > 0:
            buckets["Hooks only (mcp=0, hooks>0)"].append(r)
        else:
            buckets["No BDD (mcp=0, hooks=0)"].append(r)

    print()
    print("### BDD Engagement vs Outcomes")
    print()
    headers = ["Engagement Level", "Runs", "Pass%", "Avg Tokens", "Avg Cost"]
    aligns = ["l", "r", "r", "r", "r"]
    rows = []
    for label in buckets:
        runs = buckets[label]
        n = len(runs)
        if n == 0:
            rows.append([label, "0", "-", "-", "-"])
            continue
        pass_rate = sum(1 for r in runs if r.get("acceptance_pass")) / n * 100
        avg_tokens = sum(r.get("tokens_total", 0) for r in runs) / n
        avg_cost = sum(r.get("budget_used_usd", 0) for r in runs) / n
        rows.append([
            label,
            str(n),
            f"{pass_rate:.0f}%",
            fmt_tokens(int(avg_tokens)),
            fmt_cost(avg_cost),
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
        "mcp_tool_calls", "bdd_test_calls", "bdd_motivation_calls",
        "bdd_locate_calls", "bdd_status_calls",
        "tool_errors",
        "hook_begins", "hook_ends", "hook_failures",
        "hook_injections", "hook_skips", "hook_unique_facets",
        "edit_log_entries", "edit_log_unique_facets", "edit_log_unique_files",
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
    print_engagement_table(results)
    print_reliability_table(results)
    print_correlation_table(results)

    # Export CSV if requested
    if "--csv" in sys.argv:
        csv_path = results_dir / "results.csv"
        export_csv(results, csv_path)


if __name__ == "__main__":
    main()
