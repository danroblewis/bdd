#!/usr/bin/env python3
"""Analyze bench results and produce comparison tables."""

import json
import sys
from pathlib import Path
from collections import defaultdict


# --- Treatment classification ---

# Treatments known to use subagents (for metrics missing tool_breakdown)
AGENT_TREATMENTS = {"planner-agent", "verifier-agent", "prompt-decompose", "scout-swarm"}

# Hook injection variant by treatment name
# Standard context-injection hooks fall through to "standard" at runtime.
HOOK_VARIANTS = {
    "differential-context": "differential",
    "best-chain-only": "best-chain",
    "narrative-hooks": "narrative",
    "progressive-depth": "progressive",
    "bdd-autodetect": "autodetect",
    "bdd-claim": "claim",
    "edit-guard": "guard",
    "regression-feedback": "test-feedback",
    "review-before-stop": "stop-gate",
}

# Hook-only treatments (have hooks configured but no MCP server).
# Used in diagnosis to avoid false-positive "MCP available but unused" warnings.
HOOKS_NO_MCP_TREATMENTS = {
    "edit-guard", "regression-feedback", "review-before-stop",
}

# Treatment tier classification.
# Tiers group treatments by the BDD mechanism stack they rely on.
TREATMENT_TIERS = {
    # Tier 0 — No BDD scaffolding
    "baseline":               "none",
    # Tier 1 — Static context only (CLAUDE.md / rules / pre-prompt, no runtime tools)
    "claude-md":              "context-only",
    "why-how-what":           "context-only",
    "targeted":               "context-only",
    "pre-prompt-behavioral":  "context-only",
    "test-first-workflow":    "context-only",
    "whw-plus-pre-prompt":    "context-only",
    "whw-plus-catalog-inline":"context-only",
    # Tier 2 — MCP tools without automatic hooks
    "bdd-fine-no-hooks":      "mcp-only",
    "whw-plus-bdd-test":      "mcp-only",
    "whw-combined":           "mcp-only",
    "motivation-briefing":    "mcp-only",
    # Tier 3 — Automatic hooks without MCP
    "edit-guard":             "hooks-only",
    "regression-feedback":    "hooks-only",
    "review-before-stop":     "hooks-only",
    # Tier 4 — Hooks + MCP
    "full-bdd":               "hooks+mcp",
    "bdd-fine-index":         "hooks+mcp",
    "pre-prompt-fine-index":  "hooks+mcp",
    "bdd-autodetect":         "hooks+mcp",
    "bdd-claim":              "hooks+mcp",
    "catalog-driven-planning":"hooks+mcp",
    "differential-context":   "hooks+mcp",
    "best-chain-only":        "hooks+mcp",
    "narrative-hooks":        "hooks+mcp",
    "progressive-depth":      "hooks+mcp",
    # Tier 5 — Agent / subagent orchestration
    "planner-agent":          "agent",
    "verifier-agent":         "agent",
    "prompt-decompose":       "agent",
    "scout-swarm":            "agent",
}

# Display order for tiers
TIER_ORDER = [
    "none", "context-only", "mcp-only", "hooks-only", "hooks+mcp", "agent",
]

TIER_LABELS = {
    "none":         "No BDD",
    "context-only": "Context only",
    "mcp-only":     "MCP only",
    "hooks-only":   "Hooks only",
    "hooks+mcp":    "Hooks + MCP",
    "agent":        "Agent-based",
}


def classify_run(r: dict) -> dict:
    """Classify a single run's BDD feature usage from its metrics."""
    breakdown = r.get("tool_breakdown", {})
    treatment = r.get("treatment", "")

    has_hooks = r.get("hook_begins", 0) > 0
    has_mcp = r.get("mcp_tool_calls", 0) > 0
    # Agent detection: treatment is designed to use agents, OR agent used Task tool
    # but only count Task tool as "agent" if it's an agent treatment (avoid false
    # positives from one-off Task tool use in non-agent treatments)
    is_agent_treatment = treatment in AGENT_TREATMENTS
    used_task_tool = "Task" in breakdown
    has_agents = is_agent_treatment
    has_skills = "Skill" in breakdown

    # Determine primary engagement level
    if has_agents and has_mcp and has_hooks:
        engagement = "Agent+MCP+Hooks"
    elif has_agents and has_mcp:
        engagement = "Agent+MCP"
    elif has_agents and has_hooks:
        engagement = "Agent+Hooks"
    elif has_agents:
        engagement = "Agent only"
    elif has_mcp and has_hooks:
        engagement = "MCP+Hooks"
    elif has_mcp:
        engagement = "MCP only"
    elif has_hooks:
        engagement = "Hooks only"
    else:
        engagement = "No BDD"

    hook_variant = HOOK_VARIANTS.get(treatment, "standard" if has_hooks else "none")

    # Context volume: injections + MCP calls as proxy for BDD context provided
    context_volume = r.get("hook_injections", 0) + r.get("mcp_tool_calls", 0)

    # Treatment tier (falls back to data-driven guess if treatment not in map)
    tier = TREATMENT_TIERS.get(treatment, "")
    if not tier:
        if has_agents:
            tier = "agent"
        elif has_hooks and has_mcp:
            tier = "hooks+mcp"
        elif has_hooks:
            tier = "hooks-only"
        elif has_mcp:
            tier = "mcp-only"
        else:
            tier = "none"

    return {
        "has_hooks": has_hooks,
        "has_mcp": has_mcp,
        "has_agents": has_agents,
        "used_task_tool": used_task_tool,
        "has_skills": has_skills,
        "engagement": engagement,
        "hook_variant": hook_variant,
        "context_volume": context_volume,
        "tier": tier,
        "hook_injections": r.get("hook_injections", 0),
        "hook_skips": r.get("hook_skips", 0),
        "hook_begins": r.get("hook_begins", 0),
        "hook_failures": r.get("hook_failures", 0),
        "hook_unique_facets": r.get("hook_unique_facets", 0),
        "mcp_total": r.get("mcp_tool_calls", 0),
        "bdd_test": r.get("bdd_test_calls", 0),
        "bdd_motivation": r.get("bdd_motivation_calls", 0),
        "bdd_locate": r.get("bdd_locate_calls", 0),
        "bdd_status": r.get("bdd_status_calls", 0),
    }


def engagement_tag(r: dict) -> str:
    """Short tag for detail table: shows BDD engagement at a glance."""
    c = classify_run(r)
    parts = []
    if c["has_agents"]:
        parts.append("A")
    if c["has_mcp"]:
        parts.append("M")
    if c["has_hooks"]:
        parts.append("H")
    if c["has_skills"]:
        parts.append("S")
    return "".join(parts) if parts else "-"


# --- Formatters ---

def _is_rate_limited(data: dict) -> bool:
    """Detect runs that failed due to API rate limits (Claude never executed)."""
    return data.get("tokens_total", 0) == 0 and data.get("budget_used_usd", 0) == 0


def load_results(results_dir: Path, since: str = "") -> tuple[list[dict], int]:
    """Load single-task metrics.json files from results directory (excludes sequences).

    Searches recursively so results in subdirectories (e.g. old/) are included.
    Rate-limited runs (zero tokens, zero cost) are excluded.
    If *since* is set, only results with timestamp >= since are included.

    Returns (results, num_rate_limited).
    """
    results = []
    rate_limited = 0
    for metrics_file in sorted(results_dir.glob("**/metrics.json")):
        with open(metrics_file) as f:
            data = json.load(f)
        if data.get("type") == "sequence":
            continue
        if since and data.get("timestamp", "") < since:
            continue
        if _is_rate_limited(data):
            rate_limited += 1
            continue
        results.append(data)
    return results, rate_limited


def load_sequence_results(results_dir: Path, since: str = "") -> list[dict]:
    """Load sequence-type metrics.json files from results directory.

    Searches recursively so results in subdirectories are included.
    If *since* is set, only results with timestamp >= since are included.
    """
    results = []
    for metrics_file in sorted(results_dir.glob("**/metrics.json")):
        with open(metrics_file) as f:
            data = json.load(f)
        if data.get("type") == "sequence":
            if since and data.get("timestamp", "") < since:
                continue
            results.append(data)
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


def fmt_pct(n: int, total: int) -> str:
    if total == 0:
        return "-"
    return f"{n / total * 100:.0f}%"


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


def _bucket_stats(runs: list[dict]) -> tuple[int, str, str, str, str, str]:
    """Compute common stats for a bucket of runs. Returns (n, pass%, avg_tokens, avg_cost, avg_turns, tamper%)."""
    n = len(runs)
    if n == 0:
        return (0, "-", "-", "-", "-", "-")
    pass_rate = sum(1 for r in runs if r.get("acceptance_pass")) / n * 100
    avg_tokens = sum(r.get("tokens_total", 0) for r in runs) / n
    avg_cost = sum(r.get("budget_used_usd", 0) for r in runs) / n
    avg_turns = sum(r.get("api_turns", 0) for r in runs) / n
    tamper_pct = sum(1 for r in runs if r.get("regression_tests_modified")) / n * 100
    return (
        n,
        f"{pass_rate:.0f}%",
        fmt_tokens(int(avg_tokens)),
        fmt_cost(avg_cost),
        f"{avg_turns:.1f}",
        f"{tamper_pct:.0f}%",
    )


# ============================================================
# EXISTING TABLES (enhanced)
# ============================================================

def print_detail_table(results: list[dict]):
    """Print detailed per-run results table with BDD engagement columns."""
    if not results:
        print("No results found.")
        return

    headers = [
        "Task", "Treatment", "Pass", "R.Dlt", "Blks",
        "BDD", "MCP", "Inj", "Facets",
        "Tokens", "Turns", "Time", "Cost",
    ]
    aligns = ["l", "l", "r", "r", "r", "c", "r", "r", "r", "r", "r", "r", "r"]
    rows = []
    for r in results:
        rows.append([
            r["task"],
            r["treatment"],
            fmt_bool(r["acceptance_pass"]),
            fmt_delta(r.get("regression_delta", 0)),
            str(r.get("stop_blocks", 0)),
            engagement_tag(r),
            str(r.get("mcp_tool_calls", 0)),
            str(r.get("hook_injections", 0)),
            str(r.get("hook_unique_facets", 0)),
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


# ============================================================
# NEW BDD ANALYSIS TABLES
# ============================================================

def print_treatment_features(results: list[dict]):
    """Print feature matrix: which BDD mechanisms each treatment uses."""
    if not results:
        return

    by_treatment = defaultdict(list)
    for r in results:
        by_treatment[r["treatment"]].append(r)

    print()
    print("### Treatment Feature Matrix")
    print()
    headers = ["Treatment", "Hooks", "MCP", "Agents", "Skills", "Hook Variant", "Engagement"]
    aligns = ["l", "c", "c", "c", "c", "l", "l"]
    rows = []
    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        classifications = [classify_run(r) for r in runs]
        # Aggregate: if ANY run has the feature, mark it
        any_hooks = any(c["has_hooks"] for c in classifications)
        any_mcp = any(c["has_mcp"] for c in classifications)
        any_agents = any(c["has_agents"] for c in classifications)
        any_skills = any(c["has_skills"] for c in classifications)

        # Pick the most-informed run for variant/engagement (prefer runs with BDD data)
        best = max(classifications, key=lambda c: c["context_volume"] + c["hook_begins"])
        # Override engagement based on aggregated feature presence
        if any_agents and any_mcp and any_hooks:
            eng = "Agent+MCP+Hooks"
        elif any_agents and any_mcp:
            eng = "Agent+MCP"
        elif any_agents and any_hooks:
            eng = "Agent+Hooks"
        elif any_agents:
            eng = "Agent only"
        elif any_mcp and any_hooks:
            eng = "MCP+Hooks"
        elif any_mcp:
            eng = "MCP only"
        elif any_hooks:
            eng = "Hooks only"
        else:
            eng = "No BDD"

        # Hook variant from treatment name (deterministic, not data-dependent)
        variant = HOOK_VARIANTS.get(treatment, "standard" if any_hooks else "none")

        rows.append([
            treatment,
            "Y" if any_hooks else "-",
            "Y" if any_mcp else "-",
            "Y" if any_agents else "-",
            "Y" if any_skills else "-",
            variant,
            eng,
        ])
    md_table(headers, rows, aligns)


def print_engagement_vs_outcomes(results: list[dict]):
    """Print expanded BDD engagement level vs outcomes.

    Categories: No BDD, Hooks only, MCP only, MCP+Hooks, Agent-based,
    plus skill-based if any runs use skills.
    """
    if not results:
        return

    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        c = classify_run(r)
        buckets[c["engagement"]].append(r)

    # Ordered display (show non-empty buckets in logical order)
    order = [
        "No BDD", "Hooks only", "MCP only", "MCP+Hooks",
        "Agent only", "Agent+Hooks", "Agent+MCP", "Agent+MCP+Hooks",
    ]

    print()
    print("### BDD Engagement Level vs Outcomes")
    print()
    headers = ["Engagement Level", "Runs", "Pass%", "Tamper%", "Avg Tokens", "Avg Turns", "Avg Cost"]
    aligns = ["l", "r", "r", "r", "r", "r", "r"]
    rows = []
    for label in order:
        runs = buckets.get(label, [])
        n, pass_pct, avg_tok, avg_cost, avg_turns, tamper_pct = _bucket_stats(runs)
        if n == 0:
            continue
        rows.append([label, str(n), pass_pct, tamper_pct, avg_tok, avg_turns, avg_cost])

    # Catch any engagement levels not in our order list
    for label in sorted(buckets.keys()):
        if label not in order:
            runs = buckets[label]
            n, pass_pct, avg_tok, avg_cost, avg_turns, tamper_pct = _bucket_stats(runs)
            rows.append([label, str(n), pass_pct, tamper_pct, avg_tok, avg_turns, avg_cost])

    md_table(headers, rows, aligns)


def print_context_volume_analysis(results: list[dict]):
    """Print pass rate bucketed by amount of BDD context provided.

    Context volume = hook_injections + mcp_tool_calls.
    Also shows facet coverage buckets.
    """
    if not results:
        return

    # --- Context volume (injections + MCP calls) ---
    volume_buckets: dict[str, list[dict]] = {
        "0 (none)": [],
        "1-3 (light)": [],
        "4-7 (moderate)": [],
        "8-12 (heavy)": [],
        "13+ (saturated)": [],
    }

    for r in results:
        vol = classify_run(r)["context_volume"]
        if vol == 0:
            volume_buckets["0 (none)"].append(r)
        elif vol <= 3:
            volume_buckets["1-3 (light)"].append(r)
        elif vol <= 7:
            volume_buckets["4-7 (moderate)"].append(r)
        elif vol <= 12:
            volume_buckets["8-12 (heavy)"].append(r)
        else:
            volume_buckets["13+ (saturated)"].append(r)

    print()
    print("### Context Volume vs Outcomes")
    print()
    print("Context volume = hook injections + MCP tool calls")
    print()
    headers = ["Context Volume", "Runs", "Pass%", "Tamper%", "Avg Tokens", "Avg Cost"]
    aligns = ["l", "r", "r", "r", "r", "r"]
    rows = []
    for label in volume_buckets:
        runs = volume_buckets[label]
        n, pass_pct, avg_tok, avg_cost, _, tamper_pct = _bucket_stats(runs)
        if n == 0:
            continue
        rows.append([label, str(n), pass_pct, tamper_pct, avg_tok, avg_cost])
    md_table(headers, rows, aligns)

    # --- Facet coverage buckets ---
    facet_buckets: dict[str, list[dict]] = {
        "0 facets": [],
        "1-5 facets": [],
        "6-10 facets": [],
        "11+ facets": [],
    }

    for r in results:
        facets = r.get("hook_unique_facets", 0)
        if facets == 0:
            facet_buckets["0 facets"].append(r)
        elif facets <= 5:
            facet_buckets["1-5 facets"].append(r)
        elif facets <= 10:
            facet_buckets["6-10 facets"].append(r)
        else:
            facet_buckets["11+ facets"].append(r)

    print()
    print("### Facet Coverage vs Outcomes")
    print()
    print("Unique facets surfaced by hooks during the run")
    print()
    headers = ["Facet Coverage", "Runs", "Pass%", "Tamper%", "Avg Tokens", "Avg Cost"]
    aligns = ["l", "r", "r", "r", "r", "r"]
    rows = []
    for label in facet_buckets:
        runs = facet_buckets[label]
        n, pass_pct, avg_tok, avg_cost, _, tamper_pct = _bucket_stats(runs)
        if n == 0:
            continue
        rows.append([label, str(n), pass_pct, tamper_pct, avg_tok, avg_cost])
    md_table(headers, rows, aligns)


def print_hook_effectiveness(results: list[dict]):
    """Print hook injection effectiveness for runs that have hooks."""
    # Only analyze runs with hooks
    hooked_runs = [r for r in results if r.get("hook_begins", 0) > 0]
    if not hooked_runs:
        return

    print()
    print("### Hook Injection Effectiveness")
    print()
    print("Runs with hooks only. Injection rate = injections / hook invocations.")
    print()
    headers = [
        "Treatment", "Runs", "Pass%",
        "Avg Begins", "Avg Inj", "Avg Skip", "Inj Rate",
        "Avg Facets", "Avg Fail",
    ]
    aligns = ["l", "r", "r", "r", "r", "r", "r", "r", "r"]

    by_treatment = defaultdict(list)
    for r in hooked_runs:
        by_treatment[r["treatment"]].append(r)

    rows = []
    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        n = len(runs)
        pass_rate = sum(1 for r in runs if r.get("acceptance_pass")) / n * 100
        total_begins = sum(r.get("hook_begins", 0) for r in runs)
        total_inj = sum(r.get("hook_injections", 0) for r in runs)
        total_skip = sum(r.get("hook_skips", 0) for r in runs)
        total_fail = sum(r.get("hook_failures", 0) for r in runs)
        inj_rate = f"{total_inj / total_begins * 100:.0f}%" if total_begins > 0 else "-"

        avg_begins = total_begins / n
        avg_inj = total_inj / n
        avg_skip = total_skip / n
        avg_fail = total_fail / n
        avg_facets = sum(r.get("hook_unique_facets", 0) for r in runs) / n

        rows.append([
            treatment,
            str(n),
            f"{pass_rate:.0f}%",
            f"{avg_begins:.1f}",
            f"{avg_inj:.1f}",
            f"{avg_skip:.1f}",
            inj_rate,
            f"{avg_facets:.1f}",
            f"{avg_fail:.1f}",
        ])
    md_table(headers, rows, aligns)


def print_mcp_tool_patterns(results: list[dict]):
    """Print MCP tool usage breakdown and correlation with outcomes."""
    mcp_runs = [r for r in results if r.get("mcp_tool_calls", 0) > 0]
    if not mcp_runs:
        return

    print()
    print("### MCP Tool Usage Patterns")
    print()
    print("Runs with MCP tool calls only.")
    print()
    headers = [
        "Treatment", "Runs", "Pass%",
        "bdd_test", "bdd_motiv", "bdd_locate", "bdd_status", "Total MCP",
    ]
    aligns = ["l", "r", "r", "r", "r", "r", "r", "r"]

    by_treatment = defaultdict(list)
    for r in mcp_runs:
        by_treatment[r["treatment"]].append(r)

    rows = []
    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        n = len(runs)
        pass_rate = sum(1 for r in runs if r.get("acceptance_pass")) / n * 100
        avg_test = sum(r.get("bdd_test_calls", 0) for r in runs) / n
        avg_motiv = sum(r.get("bdd_motivation_calls", 0) for r in runs) / n
        avg_locate = sum(r.get("bdd_locate_calls", 0) for r in runs) / n
        avg_status = sum(r.get("bdd_status_calls", 0) for r in runs) / n
        avg_total = sum(r.get("mcp_tool_calls", 0) for r in runs) / n

        rows.append([
            treatment,
            str(n),
            f"{pass_rate:.0f}%",
            f"{avg_test:.1f}",
            f"{avg_motiv:.1f}",
            f"{avg_locate:.1f}",
            f"{avg_status:.1f}",
            f"{avg_total:.1f}",
        ])
    md_table(headers, rows, aligns)

    # Also show per-tool usage across all MCP runs
    print()
    print("#### MCP Tool Usage Summary (across all MCP runs)")
    print()
    tool_names = ["bdd_test", "bdd_motivation", "bdd_locate", "bdd_status"]
    field_map = {
        "bdd_test": "bdd_test_calls",
        "bdd_motivation": "bdd_motivation_calls",
        "bdd_locate": "bdd_locate_calls",
        "bdd_status": "bdd_status_calls",
    }
    headers2 = ["MCP Tool", "Total Calls", "Runs Using", "Avg/Run", "Pass% (users)", "Pass% (non-users)"]
    aligns2 = ["l", "r", "r", "r", "r", "r"]
    rows2 = []
    for tool in tool_names:
        field = field_map[tool]
        total_calls = sum(r.get(field, 0) for r in results)
        users = [r for r in results if r.get(field, 0) > 0]
        non_users = [r for r in results if r.get(field, 0) == 0]
        n_users = len(users)
        avg_per_run = total_calls / n_users if n_users > 0 else 0
        pass_users = sum(1 for r in users if r.get("acceptance_pass")) / n_users * 100 if n_users > 0 else 0
        pass_non = sum(1 for r in non_users if r.get("acceptance_pass")) / len(non_users) * 100 if non_users else 0
        rows2.append([
            tool,
            str(total_calls),
            str(n_users),
            f"{avg_per_run:.1f}",
            f"{pass_users:.0f}%" if n_users > 0 else "-",
            f"{pass_non:.0f}%" if non_users else "-",
        ])
    md_table(headers2, rows2, aligns2)


def print_hook_variant_comparison(results: list[dict]):
    """Compare different hook injection strategies (standard, differential, best-chain, narrative, progressive)."""
    hooked_runs = [r for r in results if r.get("hook_begins", 0) > 0]
    if not hooked_runs:
        return

    by_variant: dict[str, list[dict]] = defaultdict(list)
    for r in hooked_runs:
        c = classify_run(r)
        by_variant[c["hook_variant"]].append(r)

    if len(by_variant) < 2:
        return

    print()
    print("### Hook Variant Comparison")
    print()
    print("Comparing different hook context injection strategies.")
    print()
    headers = ["Variant", "Runs", "Pass%", "Inj Rate", "Avg Facets", "Avg Tokens", "Avg Cost"]
    aligns = ["l", "r", "r", "r", "r", "r", "r"]
    rows = []
    for variant in sorted(by_variant.keys()):
        runs = by_variant[variant]
        n = len(runs)
        pass_rate = sum(1 for r in runs if r.get("acceptance_pass")) / n * 100
        total_begins = sum(r.get("hook_begins", 0) for r in runs)
        total_inj = sum(r.get("hook_injections", 0) for r in runs)
        inj_rate = f"{total_inj / total_begins * 100:.0f}%" if total_begins > 0 else "-"
        avg_facets = sum(r.get("hook_unique_facets", 0) for r in runs) / n
        avg_tokens = sum(r.get("tokens_total", 0) for r in runs) / n
        avg_cost = sum(r.get("budget_used_usd", 0) for r in runs) / n

        rows.append([
            variant,
            str(n),
            f"{pass_rate:.0f}%",
            inj_rate,
            f"{avg_facets:.1f}",
            fmt_tokens(int(avg_tokens)),
            fmt_cost(avg_cost),
        ])
    md_table(headers, rows, aligns)


def print_agent_outcomes(results: list[dict]):
    """Print outcomes for agent-based treatments vs non-agent treatments."""
    agent_runs = [r for r in results if classify_run(r)["has_agents"]]
    non_agent_runs = [r for r in results if not classify_run(r)["has_agents"]]

    if not agent_runs:
        return

    print()
    print("### Agent-Based Treatment Outcomes")
    print()

    headers = ["Category", "Runs", "Pass%", "Tamper%", "Avg Tokens", "Avg Turns", "Avg Cost"]
    aligns = ["l", "r", "r", "r", "r", "r", "r"]
    rows = []

    # Agent runs by treatment
    by_treatment = defaultdict(list)
    for r in agent_runs:
        by_treatment[r["treatment"]].append(r)

    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        n, pass_pct, avg_tok, avg_cost, avg_turns, tamper_pct = _bucket_stats(runs)
        rows.append([f"  {treatment}", str(n), pass_pct, tamper_pct, avg_tok, avg_turns, avg_cost])

    # Totals
    n, pass_pct, avg_tok, avg_cost, avg_turns, tamper_pct = _bucket_stats(agent_runs)
    rows.append(["**All agents**", str(n), pass_pct, tamper_pct, avg_tok, avg_turns, avg_cost])

    if non_agent_runs:
        n, pass_pct, avg_tok, avg_cost, avg_turns, tamper_pct = _bucket_stats(non_agent_runs)
        rows.append(["**Non-agent**", str(n), pass_pct, tamper_pct, avg_tok, avg_turns, avg_cost])

    md_table(headers, rows, aligns)


def print_bdd_diagnosis(results: list[dict]):
    """Identify specific BDD weaknesses: where is BDD failing to help?"""
    if not results:
        return

    print()
    print("### BDD Diagnosis: Where Is BDD Failing?")
    print()

    # 1. High context but still failing
    high_context_fails = [
        r for r in results
        if classify_run(r)["context_volume"] >= 5 and not r.get("acceptance_pass")
    ]
    high_context_passes = [
        r for r in results
        if classify_run(r)["context_volume"] >= 5 and r.get("acceptance_pass")
    ]

    print("**High context (5+ interactions) outcomes:**")
    total_high = len(high_context_fails) + len(high_context_passes)
    if total_high > 0:
        print(f"  Pass: {len(high_context_passes)}/{total_high} "
              f"({len(high_context_passes) / total_high * 100:.0f}%)")
        if high_context_fails:
            print(f"  Failed treatments: "
                  + ", ".join(sorted(set(r["treatment"] for r in high_context_fails))))
    else:
        print("  No runs with high BDD context volume.")
    print()

    # 2. Hooks fired but nothing injected
    wasted_hooks = [
        r for r in results
        if r.get("hook_begins", 0) > 0 and r.get("hook_injections", 0) == 0
    ]
    if wasted_hooks:
        print("**Hooks fired but zero injections (wasted hooks):**")
        for r in wasted_hooks:
            print(f"  {r['task']} / {r['treatment']}: "
                  f"{r.get('hook_begins', 0)} begins, "
                  f"{r.get('hook_skips', 0)} skips, "
                  f"{r.get('hook_failures', 0)} failures")
        print()

    # 3. MCP tools available but never called
    mcp_available_unused = [
        r for r in results
        if r.get("mcp_tool_calls", 0) == 0
        and r.get("hook_begins", 0) > 0  # BDD treatment (has hooks = BDD is set up)
        and r.get("treatment", "") not in HOOKS_NO_MCP_TREATMENTS
    ]
    if mcp_available_unused:
        print("**BDD treatments where agent never called MCP tools:**")
        for r in mcp_available_unused:
            print(f"  {r['task']} / {r['treatment']}")
        print()

    # 4. Hook failures (begins > ends)
    hook_failure_runs = [
        r for r in results
        if r.get("hook_failures", 0) > 0
    ]
    if hook_failure_runs:
        print("**Runs with hook failures (incomplete hooks):**")
        for r in hook_failure_runs:
            print(f"  {r['task']} / {r['treatment']}: "
                  f"{r.get('hook_failures', 0)} failures out of "
                  f"{r.get('hook_begins', 0)} begins")
        print()

    # 5. BDD context provided but tests tampered
    bdd_tamper = [
        r for r in results
        if (r.get("hook_injections", 0) > 0 or r.get("mcp_tool_calls", 0) > 0)
        and r.get("regression_tests_modified")
    ]
    if bdd_tamper:
        print("**BDD context provided but agent still tampered with tests:**")
        for r in bdd_tamper:
            c = classify_run(r)
            print(f"  {r['task']} / {r['treatment']}: "
                  f"context_vol={c['context_volume']}, "
                  f"pass={fmt_bool(r.get('acceptance_pass', False))}")
        print()

    # 6. Cost efficiency: BDD overhead analysis
    bdd_runs = [r for r in results
                if r.get("hook_begins", 0) > 0 or r.get("mcp_tool_calls", 0) > 0]
    no_bdd_runs = [r for r in results
                   if r.get("hook_begins", 0) == 0 and r.get("mcp_tool_calls", 0) == 0
                   and not classify_run(r)["has_agents"]]
    if bdd_runs and no_bdd_runs:
        bdd_avg_cost = sum(r.get("budget_used_usd", 0) for r in bdd_runs) / len(bdd_runs)
        no_bdd_avg_cost = sum(r.get("budget_used_usd", 0) for r in no_bdd_runs) / len(no_bdd_runs)
        bdd_pass = sum(1 for r in bdd_runs if r.get("acceptance_pass")) / len(bdd_runs) * 100
        no_bdd_pass = sum(1 for r in no_bdd_runs if r.get("acceptance_pass")) / len(no_bdd_runs) * 100

        print("**BDD cost-effectiveness summary:**")
        print(f"  BDD runs:    {len(bdd_runs)} runs, "
              f"{bdd_pass:.0f}% pass, "
              f"avg cost {fmt_cost(bdd_avg_cost)}")
        print(f"  No-BDD runs: {len(no_bdd_runs)} runs, "
              f"{no_bdd_pass:.0f}% pass, "
              f"avg cost {fmt_cost(no_bdd_avg_cost)}")
        if no_bdd_avg_cost > 0:
            overhead = (bdd_avg_cost - no_bdd_avg_cost) / no_bdd_avg_cost * 100
            print(f"  Cost overhead: {overhead:+.0f}%")
        delta_pass = bdd_pass - no_bdd_pass
        print(f"  Pass rate delta: {delta_pass:+.0f}pp")
        print()


def print_context_vs_pass_scatter(results: list[dict]):
    """Print per-run context volume vs pass as a sortable list for diagnosis."""
    bdd_runs = [r for r in results
                if r.get("hook_begins", 0) > 0 or r.get("mcp_tool_calls", 0) > 0]
    if not bdd_runs:
        return

    print()
    print("### Per-Run BDD Context Detail")
    print()
    print("All BDD-active runs sorted by context volume (descending).")
    print()

    headers = ["Task", "Treatment", "Pass", "CtxVol", "Inj", "MCP", "Facets", "Variant", "Tokens", "Cost"]
    aligns = ["l", "l", "c", "r", "r", "r", "r", "l", "r", "r"]

    decorated = []
    for r in bdd_runs:
        c = classify_run(r)
        decorated.append((c["context_volume"], r, c))
    decorated.sort(key=lambda x: -x[0])

    rows = []
    for vol, r, c in decorated:
        rows.append([
            r["task"],
            r["treatment"],
            fmt_bool(r.get("acceptance_pass", False)),
            str(vol),
            str(c["hook_injections"]),
            str(c["mcp_total"]),
            str(c["hook_unique_facets"]),
            c["hook_variant"],
            fmt_tokens(r.get("tokens_total", 0)),
            fmt_cost(r.get("budget_used_usd", 0)),
        ])
    md_table(headers, rows, aligns)


# ============================================================
# TIER & MATRIX ANALYSIS TABLES
# ============================================================

def print_tier_summary(results: list[dict]):
    """Print outcomes aggregated by treatment tier."""
    if not results:
        return

    by_tier: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        tier = classify_run(r)["tier"]
        by_tier[tier].append(r)

    print()
    print("### Outcomes by Treatment Tier")
    print()
    headers = ["Tier", "Treatments", "Runs", "Pass%", "Tamper%", "Avg Tokens", "Avg Turns", "Avg Cost"]
    aligns = ["l", "r", "r", "r", "r", "r", "r", "r"]
    rows = []
    for tier_key in TIER_ORDER:
        runs = by_tier.get(tier_key, [])
        if not runs:
            continue
        n = len(runs)
        treatments = len(set(r["treatment"] for r in runs))
        pass_rate = sum(1 for r in runs if r.get("acceptance_pass")) / n * 100
        tamper_pct = sum(1 for r in runs if r.get("regression_tests_modified")) / n * 100
        avg_tokens = sum(r.get("tokens_total", 0) for r in runs) / n
        avg_turns = sum(r.get("api_turns", 0) for r in runs) / n
        avg_cost = sum(r.get("budget_used_usd", 0) for r in runs) / n

        rows.append([
            TIER_LABELS.get(tier_key, tier_key),
            str(treatments),
            str(n),
            f"{pass_rate:.0f}%",
            f"{tamper_pct:.0f}%",
            fmt_tokens(int(avg_tokens)),
            f"{avg_turns:.1f}",
            fmt_cost(avg_cost),
        ])

    # Catch any tiers not in TIER_ORDER
    for tier_key in sorted(by_tier.keys()):
        if tier_key not in TIER_ORDER:
            runs = by_tier[tier_key]
            n = len(runs)
            treatments = len(set(r["treatment"] for r in runs))
            n_, pass_pct, avg_tok, avg_cost, avg_turns, tamper_pct = _bucket_stats(runs)
            rows.append([tier_key, str(treatments), str(n), pass_pct, tamper_pct, avg_tok, avg_turns, avg_cost])

    md_table(headers, rows, aligns)


def print_tier_efficiency(results: list[dict]):
    """Print efficiency (successful runs only) aggregated by tier."""
    if not results:
        return

    by_tier: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        tier = classify_run(r)["tier"]
        by_tier[tier].append(r)

    print()
    print("### Efficiency by Tier (successful runs only)")
    print()
    headers = ["Tier", "Successes", "Total Runs", "Success%", "Tokens/Success", "Cost/Success"]
    aligns = ["l", "r", "r", "r", "r", "r"]
    rows = []
    for tier_key in TIER_ORDER:
        runs = by_tier.get(tier_key, [])
        if not runs:
            continue
        successes = [r for r in runs if r.get("acceptance_pass") and r.get("regression_pass")]
        ns = len(successes)
        nt = len(runs)
        if ns == 0:
            rows.append([TIER_LABELS.get(tier_key, tier_key), "0", str(nt), "0%", "N/A", "N/A"])
            continue
        avg_tokens = sum(r.get("tokens_total", 0) for r in successes) / ns
        avg_cost = sum(r.get("budget_used_usd", 0) for r in successes) / ns
        rows.append([
            TIER_LABELS.get(tier_key, tier_key),
            str(ns),
            str(nt),
            fmt_pct(ns, nt),
            fmt_tokens(int(avg_tokens)),
            fmt_cost(avg_cost),
        ])
    md_table(headers, rows, aligns)


def print_task_x_treatment_matrix(results: list[dict]):
    """Print a task × treatment pass/fail matrix."""
    if not results:
        return

    # Collect unique tasks and treatments present in results
    tasks = sorted(set(r["task"] for r in results))
    treatments = sorted(set(r["treatment"] for r in results))

    if len(tasks) < 2 or len(treatments) < 2:
        return

    # Build lookup: (task, treatment) -> list of pass booleans (multiple trials)
    grid: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for r in results:
        grid[(r["task"], r["treatment"])].append(bool(r.get("acceptance_pass")))

    print()
    print("### Task × Treatment Pass Matrix")
    print()

    # Abbreviate treatment names for column headers
    def abbrev(name: str) -> str:
        if len(name) <= 12:
            return name
        # Remove common prefixes/suffixes for brevity
        short = name.replace("bdd-", "b-").replace("whw-plus-", "whw+")
        short = short.replace("pre-prompt-", "pp-").replace("-context", "-ctx")
        if len(short) <= 12:
            return short
        return short[:11] + "…"

    headers = ["Task"] + [abbrev(t) for t in treatments]
    aligns = ["l"] + ["c"] * len(treatments)
    rows = []
    for task in tasks:
        row = [task]
        for treatment in treatments:
            passes = grid.get((task, treatment), [])
            if not passes:
                row.append("-")
            elif len(passes) == 1:
                row.append("Y" if passes[0] else "N")
            else:
                # Multiple trials: show pass count
                p = sum(passes)
                row.append(f"{p}/{len(passes)}")
        rows.append(row)

    # Add pass-rate footer row
    footer = ["**Pass%**"]
    for treatment in treatments:
        t_runs = [r for r in results if r["treatment"] == treatment]
        if t_runs:
            pct = sum(1 for r in t_runs if r.get("acceptance_pass")) / len(t_runs) * 100
            footer.append(f"{pct:.0f}%")
        else:
            footer.append("-")
    rows.append(footer)

    md_table(headers, rows, aligns)


def print_task_difficulty(results: list[dict]):
    """Print task difficulty ranking based on cross-treatment pass rates."""
    if not results:
        return

    by_task = defaultdict(list)
    for r in results:
        by_task[r["task"]].append(r)

    if len(by_task) < 2:
        return

    print()
    print("### Task Difficulty Ranking")
    print()
    headers = ["Task", "Runs", "Pass%", "Tamper%", "Avg Tokens", "Avg Cost", "Best Treatment", "Worst Treatment"]
    aligns = ["l", "r", "r", "r", "r", "r", "l", "l"]
    rows = []

    # Sort by pass rate ascending (hardest first)
    ranked = sorted(by_task.items(), key=lambda kv: sum(1 for r in kv[1] if r.get("acceptance_pass")) / len(kv[1]))

    for task, runs in ranked:
        n = len(runs)
        pass_rate = sum(1 for r in runs if r.get("acceptance_pass")) / n * 100
        tamper_pct = sum(1 for r in runs if r.get("regression_tests_modified")) / n * 100
        avg_tokens = sum(r.get("tokens_total", 0) for r in runs) / n
        avg_cost = sum(r.get("budget_used_usd", 0) for r in runs) / n

        # Find best/worst treatment for this task
        by_treatment = defaultdict(list)
        for r in runs:
            by_treatment[r["treatment"]].append(r)

        best = max(by_treatment.items(),
                   key=lambda kv: sum(1 for r in kv[1] if r.get("acceptance_pass")) / len(kv[1]))
        worst = min(by_treatment.items(),
                    key=lambda kv: sum(1 for r in kv[1] if r.get("acceptance_pass")) / len(kv[1]))

        best_pct = sum(1 for r in best[1] if r.get("acceptance_pass")) / len(best[1]) * 100
        worst_pct = sum(1 for r in worst[1] if r.get("acceptance_pass")) / len(worst[1]) * 100

        rows.append([
            task,
            str(n),
            f"{pass_rate:.0f}%",
            f"{tamper_pct:.0f}%",
            fmt_tokens(int(avg_tokens)),
            fmt_cost(avg_cost),
            f"{best[0]} ({best_pct:.0f}%)",
            f"{worst[0]} ({worst_pct:.0f}%)",
        ])

    md_table(headers, rows, aligns)


# ============================================================
# SEQUENCE ANALYSIS TABLES
# ============================================================

def print_sequence_treatment_summary(seq_results: list[dict]):
    """Print sequence results aggregated by treatment (mirrors Summary by Treatment)."""
    if not seq_results:
        return

    by_treatment = defaultdict(list)
    for r in seq_results:
        by_treatment[r["treatment"]].append(r)

    print()
    print("### Sequence Summary by Treatment")
    print()
    headers = ["Treatment", "Runs", "All Pass%", "Avg Steps", "Avg Regressions", "Avg Tokens", "Avg Time", "Avg Cost"]
    aligns = ["l", "r", "r", "r", "r", "r", "r", "r"]
    rows = []
    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        n = len(runs)
        all_pass = sum(1 for r in runs if r.get("aggregate", {}).get("all_steps_pass")) / n * 100
        avg_steps = sum(r.get("num_steps", 0) for r in runs) / n
        avg_regr = sum(r.get("aggregate", {}).get("prior_step_regressions", 0) for r in runs) / n
        avg_tokens = sum(r.get("aggregate", {}).get("total_tokens", 0) for r in runs) / n
        avg_time = sum(r.get("aggregate", {}).get("total_wall_time_seconds", 0) for r in runs) / n
        avg_cost = sum(r.get("aggregate", {}).get("total_budget_used_usd", 0) for r in runs) / n

        rows.append([
            treatment,
            str(n),
            f"{all_pass:.0f}%",
            f"{avg_steps:.1f}",
            f"{avg_regr:.1f}",
            fmt_tokens(int(avg_tokens)),
            f"{avg_time:.0f}s",
            fmt_cost(avg_cost),
        ])
    md_table(headers, rows, aligns)


def print_sequence_summary(seq_results: list[dict]):
    """Print summary table of sequence × treatment results."""
    if not seq_results:
        return

    print()
    print("## Sequence Results")
    print()
    print("### Sequence Summary")
    print()
    headers = [
        "Sequence", "Treatment", "Steps",
        "All Pass", "Cumul Pass", "Passed", "Failed",
        "Tokens", "Time", "Cost", "Regressions",
    ]
    aligns = ["l", "l", "r", "c", "c", "r", "r", "r", "r", "r", "r"]
    rows = []
    for r in seq_results:
        agg = r.get("aggregate", {})
        rows.append([
            r["sequence"],
            r["treatment"],
            str(r["num_steps"]),
            fmt_bool(agg.get("all_steps_pass", False)),
            fmt_bool(agg.get("cumulative_pass_at_every_step", False)),
            str(agg.get("steps_passed", 0)),
            str(agg.get("steps_failed", 0)),
            fmt_tokens(agg.get("total_tokens", 0)),
            f"{agg.get('total_wall_time_seconds', 0)}s",
            fmt_cost(agg.get("total_budget_used_usd", 0)),
            str(agg.get("prior_step_regressions", 0)),
        ])
    md_table(headers, rows, aligns)


def print_sequence_step_detail(seq_results: list[dict]):
    """Print per-step breakdown within each sequence run."""
    if not seq_results:
        return

    print()
    print("### Sequence Step Detail")
    print()
    headers = [
        "Sequence", "Treatment", "Step", "Task",
        "Accept", "Regress", "Prior OK", "Cumul",
        "Tokens", "Time", "Cost",
    ]
    aligns = ["l", "l", "r", "l", "c", "c", "c", "c", "r", "r", "r"]
    rows = []
    for r in seq_results:
        for step in r.get("steps", []):
            rows.append([
                r["sequence"],
                r["treatment"],
                str(step["step"]),
                step["task"],
                fmt_bool(step.get("acceptance_pass", False)),
                fmt_bool(step.get("regression_pass", False)),
                f"{step.get('prior_steps_passed', 0)}/{step.get('prior_steps_passed', 0) + step.get('prior_steps_failed', 0)}",
                fmt_bool(step.get("cumulative_pass", False)),
                fmt_tokens(step.get("tokens_total", 0)),
                f"{step.get('wall_time_seconds', 0)}s",
                fmt_cost(step.get("budget_used_usd", 0)),
            ])
    md_table(headers, rows, aligns)


# ============================================================
# CSV Export
# ============================================================

def export_csv(results: list[dict], output_path: Path):
    """Export results as CSV with classification columns."""
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

    # Computed classification columns
    computed = ["bdd_engagement", "bdd_hook_variant", "bdd_context_volume",
                "bdd_tier", "has_agents", "has_skills"]

    with open(output_path, "w") as f:
        f.write(",".join(fields + computed) + "\n")
        for r in results:
            c = classify_run(r)
            row = [str(r.get(field, "")) for field in fields]
            row.append(c["engagement"])
            row.append(c["hook_variant"])
            row.append(str(c["context_volume"]))
            row.append(c["tier"])
            row.append(str(c["has_agents"]))
            row.append(str(c["has_skills"]))
            f.write(",".join(row) + "\n")

    print(f"\nCSV exported to: {output_path}")


# ============================================================
# Main
# ============================================================

def parse_args(argv: list[str]) -> dict:
    """Parse CLI arguments."""
    opts = {"csv": False, "since": ""}
    i = 0
    while i < len(argv):
        if argv[i] == "--csv":
            opts["csv"] = True
            i += 1
        elif argv[i] == "--since" and i + 1 < len(argv):
            opts["since"] = argv[i + 1]
            i += 2
        else:
            print(f"Usage: analyze.py [--since TIMESTAMP] [--csv]")
            print(f"  --since  Only include results at or after TIMESTAMP (e.g. 20260217T170000Z)")
            print(f"  --csv    Export results to CSV")
            sys.exit(2)
    return opts


def main():
    bench_dir = Path(__file__).parent
    results_dir = bench_dir / "results"

    if not results_dir.exists():
        print(f"Results directory not found: {results_dir}")
        sys.exit(1)

    opts = parse_args(sys.argv[1:])
    since = opts["since"]

    results, num_rate_limited = load_results(results_dir, since=since)
    seq_results = load_sequence_results(results_dir, since=since)

    if not results and not seq_results:
        print("No results found. Run some benchmarks first:")
        print("  ./bench/run.sh --task 001-add-search --treatment baseline")
        sys.exit(0)

    total = len(results) + len(seq_results)
    rl_note = f", {num_rate_limited} rate-limited excluded" if num_rate_limited else ""
    since_note = f", since {since}" if since else ""
    print(f"Loaded {total} result(s) from {results_dir} ({len(results)} task, {len(seq_results)} sequence{rl_note}{since_note})\n")

    if results:
        # --- Compact summaries first ---
        print_summary_table(results)
        if seq_results:
            print_sequence_treatment_summary(seq_results)
        print_task_summary(results)
        print_tier_summary(results)
        print_task_x_treatment_matrix(results)
        print_task_difficulty(results)

        # --- Efficiency & integrity ---
        print_efficiency_table(results)
        print_tier_efficiency(results)
        print_integrity_table(results)

        # --- BDD engagement ---
        print_engagement_table(results)
        print_engagement_vs_outcomes(results)
        print_hook_effectiveness(results)
        print_hook_variant_comparison(results)
        print_mcp_tool_patterns(results)
        print_agent_outcomes(results)
        print_context_volume_analysis(results)
        print_context_vs_pass_scatter(results)

        # --- Detailed / long tables ---
        print_reliability_table(results)
        print_treatment_features(results)
        print_bdd_diagnosis(results)
        print_detail_table(results)

    # --- Sequence tables ---
    if seq_results:
        print_sequence_summary(seq_results)
        print_sequence_step_detail(seq_results)

    # Export CSV if requested
    if opts["csv"]:
        csv_path = results_dir / "results.csv"
        export_csv(results, csv_path)


if __name__ == "__main__":
    main()
