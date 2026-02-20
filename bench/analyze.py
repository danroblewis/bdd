#!/usr/bin/env python3
"""Analyze bench results and produce comparison tables."""

import json
import re
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


def enrich_results(results: list[dict]) -> list[dict]:
    """Add computed classification fields to each result dict (mutates in place)."""
    for r in results:
        c = classify_run(r)
        r["_tier"] = c["tier"]
        r["_tier_label"] = TIER_LABELS.get(c["tier"], c["tier"])
        r["_engagement"] = c["engagement"]
        r["_hook_variant"] = c["hook_variant"]
        r["_context_volume"] = c["context_volume"]
        r["_engagement_tag"] = engagement_tag(r)
        r["_has_hooks"] = c["has_hooks"]
        r["_has_mcp"] = c["has_mcp"]
        r["_has_agents"] = c["has_agents"]
        r["_has_skills"] = c["has_skills"]
    return results


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
    headers = ["Treatment", "Runs", "Pass%", "Avg Quality", "MCP Calls", "bdd_test", "Hooks", "Injected", "Failed", "Uniq Facets", "Edits"]
    aligns = ["l", "r", "r", "r", "r", "r", "r", "r", "r", "r", "r"]
    rows = []
    for treatment in sorted(by_treatment.keys()):
        runs = by_treatment[treatment]
        n = len(runs)
        pass_rate = sum(1 for r in runs if r.get("acceptance_pass")) / n * 100
        avg_quality = sum(r.get("_quality_score", 0) or 0 for r in runs) / n
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
            f"{pass_rate:.0f}%",
            f"{avg_quality:.1f}",
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
# HTML Report
# ============================================================

def generate_html_report(results: list[dict], seq_results: list[dict],
                         output_path: Path, since: str = "", num_rate_limited: int = 0):
    """Generate self-contained interactive HTML report."""
    import datetime

    data = {
        "results": results,
        "sequences": seq_results,
        "meta": {
            "generated": datetime.datetime.now().isoformat(),
            "since": since,
            "num_rate_limited": num_rate_limited,
            "total_results": len(results),
            "total_sequences": len(seq_results),
        },
        "constants": {
            "TIER_ORDER": TIER_ORDER,
            "TIER_LABELS": TIER_LABELS,
            "HOOK_VARIANTS": HOOK_VARIANTS,
            "HOOKS_NO_MCP_TREATMENTS": list(HOOKS_NO_MCP_TREATMENTS),
            "AGENT_TREATMENTS": list(AGENT_TREATMENTS),
        },
    }

    data_json = json.dumps(data, default=str)

    html = HTML_TEMPLATE.replace("/*DATA_PLACEHOLDER*/", data_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)
    print(f"HTML report written to: {output_path}")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BDD Bench Report</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  background:#f8f9fa;color:#212529;font-size:13px;line-height:1.4}
.top-bar{background:#fff;border-bottom:1px solid #dee2e6;padding:8px 16px;position:sticky;top:0;z-index:100}
.top-bar h1{font-size:16px;margin-bottom:4px}
.filters{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.filters label{font-size:11px;color:#6c757d;margin-right:2px}
.filters input{font-size:12px;padding:2px 6px;border:1px solid #ced4da;border-radius:3px;width:140px}
.filters input.invalid{border-color:#dc3545}
.filters .stats{margin-left:auto;font-size:11px;color:#6c757d}
.tab-bar{display:flex;gap:0;background:#fff;border-bottom:2px solid #dee2e6;padding:0 16px;overflow-x:auto}
.tab-bar button{background:none;border:none;padding:8px 14px;font-size:12px;cursor:pointer;
  border-bottom:2px solid transparent;margin-bottom:-2px;white-space:nowrap;color:#495057}
.tab-bar button:hover{color:#0d6efd}
.tab-bar button.active{color:#0d6efd;border-bottom-color:#0d6efd;font-weight:600}
.tab-content{display:none;padding:16px}
.tab-content.active{display:block}
.tab-content h3{font-size:14px;margin:16px 0 6px;color:#343a40}
.tab-content h3:first-child{margin-top:0}
.tab-content p.note{font-size:11px;color:#6c757d;margin-bottom:6px}
.scroll-wrap{overflow-x:auto;margin-bottom:16px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{padding:4px 8px;border:1px solid #dee2e6;text-align:left;white-space:nowrap}
th{background:#f1f3f5;position:sticky;top:0;cursor:pointer;user-select:none;font-weight:600}
th:hover{background:#e2e6ea}
th .sort-arrow{font-size:9px;margin-left:2px;color:#adb5bd}
th.sorted-asc .sort-arrow::after{content:" \25B2";color:#0d6efd}
th.sorted-desc .sort-arrow::after{content:" \25BC";color:#0d6efd}
tr:nth-child(even) td{background:#f8f9fa}
tr:hover td{background:#e9ecef}
td.pass-high{background:#d4edda !important;color:#155724}
td.pass-mid{background:#fff3cd !important;color:#856404}
td.pass-low{background:#f8d7da !important;color:#721c24}
td.r{text-align:right}
td.c{text-align:center}
.diag-section{margin-bottom:12px}
.diag-section strong{font-size:12px}
.diag-section ul{margin:4px 0 4px 20px;font-size:12px}
.diag-section .metric{font-size:12px;margin:2px 0}
.chart-wrap{margin-bottom:20px;overflow-x:auto}
.chart-wrap svg{display:block}
.chart-legend{display:flex;gap:16px;margin:6px 0 4px;font-size:11px;color:#495057}
.chart-legend span{display:inline-flex;align-items:center;gap:4px}
.chart-legend .swatch{display:inline-block;width:12px;height:12px;border-radius:2px}
</style>
</head>
<body>
<div class="top-bar">
  <h1>BDD Bench Report</h1>
  <div class="filters">
    <label>Subject:</label><input id="f-subject" placeholder="regex">
    <label>Treatment:</label><input id="f-treatment" placeholder="regex">
    <label>Task:</label><input id="f-task" placeholder="regex">
    <label>From:</label><input id="f-start" type="datetime-local">
    <label>To:</label><input id="f-end" type="datetime-local">
    <span class="stats" id="stats-bar"></span>
  </div>
</div>
<div class="tab-bar" id="tab-bar">
  <button data-tab="summary" class="active">Summary</button>
  <button data-tab="matrix">Matrix</button>
  <button data-tab="efficiency">Efficiency</button>
  <button data-tab="bdd">BDD Analysis</button>
  <button data-tab="context">Context</button>
  <button data-tab="diagnostics">Diagnostics</button>
  <button data-tab="detail">Detail</button>
  <button data-tab="quality">Quality</button>
  <button data-tab="sequences">Sequences</button>
</div>
<div id="tab-summary" class="tab-content active"></div>
<div id="tab-matrix" class="tab-content"></div>
<div id="tab-efficiency" class="tab-content"></div>
<div id="tab-bdd" class="tab-content"></div>
<div id="tab-context" class="tab-content"></div>
<div id="tab-diagnostics" class="tab-content"></div>
<div id="tab-detail" class="tab-content"></div>
<div id="tab-quality" class="tab-content"></div>
<div id="tab-sequences" class="tab-content"></div>

<script>
// === Data ===
var DATA = /*DATA_PLACEHOLDER*/;

// === State ===
var state = {
  activeTab: 'summary',
  dirty: {},
  filtered: null,
  filteredSeq: null
};

// === Utilities ===
function groupBy(arr, keyFn) {
  var m = {};
  for (var i = 0; i < arr.length; i++) {
    var k = keyFn(arr[i]);
    if (!m[k]) m[k] = [];
    m[k].push(arr[i]);
  }
  return m;
}
function sortedKeys(obj) { return Object.keys(obj).sort(); }
function sum(arr, fn) { var s = 0; for (var i = 0; i < arr.length; i++) s += fn(arr[i]); return s; }
function count(arr, fn) { var c = 0; for (var i = 0; i < arr.length; i++) if (fn(arr[i])) c++; return c; }
function fmtPct(n, total) { return total === 0 ? '-' : Math.round(n / total * 100) + '%'; }
function fmtTokens(n) { return n >= 1000 ? Math.round(n / 1000) + 'k' : String(n); }
function fmtCost(c) { return '$' + c.toFixed(2); }
function fmtBool(b) { return b ? 'YES' : 'NO'; }
function fmtDelta(d) { return d > 0 ? '+' + d : String(d); }
function fmtFloat(v, d) { return v.toFixed(d === undefined ? 1 : d); }
function avg(arr, fn) { return arr.length === 0 ? 0 : sum(arr, fn) / arr.length; }
function passClass(pctStr) {
  var v = parseInt(pctStr);
  if (isNaN(v)) return '';
  if (v >= 90) return 'pass-high';
  if (v >= 40) return 'pass-mid';
  return 'pass-low';
}

// === Chart helpers ===
function pctColor(pct) {
  var hue = Math.round(Math.min(100, Math.max(0, pct)) * 1.2);
  return 'hsl(' + hue + ',70%,42%)';
}

function svgEl(tag, attrs) {
  var e = document.createElementNS('http://www.w3.org/2000/svg', tag);
  if (attrs) Object.keys(attrs).forEach(function(k) { e.setAttribute(k, attrs[k]); });
  return e;
}

function renderBarChart(container, data, opts) {
  // data: [{label, value, color?}]
  // opts: {suffix, maxValue, decimals, colorFn, width}
  opts = opts || {};
  if (!data.length) return;
  var suffix = opts.suffix || '';
  var dec = opts.decimals != null ? opts.decimals : 0;
  var maxVal = opts.maxValue || Math.max.apply(null, data.map(function(d){return d.value})) || 1;
  var W = opts.width || 660;
  var barH = 22, gap = 4, labelW = 150, valueW = 60, chartW = W - labelW - valueW - 10;
  var H = data.length * (barH + gap) + gap;

  var div = document.createElement('div'); div.className = 'chart-wrap';
  var svg = svgEl('svg', {width: W, viewBox: '0 0 ' + W + ' ' + H});
  svg.style.maxWidth = W + 'px';

  data.forEach(function(d, i) {
    var y = gap + i * (barH + gap);
    var barW = Math.max(0, (d.value / maxVal) * chartW);
    var color = d.color || (opts.colorFn ? opts.colorFn(d.value) : pctColor(d.value));

    var label = svgEl('text', {x: labelW - 6, y: y + barH / 2 + 4, 'text-anchor': 'end',
      'font-size': '11', fill: '#495057', 'font-family': 'inherit'});
    label.textContent = d.label.length > 20 ? d.label.substring(0, 19) + '\u2026' : d.label;
    svg.appendChild(label);

    svg.appendChild(svgEl('rect', {x: labelW, y: y, width: chartW, height: barH, fill: '#f1f3f5', rx: 3}));
    if (barW > 0) svg.appendChild(svgEl('rect', {x: labelW, y: y, width: barW, height: barH, fill: color, rx: 3}));

    var val = svgEl('text', {x: labelW + chartW + 8, y: y + barH / 2 + 4,
      'font-size': '11', 'font-weight': '600', fill: '#212529', 'font-family': 'inherit'});
    val.textContent = d.value.toFixed(dec) + suffix;
    svg.appendChild(val);
  });

  div.appendChild(svg);
  container.appendChild(div);
}

function renderGroupedBarChart(container, data, opts) {
  // data: [{label, values: [{value, color, legendLabel}]}]
  // opts: {suffix, maxValue, decimals, width, legend: [{label, color}]}
  opts = opts || {};
  if (!data.length) return;
  var suffix = opts.suffix || '';
  var dec = opts.decimals != null ? opts.decimals : 0;
  var nGroups = data[0].values.length;
  var allVals = []; data.forEach(function(d) { d.values.forEach(function(v) { allVals.push(v.value); }); });
  var maxVal = opts.maxValue || Math.max.apply(null, allVals) || 1;
  var W = opts.width || 660;
  var subH = 16, subGap = 2, groupGap = 6, labelW = 150, valueW = 60;
  var chartW = W - labelW - valueW - 10;
  var groupH = nGroups * (subH + subGap) - subGap;
  var H = data.length * (groupH + groupGap) + groupGap;

  var div = document.createElement('div'); div.className = 'chart-wrap';

  // Legend
  if (opts.legend) {
    var leg = document.createElement('div'); leg.className = 'chart-legend';
    opts.legend.forEach(function(l) {
      var sp = document.createElement('span');
      var sw = document.createElement('span'); sw.className = 'swatch'; sw.style.background = l.color;
      sp.appendChild(sw); sp.appendChild(document.createTextNode(l.label));
      leg.appendChild(sp);
    });
    div.appendChild(leg);
  }

  var svg = svgEl('svg', {width: W, viewBox: '0 0 ' + W + ' ' + H});
  svg.style.maxWidth = W + 'px';

  data.forEach(function(d, i) {
    var gy = groupGap + i * (groupH + groupGap);

    var label = svgEl('text', {x: labelW - 6, y: gy + groupH / 2 + 4, 'text-anchor': 'end',
      'font-size': '11', fill: '#495057', 'font-family': 'inherit'});
    label.textContent = d.label.length > 20 ? d.label.substring(0, 19) + '\u2026' : d.label;
    svg.appendChild(label);

    d.values.forEach(function(v, j) {
      var y = gy + j * (subH + subGap);
      var barW = Math.max(0, (v.value / maxVal) * chartW);

      svg.appendChild(svgEl('rect', {x: labelW, y: y, width: chartW, height: subH, fill: '#f1f3f5', rx: 2}));
      if (barW > 0) svg.appendChild(svgEl('rect', {x: labelW, y: y, width: barW, height: subH, fill: v.color, rx: 2}));

      var val = svgEl('text', {x: labelW + chartW + 8, y: y + subH / 2 + 4,
        'font-size': '10', fill: '#495057', 'font-family': 'inherit'});
      val.textContent = v.value.toFixed(dec) + suffix;
      svg.appendChild(val);
    });
  });

  div.appendChild(svg);
  container.appendChild(div);
}

function renderScatterPlot(container, data, opts) {
  // data: [{x, y, label?, color?}]
  // opts: {xLabel, yLabel, xSuffix, ySuffix, xMax, yMax, width, height, title, colorFn}
  opts = opts || {};
  if (!data.length) return;
  var W = opts.width || 560, H = opts.height || 340;
  var pad = {top: 30, right: 20, bottom: 45, left: 55};
  var cW = W - pad.left - pad.right, cH = H - pad.top - pad.bottom;
  var xSuf = opts.xSuffix || '', ySuf = opts.ySuffix || '';
  var xMax = opts.xMax != null ? opts.xMax : Math.max.apply(null, data.map(function(d){return d.x})) || 1;
  var yMax = opts.yMax != null ? opts.yMax : Math.max.apply(null, data.map(function(d){return d.y})) || 1;
  // Add 10% headroom
  if (opts.xMax == null) xMax = xMax * 1.1 || 1;
  if (opts.yMax == null) yMax = yMax * 1.1 || 1;

  var div = document.createElement('div'); div.className = 'chart-wrap';
  var svg = svgEl('svg', {width: W, viewBox: '0 0 ' + W + ' ' + H});
  svg.style.maxWidth = W + 'px';

  // Grid lines
  for (var gi = 0; gi <= 4; gi++) {
    var gy = pad.top + cH - (gi / 4) * cH;
    svg.appendChild(svgEl('line', {x1: pad.left, y1: gy, x2: pad.left + cW, y2: gy,
      stroke: '#e9ecef', 'stroke-width': 1}));
    var yt = svgEl('text', {x: pad.left - 8, y: gy + 4, 'text-anchor': 'end',
      'font-size': '10', fill: '#868e96', 'font-family': 'inherit'});
    yt.textContent = (yMax * gi / 4).toFixed(ySuf === '%' ? 0 : 1) + ySuf;
    svg.appendChild(yt);
  }
  for (var gj = 0; gj <= 4; gj++) {
    var gx = pad.left + (gj / 4) * cW;
    svg.appendChild(svgEl('line', {x1: gx, y1: pad.top, x2: gx, y2: pad.top + cH,
      stroke: '#e9ecef', 'stroke-width': 1}));
    var xt = svgEl('text', {x: gx, y: pad.top + cH + 16, 'text-anchor': 'middle',
      'font-size': '10', fill: '#868e96', 'font-family': 'inherit'});
    xt.textContent = (xMax * gj / 4).toFixed(xSuf === '%' ? 0 : 1) + xSuf;
    svg.appendChild(xt);
  }

  // Axes
  svg.appendChild(svgEl('line', {x1: pad.left, y1: pad.top, x2: pad.left, y2: pad.top + cH,
    stroke: '#adb5bd', 'stroke-width': 1}));
  svg.appendChild(svgEl('line', {x1: pad.left, y1: pad.top + cH, x2: pad.left + cW, y2: pad.top + cH,
    stroke: '#adb5bd', 'stroke-width': 1}));

  // Axis labels
  if (opts.xLabel) {
    var xl = svgEl('text', {x: pad.left + cW / 2, y: H - 4, 'text-anchor': 'middle',
      'font-size': '11', fill: '#495057', 'font-family': 'inherit'});
    xl.textContent = opts.xLabel;
    svg.appendChild(xl);
  }
  if (opts.yLabel) {
    var yl = svgEl('text', {x: 14, y: pad.top + cH / 2, 'text-anchor': 'middle',
      'font-size': '11', fill: '#495057', 'font-family': 'inherit',
      transform: 'rotate(-90,' + 14 + ',' + (pad.top + cH / 2) + ')'});
    yl.textContent = opts.yLabel;
    svg.appendChild(yl);
  }

  // Trend line (linear regression)
  if (data.length >= 3) {
    var n = data.length;
    var sx = 0, sy = 0, sxy = 0, sx2 = 0;
    data.forEach(function(d) { sx += d.x; sy += d.y; sxy += d.x * d.y; sx2 += d.x * d.x; });
    var denom = n * sx2 - sx * sx;
    if (Math.abs(denom) > 0.001) {
      var slope = (n * sxy - sx * sy) / denom;
      var intercept = (sy - slope * sx) / n;
      var x0 = 0, x1 = xMax;
      var ty0 = intercept, ty1 = slope * xMax + intercept;
      // Clamp to chart bounds
      ty0 = Math.max(0, Math.min(yMax, ty0));
      ty1 = Math.max(0, Math.min(yMax, ty1));
      var lx0 = pad.left + (x0 / xMax) * cW;
      var ly0 = pad.top + cH - (ty0 / yMax) * cH;
      var lx1 = pad.left + (x1 / xMax) * cW;
      var ly1 = pad.top + cH - (ty1 / yMax) * cH;
      svg.appendChild(svgEl('line', {x1: lx0, y1: ly0, x2: lx1, y2: ly1,
        stroke: '#dee2e6', 'stroke-width': 1.5, 'stroke-dasharray': '6,4'}));
    }
  }

  // Points
  data.forEach(function(d) {
    var cx = pad.left + (Math.min(d.x, xMax) / xMax) * cW;
    var cy = pad.top + cH - (Math.min(d.y, yMax) / yMax) * cH;
    var color = d.color || (opts.colorFn ? opts.colorFn(d.y) : '#0d6efd');
    svg.appendChild(svgEl('circle', {cx: cx, cy: cy, r: 5, fill: color, opacity: 0.75,
      stroke: '#fff', 'stroke-width': 1.5}));
    if (d.label) {
      var lt = svgEl('text', {x: cx + 7, y: cy + 3, 'font-size': '9', fill: '#868e96', 'font-family': 'inherit'});
      lt.textContent = d.label.length > 15 ? d.label.substring(0, 14) + '\u2026' : d.label;
      svg.appendChild(lt);
    }
  });

  div.appendChild(svg);
  container.appendChild(div);
}

// === Generic table renderer ===
function renderTable(container, headers, rows, aligns, opts) {
  opts = opts || {};
  var wrap = document.createElement('div');
  wrap.className = 'scroll-wrap';
  var table = document.createElement('table');
  var thead = document.createElement('thead');
  var hr = document.createElement('tr');
  for (var i = 0; i < headers.length; i++) {
    var th = document.createElement('th');
    th.textContent = headers[i];
    var sp = document.createElement('span');
    sp.className = 'sort-arrow';
    th.appendChild(sp);
    th.dataset.col = i;
    th.addEventListener('click', (function(tbl, ci, als) {
      return function() {
        sortTable(tbl, ci, als);
      };
    })(table, i, aligns));
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  var tbody = document.createElement('tbody');
  for (var r = 0; r < rows.length; r++) {
    var tr = document.createElement('tr');
    for (var c = 0; c < rows[r].length; c++) {
      var td = document.createElement('td');
      var val = rows[r][c];
      td.textContent = val;
      var al = aligns && aligns[c] ? aligns[c] : 'l';
      if (al === 'r') td.className = 'r';
      else if (al === 'c') td.className = 'c';
      // Color pass% cells
      if (headers[c] && /pass%|pass|success%/i.test(headers[c]) && typeof val === 'string' && val.endsWith('%')) {
        var pc = passClass(val);
        if (pc) td.classList.add(pc);
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  container.appendChild(wrap);
}

function sortTable(table, colIdx, aligns) {
  var thead = table.querySelector('thead');
  var ths = thead.querySelectorAll('th');
  var curr = ths[colIdx].classList.contains('sorted-asc') ? 'asc' : ths[colIdx].classList.contains('sorted-desc') ? 'desc' : '';
  for (var i = 0; i < ths.length; i++) { ths[i].classList.remove('sorted-asc', 'sorted-desc'); }
  var dir = curr === 'asc' ? 'desc' : 'asc';
  ths[colIdx].classList.add('sorted-' + dir);
  var tbody = table.querySelector('tbody');
  var rows = Array.from(tbody.rows);
  rows.sort(function(a, b) {
    var av = a.cells[colIdx].textContent.trim();
    var bv = b.cells[colIdx].textContent.trim();
    // Try numeric
    var an = parseFloat(av.replace(/[%$,ks]/g, '')), bn = parseFloat(bv.replace(/[%$,ks]/g, ''));
    if (!isNaN(an) && !isNaN(bn)) return dir === 'asc' ? an - bn : bn - an;
    return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
  });
  for (var i = 0; i < rows.length; i++) tbody.appendChild(rows[i]);
}

// === Bucket stats (mirrors Python _bucket_stats) ===
function bucketStats(runs) {
  var n = runs.length;
  if (n === 0) return {n:0, passPct:'-', avgTokens:'-', avgCost:'-', avgTurns:'-', tamperPct:'-'};
  return {
    n: n,
    passPct: fmtPct(count(runs, function(r){return r.acceptance_pass}), n),
    avgTokens: fmtTokens(Math.round(avg(runs, function(r){return r.tokens_total||0}))),
    avgCost: fmtCost(avg(runs, function(r){return r.budget_used_usd||0})),
    avgTurns: fmtFloat(avg(runs, function(r){return r.api_turns||0})),
    tamperPct: fmtPct(count(runs, function(r){return r.regression_tests_modified}), n)
  };
}

// === Filtering ===
function tryRegex(pattern) {
  if (!pattern) return null;
  try { return new RegExp(pattern, 'i'); } catch(e) { return false; }
}
// Convert datetime-local value "2026-02-03T00:00" to compact "20260203T000000Z"
function toCompactTS(dtLocal) {
  if (!dtLocal) return '';
  return dtLocal.replace(/[-:]/g, '').replace(/T(\d{4})$/, 'T$100') + 'Z';
}

function getFilteredResults() {
  var sRe = tryRegex(document.getElementById('f-subject').value);
  var tRe = tryRegex(document.getElementById('f-treatment').value);
  var kRe = tryRegex(document.getElementById('f-task').value);
  var startVal = toCompactTS(document.getElementById('f-start').value);
  var endVal = toCompactTS(document.getElementById('f-end').value);

  // Mark invalid
  document.getElementById('f-subject').classList.toggle('invalid', sRe === false);
  document.getElementById('f-treatment').classList.toggle('invalid', tRe === false);
  document.getElementById('f-task').classList.toggle('invalid', kRe === false);

  var filtered = DATA.results.filter(function(r) {
    if (sRe && !sRe.test(r.subject || '')) return false;
    if (tRe && !tRe.test(r.treatment)) return false;
    if (kRe && !kRe.test(r.task)) return false;
    if (startVal && r.timestamp && r.timestamp < startVal) return false;
    if (endVal && r.timestamp && r.timestamp > endVal) return false;
    return true;
  });
  var filteredSeq = DATA.sequences.filter(function(r) {
    if (sRe && !sRe.test(r.subject || '')) return false;
    if (tRe && !tRe.test(r.treatment)) return false;
    if (kRe && !kRe.test(r.sequence)) return false;
    if (startVal && r.timestamp && r.timestamp < startVal) return false;
    if (endVal && r.timestamp && r.timestamp > endVal) return false;
    return true;
  });

  state.filtered = filtered;
  state.filteredSeq = filteredSeq;

  // Stats bar
  document.getElementById('stats-bar').textContent =
    'Showing ' + filtered.length + ' of ' + DATA.results.length + ' results' +
    (filteredSeq.length !== DATA.sequences.length ? ', ' + filteredSeq.length + ' of ' + DATA.sequences.length + ' sequences' : '') +
    (DATA.meta.num_rate_limited ? ' (' + DATA.meta.num_rate_limited + ' rate-limited excluded)' : '') +
    (DATA.meta.since ? ' since ' + DATA.meta.since : '');

  // Mark all tabs dirty
  var tabs = ['summary','matrix','efficiency','bdd','context','diagnostics','detail','quality','sequences'];
  for (var i = 0; i < tabs.length; i++) state.dirty[tabs[i]] = true;
  renderActiveTab();
}

// === Tab switching ===
function switchTab(tabName) {
  state.activeTab = tabName;
  var buttons = document.querySelectorAll('.tab-bar button');
  for (var i = 0; i < buttons.length; i++) {
    buttons[i].classList.toggle('active', buttons[i].dataset.tab === tabName);
  }
  var panes = document.querySelectorAll('.tab-content');
  for (var i = 0; i < panes.length; i++) {
    panes[i].classList.toggle('active', panes[i].id === 'tab-' + tabName);
  }
  if (state.dirty[tabName]) renderActiveTab();
}

function renderActiveTab() {
  var tab = state.activeTab;
  var el = document.getElementById('tab-' + tab);
  if (!el || !state.dirty[tab]) return;
  el.innerHTML = '';
  var results = state.filtered || [];
  var seqs = state.filteredSeq || [];

  switch(tab) {
    case 'summary': renderSummaryTab(el, results, seqs); break;
    case 'matrix': renderMatrixTab(el, results); break;
    case 'efficiency': renderEfficiencyTab(el, results); break;
    case 'bdd': renderBddTab(el, results); break;
    case 'context': renderContextTab(el, results); break;
    case 'diagnostics': renderDiagnosticsTab(el, results); break;
    case 'detail': renderDetailTab(el, results); break;
    case 'quality': renderQualityTab(el, results); break;
    case 'sequences': renderSequencesTab(el, seqs); break;
  }
  state.dirty[tab] = false;
}

// ============ TAB 1: Summary ============
function renderSummaryTab(el, results, seqs) {
  // Summary by Treatment
  var h = document.createElement('h3'); h.textContent = 'Summary by Treatment'; el.appendChild(h);
  var byT = groupBy(results, function(r){return r.treatment});
  var headers = ['Treatment','Runs','Pass%','Avg Qual','Avg Blks','Skip%','Tamper%','Avg Tokens','Avg Turns','Avg Time','Avg Cost'];
  var aligns = ['l','r','r','r','r','r','r','r','r','r','r'];
  var rows = [];
  sortedKeys(byT).forEach(function(t) {
    var runs = byT[t], n = runs.length;
    rows.push([t, n, fmtPct(count(runs,function(r){return r.acceptance_pass}),n),
      fmtFloat(avg(runs,function(r){return r._quality_score||0})),
      fmtFloat(avg(runs,function(r){return r.stop_blocks||0})),
      fmtPct(count(runs,function(r){return(r.regression_skipped||0)>0}),n),
      fmtPct(count(runs,function(r){return r.regression_tests_modified}),n),
      fmtTokens(Math.round(avg(runs,function(r){return r.tokens_total||0}))),
      fmtFloat(avg(runs,function(r){return r.api_turns||0})),
      Math.round(avg(runs,function(r){return r.wall_time_seconds||0}))+'s',
      fmtCost(avg(runs,function(r){return r.budget_used_usd||0}))]);
  });
  renderTable(el, headers, rows, aligns);

  // Sequence Summary by Treatment
  if (seqs.length > 0) {
    h = document.createElement('h3'); h.textContent = 'Sequence Summary by Treatment'; el.appendChild(h);
    var byTSeq = groupBy(seqs, function(r){return r.treatment});
    var sh = ['Treatment','Runs','All Pass%','Avg Steps','Avg Regressions','Avg Tokens','Avg Time','Avg Cost'];
    var sa = ['l','r','r','r','r','r','r','r'];
    var sr = [];
    sortedKeys(byTSeq).forEach(function(t) {
      var runs = byTSeq[t], n = runs.length;
      sr.push([t, n,
        fmtPct(count(runs,function(r){return r.aggregate&&r.aggregate.all_steps_pass}),n),
        fmtFloat(avg(runs,function(r){return r.num_steps||0})),
        fmtFloat(avg(runs,function(r){return(r.aggregate&&r.aggregate.prior_step_regressions)||0})),
        fmtTokens(Math.round(avg(runs,function(r){return(r.aggregate&&r.aggregate.total_tokens)||0}))),
        Math.round(avg(runs,function(r){return(r.aggregate&&r.aggregate.total_wall_time_seconds)||0}))+'s',
        fmtCost(avg(runs,function(r){return(r.aggregate&&r.aggregate.total_budget_used_usd)||0}))]);
    });
    renderTable(el, sh, sr, sa);
  }

  // Summary by Task
  h = document.createElement('h3'); h.textContent = 'Summary by Task'; el.appendChild(h);
  var byTask = groupBy(results, function(r){return r.task});
  headers = ['Task','Runs','Pass%','Avg Qual','Avg Tokens','Avg Turns','Avg Cost'];
  aligns = ['l','r','r','r','r','r','r'];
  rows = [];
  sortedKeys(byTask).forEach(function(t) {
    var runs = byTask[t], n = runs.length;
    rows.push([t, n, fmtPct(count(runs,function(r){return r.acceptance_pass}),n),
      fmtFloat(avg(runs,function(r){return r._quality_score||0})),
      fmtTokens(Math.round(avg(runs,function(r){return r.tokens_total||0}))),
      fmtFloat(avg(runs,function(r){return r.api_turns||0})),
      fmtCost(avg(runs,function(r){return r.budget_used_usd||0}))]);
  });
  renderTable(el, headers, rows, aligns);

  // Tier Summary
  h = document.createElement('h3'); h.textContent = 'Outcomes by Treatment Tier'; el.appendChild(h);
  var byTier = groupBy(results, function(r){return r._tier||'none'});
  headers = ['Tier','Treatments','Runs','Pass%','Avg Qual','Tamper%','Avg Tokens','Avg Turns','Avg Cost'];
  aligns = ['l','r','r','r','r','r','r','r','r'];
  rows = [];
  DATA.constants.TIER_ORDER.forEach(function(tk) {
    var runs = byTier[tk]; if (!runs||!runs.length) return;
    var n = runs.length, tSet = {};
    runs.forEach(function(r){tSet[r.treatment]=1});
    rows.push([DATA.constants.TIER_LABELS[tk]||tk, Object.keys(tSet).length, n,
      fmtPct(count(runs,function(r){return r.acceptance_pass}),n),
      fmtFloat(avg(runs,function(r){return r._quality_score||0})),
      fmtPct(count(runs,function(r){return r.regression_tests_modified}),n),
      fmtTokens(Math.round(avg(runs,function(r){return r.tokens_total||0}))),
      fmtFloat(avg(runs,function(r){return r.api_turns||0})),
      fmtCost(avg(runs,function(r){return r.budget_used_usd||0}))]);
  });
  renderTable(el, headers, rows, aligns);

  // Task Difficulty
  h = document.createElement('h3'); h.textContent = 'Task Difficulty Ranking'; el.appendChild(h);
  var tEntries = Object.keys(byTask).map(function(t) {
    var runs = byTask[t];
    return {task:t, runs:runs, passRate: count(runs,function(r){return r.acceptance_pass})/runs.length};
  }).sort(function(a,b){return a.passRate - b.passRate});
  headers = ['Task','Runs','Pass%','Avg Qual','Tamper%','Avg Tokens','Avg Cost','Best Treatment','Worst Treatment'];
  aligns = ['l','r','r','r','r','r','r','l','l'];
  rows = [];
  tEntries.forEach(function(e) {
    var runs = e.runs, n = runs.length;
    var byTr = groupBy(runs, function(r){return r.treatment});
    var trEntries = Object.keys(byTr).map(function(t){
      var rr=byTr[t]; return {name:t, pct:count(rr,function(r){return r.acceptance_pass})/rr.length};
    });
    var best = trEntries.reduce(function(a,b){return a.pct>=b.pct?a:b});
    var worst = trEntries.reduce(function(a,b){return a.pct<=b.pct?a:b});
    rows.push([e.task, n, fmtPct(count(runs,function(r){return r.acceptance_pass}),n),
      fmtFloat(avg(runs,function(r){return r._quality_score||0})),
      fmtPct(count(runs,function(r){return r.regression_tests_modified}),n),
      fmtTokens(Math.round(avg(runs,function(r){return r.tokens_total||0}))),
      fmtCost(avg(runs,function(r){return r.budget_used_usd||0})),
      best.name+' ('+Math.round(best.pct*100)+'%)',
      worst.name+' ('+Math.round(worst.pct*100)+'%)']);
  });
  if (tEntries.length >= 2) renderTable(el, headers, rows, aligns);
}

// ============ TAB 2: Matrix ============
function renderMatrixTab(el, results) {
  var h = document.createElement('h3'); h.textContent = 'Task \u00d7 Treatment Pass Matrix'; el.appendChild(h);
  var tasks = []; var treatments = []; var tSet={}, trSet={};
  results.forEach(function(r){tSet[r.task]=1;trSet[r.treatment]=1});
  tasks = Object.keys(tSet).sort(); treatments = Object.keys(trSet).sort();
  if (tasks.length < 2 || treatments.length < 2) { el.appendChild(document.createTextNode('Need 2+ tasks and treatments.')); return; }
  var grid = {};
  results.forEach(function(r) {
    var k = r.task+'|||'+r.treatment;
    if (!grid[k]) grid[k] = [];
    grid[k].push(!!r.acceptance_pass);
  });
  var headers = ['Task'].concat(treatments.map(function(t){return t.length<=12?t:t.replace('bdd-','b-').replace('whw-plus-','whw+').replace('pre-prompt-','pp-').replace('-context','-ctx').substring(0,12)}));
  var aligns = ['l'].concat(treatments.map(function(){return 'c'}));
  var rows = [];
  tasks.forEach(function(task) {
    var row = [task];
    treatments.forEach(function(tr) {
      var passes = grid[task+'|||'+tr] || [];
      if (!passes.length) row.push('-');
      else if (passes.length === 1) row.push(passes[0] ? 'Y' : 'N');
      else row.push(count(passes,function(p){return p})+'/'+passes.length);
    });
    rows.push(row);
  });
  // Footer
  var footer = ['Pass%'];
  treatments.forEach(function(tr) {
    var trRuns = results.filter(function(r){return r.treatment===tr});
    footer.push(trRuns.length ? fmtPct(count(trRuns,function(r){return r.acceptance_pass}),trRuns.length) : '-');
  });
  rows.push(footer);
  renderTable(el, headers, rows, aligns);
}

// ============ TAB 3: Efficiency ============
function renderEfficiencyTab(el, results) {
  // Efficiency (successful runs)
  var h = document.createElement('h3'); h.textContent = 'Efficiency (successful runs only)'; el.appendChild(h);
  var byT = groupBy(results, function(r){return r.treatment});
  var headers = ['Treatment','Successes','Tokens/Success','Cost/Success','Turns/Success'];
  var aligns = ['l','r','r','r','r'];
  var rows = [];
  sortedKeys(byT).forEach(function(t) {
    var succ = byT[t].filter(function(r){return r.acceptance_pass && r.regression_pass});
    var n = succ.length;
    if (n === 0) { rows.push([t,'0','N/A','N/A','N/A']); return; }
    rows.push([t, n, fmtTokens(Math.round(avg(succ,function(r){return r.tokens_total||0}))),
      fmtCost(avg(succ,function(r){return r.budget_used_usd||0})),
      fmtFloat(avg(succ,function(r){return r.api_turns||0}))]);
  });
  renderTable(el, headers, rows, aligns);

  // Tier Efficiency
  h = document.createElement('h3'); h.textContent = 'Efficiency by Tier (successful runs only)'; el.appendChild(h);
  var byTier = groupBy(results, function(r){return r._tier||'none'});
  headers = ['Tier','Successes','Total Runs','Success%','Tokens/Success','Cost/Success'];
  aligns = ['l','r','r','r','r','r'];
  rows = [];
  DATA.constants.TIER_ORDER.forEach(function(tk) {
    var runs = byTier[tk]; if (!runs||!runs.length) return;
    var succ = runs.filter(function(r){return r.acceptance_pass && r.regression_pass});
    var ns = succ.length, nt = runs.length;
    if (ns === 0) { rows.push([DATA.constants.TIER_LABELS[tk]||tk,'0',nt,'0%','N/A','N/A']); return; }
    rows.push([DATA.constants.TIER_LABELS[tk]||tk, ns, nt, fmtPct(ns,nt),
      fmtTokens(Math.round(avg(succ,function(r){return r.tokens_total||0}))),
      fmtCost(avg(succ,function(r){return r.budget_used_usd||0}))]);
  });
  renderTable(el, headers, rows, aligns);

  // Integrity
  h = document.createElement('h3'); h.textContent = 'Test Integrity'; el.appendChild(h);
  var byT2 = groupBy(results, function(r){return r.treatment});
  headers = ['Treatment','Runs','Avg R.Delta','Skip%','Tamper%','Avg Blks'];
  aligns = ['l','r','r','r','r','r'];
  rows = [];
  sortedKeys(byT2).forEach(function(t) {
    var runs = byT2[t], n = runs.length;
    rows.push([t, n,
      (avg(runs,function(r){return r.regression_delta||0})>=0?'+':'')+fmtFloat(avg(runs,function(r){return r.regression_delta||0})),
      fmtPct(count(runs,function(r){return(r.regression_skipped||0)>0}),n),
      fmtPct(count(runs,function(r){return r.regression_tests_modified}),n),
      fmtFloat(avg(runs,function(r){return r.stop_blocks||0}))]);
  });
  renderTable(el, headers, rows, aligns);
}

// ============ TAB 4: BDD Analysis ============
function renderBddTab(el, results) {
  // Engagement by Treatment
  var h = document.createElement('h3'); h.textContent = 'BDD Engagement by Treatment'; el.appendChild(h);
  var byT = groupBy(results, function(r){return r.treatment});
  var headers = ['Treatment','Runs','Pass%','Avg Quality','MCP Calls','bdd_test','Hooks','Injected','Failed','Uniq Facets','Edits'];
  var aligns = ['l','r','r','r','r','r','r','r','r','r','r'];
  var rows = [];
  sortedKeys(byT).forEach(function(t) {
    var runs = byT[t], n = runs.length;
    rows.push([t, n, fmtPct(count(runs,function(r){return r.acceptance_pass}),n),
      fmtFloat(avg(runs,function(r){return r._quality_score||0})),
      fmtFloat(avg(runs,function(r){return r.mcp_tool_calls||0})),
      fmtFloat(avg(runs,function(r){return r.bdd_test_calls||0})),
      fmtFloat(avg(runs,function(r){return r.hook_begins||0})),
      fmtFloat(avg(runs,function(r){return r.hook_injections||0})),
      fmtFloat(avg(runs,function(r){return r.hook_failures||0})),
      fmtFloat(avg(runs,function(r){return r.hook_unique_facets||0})),
      fmtFloat(avg(runs,function(r){return r.edit_log_entries||0}))]);
  });
  renderTable(el, headers, rows, aligns);

  // Chart: Treatment Pass Rate & Quality
  var chartData = [];
  sortedKeys(byT).forEach(function(t) {
    var runs = byT[t], n = runs.length;
    var passRate = n > 0 ? count(runs, function(r){return r.acceptance_pass}) / n * 100 : 0;
    var qual = avg(runs, function(r){return r._quality_score||0});
    chartData.push({label: t, values: [
      {value: passRate, color: '#0d6efd'},
      {value: qual, color: '#198754'}
    ]});
  });
  if (chartData.length > 0) {
    renderGroupedBarChart(el, chartData, {suffix: '', maxValue: 100, decimals: 0,
      legend: [{label: 'Pass %', color: '#0d6efd'}, {label: 'Avg Quality', color: '#198754'}]});
  }

  // Engagement vs Outcomes
  h = document.createElement('h3'); h.textContent = 'BDD Engagement Level vs Outcomes'; el.appendChild(h);
  var byEng = groupBy(results, function(r){return r._engagement||'No BDD'});
  var engOrder = ['No BDD','Hooks only','MCP only','MCP+Hooks','Agent only','Agent+Hooks','Agent+MCP','Agent+MCP+Hooks'];
  headers = ['Engagement Level','Runs','Pass%','Tamper%','Avg Tokens','Avg Turns','Avg Cost'];
  aligns = ['l','r','r','r','r','r','r'];
  rows = [];
  engOrder.forEach(function(label) {
    var runs = byEng[label]; if (!runs||!runs.length) return;
    var s = bucketStats(runs);
    rows.push([label, s.n, s.passPct, s.tamperPct, s.avgTokens, s.avgTurns, s.avgCost]);
  });
  // Catch extras
  Object.keys(byEng).forEach(function(label) {
    if (engOrder.indexOf(label) === -1) {
      var s = bucketStats(byEng[label]);
      rows.push([label, s.n, s.passPct, s.tamperPct, s.avgTokens, s.avgTurns, s.avgCost]);
    }
  });
  renderTable(el, headers, rows, aligns);

  // Chart: Engagement Level Pass Rate
  var engChartData = [];
  var engAllLabels = engOrder.slice();
  Object.keys(byEng).forEach(function(l) { if (engAllLabels.indexOf(l) === -1) engAllLabels.push(l); });
  engAllLabels.forEach(function(label) {
    var runs = byEng[label]; if (!runs || !runs.length) return;
    var n = runs.length;
    var passRate = count(runs, function(r){return r.acceptance_pass}) / n * 100;
    engChartData.push({label: label + ' (' + n + ')', value: passRate});
  });
  if (engChartData.length > 1) {
    renderBarChart(el, engChartData, {suffix: '%', maxValue: 100, colorFn: pctColor});
  }

  // Hook Effectiveness
  var hookedRuns = results.filter(function(r){return(r.hook_begins||0)>0});
  if (hookedRuns.length > 0) {
    h = document.createElement('h3'); h.textContent = 'Hook Injection Effectiveness'; el.appendChild(h);
    var p = document.createElement('p'); p.className = 'note'; p.textContent = 'Runs with hooks only. Injection rate = injections / hook invocations.'; el.appendChild(p);
    var byTH = groupBy(hookedRuns, function(r){return r.treatment});
    headers = ['Treatment','Runs','Pass%','Avg Begins','Avg Inj','Avg Skip','Inj Rate','Avg Facets','Avg Fail'];
    aligns = ['l','r','r','r','r','r','r','r','r'];
    rows = [];
    sortedKeys(byTH).forEach(function(t) {
      var runs = byTH[t], n = runs.length;
      var tBegins = sum(runs,function(r){return r.hook_begins||0});
      var tInj = sum(runs,function(r){return r.hook_injections||0});
      rows.push([t, n, fmtPct(count(runs,function(r){return r.acceptance_pass}),n),
        fmtFloat(avg(runs,function(r){return r.hook_begins||0})),
        fmtFloat(avg(runs,function(r){return r.hook_injections||0})),
        fmtFloat(avg(runs,function(r){return r.hook_skips||0})),
        tBegins>0?fmtPct(tInj,tBegins):'-',
        fmtFloat(avg(runs,function(r){return r.hook_unique_facets||0})),
        fmtFloat(avg(runs,function(r){return r.hook_failures||0}))]);
    });
    renderTable(el, headers, rows, aligns);
  }

  // Hook Variant Comparison
  if (hookedRuns.length > 0) {
    var byVar = groupBy(hookedRuns, function(r){return r._hook_variant||'none'});
    if (Object.keys(byVar).length >= 2) {
      h = document.createElement('h3'); h.textContent = 'Hook Variant Comparison'; el.appendChild(h);
      headers = ['Variant','Runs','Pass%','Inj Rate','Avg Facets','Avg Tokens','Avg Cost'];
      aligns = ['l','r','r','r','r','r','r'];
      rows = [];
      sortedKeys(byVar).forEach(function(v) {
        var runs = byVar[v], n = runs.length;
        var tBegins = sum(runs,function(r){return r.hook_begins||0});
        var tInj = sum(runs,function(r){return r.hook_injections||0});
        rows.push([v, n, fmtPct(count(runs,function(r){return r.acceptance_pass}),n),
          tBegins>0?fmtPct(tInj,tBegins):'-',
          fmtFloat(avg(runs,function(r){return r.hook_unique_facets||0})),
          fmtTokens(Math.round(avg(runs,function(r){return r.tokens_total||0}))),
          fmtCost(avg(runs,function(r){return r.budget_used_usd||0}))]);
      });
      renderTable(el, headers, rows, aligns);

      // Chart: Hook Variant Pass Rate & Injection Rate
      var varChartData = [];
      sortedKeys(byVar).forEach(function(v) {
        var runs = byVar[v], n = runs.length;
        var passRate = count(runs, function(r){return r.acceptance_pass}) / n * 100;
        var tB = sum(runs, function(r){return r.hook_begins||0});
        var tI = sum(runs, function(r){return r.hook_injections||0});
        var injRate = tB > 0 ? tI / tB * 100 : 0;
        varChartData.push({label: v + ' (' + n + ')', values: [
          {value: passRate, color: '#0d6efd'},
          {value: injRate, color: '#fd7e14'}
        ]});
      });
      if (varChartData.length > 1) {
        renderGroupedBarChart(el, varChartData, {suffix: '%', maxValue: 100, decimals: 0,
          legend: [{label: 'Pass %', color: '#0d6efd'}, {label: 'Injection Rate', color: '#fd7e14'}]});
      }
    }
  }

  // MCP Tool Patterns
  var mcpRuns = results.filter(function(r){return(r.mcp_tool_calls||0)>0});
  if (mcpRuns.length > 0) {
    h = document.createElement('h3'); h.textContent = 'MCP Tool Usage Patterns'; el.appendChild(h);
    p = document.createElement('p'); p.className = 'note'; p.textContent = 'Runs with MCP tool calls only.'; el.appendChild(p);
    var byTM = groupBy(mcpRuns, function(r){return r.treatment});
    headers = ['Treatment','Runs','Pass%','bdd_test','bdd_motiv','bdd_locate','bdd_status','Total MCP'];
    aligns = ['l','r','r','r','r','r','r','r'];
    rows = [];
    sortedKeys(byTM).forEach(function(t) {
      var runs = byTM[t], n = runs.length;
      rows.push([t, n, fmtPct(count(runs,function(r){return r.acceptance_pass}),n),
        fmtFloat(avg(runs,function(r){return r.bdd_test_calls||0})),
        fmtFloat(avg(runs,function(r){return r.bdd_motivation_calls||0})),
        fmtFloat(avg(runs,function(r){return r.bdd_locate_calls||0})),
        fmtFloat(avg(runs,function(r){return r.bdd_status_calls||0})),
        fmtFloat(avg(runs,function(r){return r.mcp_tool_calls||0}))]);
    });
    renderTable(el, headers, rows, aligns);

    // MCP Tool Usage Summary
    h = document.createElement('h3'); h.textContent = 'MCP Tool Usage Summary (across all runs)'; el.appendChild(h);
    var tools = [
      {name:'bdd_test', field:'bdd_test_calls'},
      {name:'bdd_motivation', field:'bdd_motivation_calls'},
      {name:'bdd_locate', field:'bdd_locate_calls'},
      {name:'bdd_status', field:'bdd_status_calls'}
    ];
    headers = ['MCP Tool','Total Calls','Runs Using','Avg/Run','Pass% (users)','Pass% (non-users)'];
    aligns = ['l','r','r','r','r','r'];
    rows = [];
    tools.forEach(function(tool) {
      var totalCalls = sum(results,function(r){return r[tool.field]||0});
      var users = results.filter(function(r){return(r[tool.field]||0)>0});
      var nonUsers = results.filter(function(r){return(r[tool.field]||0)===0});
      var nu = users.length;
      rows.push([tool.name, totalCalls, nu,
        nu>0?fmtFloat(totalCalls/nu):'0',
        nu>0?fmtPct(count(users,function(r){return r.acceptance_pass}),nu):'-',
        nonUsers.length>0?fmtPct(count(nonUsers,function(r){return r.acceptance_pass}),nonUsers.length):'-']);
    });
    renderTable(el, headers, rows, aligns);

    // Chart: MCP Tool Impact (users vs non-users pass rate)
    var mcpChartData = [];
    tools.forEach(function(tool) {
      var usrs = results.filter(function(r){return(r[tool.field]||0)>0});
      var nonUsrs = results.filter(function(r){return(r[tool.field]||0)===0});
      if (usrs.length === 0) return;
      var userPR = count(usrs, function(r){return r.acceptance_pass}) / usrs.length * 100;
      var nonPR = nonUsrs.length > 0 ? count(nonUsrs, function(r){return r.acceptance_pass}) / nonUsrs.length * 100 : 0;
      mcpChartData.push({label: tool.name, values: [
        {value: userPR, color: '#0d6efd'},
        {value: nonPR, color: '#adb5bd'}
      ]});
    });
    if (mcpChartData.length > 0) {
      var mh = document.createElement('h3'); mh.textContent = 'MCP Tool Impact on Pass Rate'; el.appendChild(mh);
      renderGroupedBarChart(el, mcpChartData, {suffix: '%', maxValue: 100, decimals: 0,
        legend: [{label: 'Users', color: '#0d6efd'}, {label: 'Non-users', color: '#adb5bd'}]});
    }
  }

  // Agent Outcomes
  var agentRuns = results.filter(function(r){return r._has_agents});
  if (agentRuns.length > 0) {
    h = document.createElement('h3'); h.textContent = 'Agent-Based Treatment Outcomes'; el.appendChild(h);
    var nonAgentRuns = results.filter(function(r){return !r._has_agents});
    var byTA = groupBy(agentRuns, function(r){return r.treatment});
    headers = ['Category','Runs','Pass%','Tamper%','Avg Tokens','Avg Turns','Avg Cost'];
    aligns = ['l','r','r','r','r','r','r'];
    rows = [];
    sortedKeys(byTA).forEach(function(t) {
      var s = bucketStats(byTA[t]);
      rows.push(['  '+t, s.n, s.passPct, s.tamperPct, s.avgTokens, s.avgTurns, s.avgCost]);
    });
    var sa = bucketStats(agentRuns);
    rows.push(['All agents', sa.n, sa.passPct, sa.tamperPct, sa.avgTokens, sa.avgTurns, sa.avgCost]);
    if (nonAgentRuns.length > 0) {
      var sn = bucketStats(nonAgentRuns);
      rows.push(['Non-agent', sn.n, sn.passPct, sn.tamperPct, sn.avgTokens, sn.avgTurns, sn.avgCost]);
    }
    renderTable(el, headers, rows, aligns);
  }

  // =================================================================
  // BDD Feature Correlation Scatter Plots
  // =================================================================
  h = document.createElement('h3'); h.textContent = 'BDD Features vs Pass Rate (per treatment)'; el.appendChild(h);
  p = document.createElement('p'); p.className = 'note';
  p.textContent = 'Each dot is a treatment. X-axis = average BDD feature usage, Y-axis = pass rate or quality. Dashed line = trend.';
  el.appendChild(p);

  // Aggregate per-treatment stats for scatter data
  var byTreat = groupBy(results, function(r){return r.treatment});
  var treatStats = [];
  sortedKeys(byTreat).forEach(function(t) {
    var runs = byTreat[t], n = runs.length;
    treatStats.push({
      label: t,
      passRate: count(runs, function(r){return r.acceptance_pass}) / n * 100,
      quality: avg(runs, function(r){return r._quality_score||0}),
      mcpCalls: avg(runs, function(r){return r.mcp_tool_calls||0}),
      bddTest: avg(runs, function(r){return r.bdd_test_calls||0}),
      hookInj: avg(runs, function(r){return r.hook_injections||0}),
      uniqFacets: avg(runs, function(r){return r.hook_unique_facets||0}),
      contextVol: avg(runs, function(r){return r._context_volume||0}),
      editEntries: avg(runs, function(r){return r.edit_log_entries||0})
    });
  });
  // Compute total BDD feature usage per treatment
  treatStats.forEach(function(s) {
    s.totalBdd = s.mcpCalls + s.bddTest + s.hookInj + s.uniqFacets + s.editEntries;
  });

  // --- Summary: Total BDD Usage vs Pass Rate & Quality ---
  h = document.createElement('h3'); h.textContent = 'Total BDD Usage vs Outcomes'; el.appendChild(h);
  p = document.createElement('p'); p.className = 'note';
  p.textContent = 'Total BDD = avg MCP calls + bdd_test calls + hook injections + unique facets + edit log entries per treatment.';
  el.appendChild(p);

  var summaryGrid = document.createElement('div');
  summaryGrid.style.cssText = 'display:flex;flex-wrap:wrap;gap:16px;margin:12px 0';

  // Total BDD vs Pass Rate
  var totalPassPts = treatStats.map(function(s) {
    return {x: s.totalBdd, y: s.passRate, label: s.label, color: pctColor(s.passRate)};
  });
  var wp = document.createElement('div');
  renderScatterPlot(wp, totalPassPts, {
    xLabel: 'Total BDD Usage (avg)', yLabel: 'Pass Rate',
    ySuffix: '%', yMax: 100, width: 420, height: 280,
    colorFn: pctColor
  });
  summaryGrid.appendChild(wp);

  // Total BDD vs Quality
  var hasQualSummary = treatStats.some(function(s){return s.quality > 0});
  if (hasQualSummary) {
    var totalQualPts = treatStats.map(function(s) {
      return {x: s.totalBdd, y: s.quality, label: s.label, color: '#198754'};
    });
    var wqs = document.createElement('div');
    renderScatterPlot(wqs, totalQualPts, {
      xLabel: 'Total BDD Usage (avg)', yLabel: 'Avg Quality',
      yMax: 100, width: 420, height: 280
    });
    summaryGrid.appendChild(wqs);
  }
  el.appendChild(summaryGrid);

  var bddFeatures = [
    {key: 'mcpCalls', label: 'Avg MCP Calls'},
    {key: 'bddTest', label: 'Avg bdd_test() Calls'},
    {key: 'hookInj', label: 'Avg Hook Injections'},
    {key: 'uniqFacets', label: 'Avg Unique Facets'},
    {key: 'contextVol', label: 'Avg Context Volume'},
    {key: 'editEntries', label: 'Avg Edit Log Entries'}
  ];

  // --- Pass Rate scatter plots ---
  var scatterGrid = document.createElement('div');
  scatterGrid.style.cssText = 'display:flex;flex-wrap:wrap;gap:16px;margin:12px 0';
  bddFeatures.forEach(function(feat) {
    var pts = treatStats.map(function(s) {
      return {x: s[feat.key], y: s.passRate, label: s.label, color: pctColor(s.passRate)};
    });
    // Skip if all x values are 0
    if (pts.every(function(p){return p.x === 0})) return;
    var wrap = document.createElement('div');
    renderScatterPlot(wrap, pts, {
      xLabel: feat.label, yLabel: 'Pass Rate',
      ySuffix: '%', yMax: 100, width: 420, height: 280,
      colorFn: pctColor
    });
    scatterGrid.appendChild(wrap);
  });
  el.appendChild(scatterGrid);

  // --- Quality scatter plots ---
  var hasQuality = treatStats.some(function(s){return s.quality > 0});
  if (hasQuality) {
    h = document.createElement('h3'); h.textContent = 'BDD Features vs Code Quality (per treatment)'; el.appendChild(h);

    var qualGrid = document.createElement('div');
    qualGrid.style.cssText = 'display:flex;flex-wrap:wrap;gap:16px;margin:12px 0';
    bddFeatures.forEach(function(feat) {
      var pts = treatStats.map(function(s) {
        return {x: s[feat.key], y: s.quality, label: s.label, color: '#198754'};
      });
      if (pts.every(function(p){return p.x === 0})) return;
      var wrap = document.createElement('div');
      renderScatterPlot(wrap, pts, {
        xLabel: feat.label, yLabel: 'Avg Quality',
        yMax: 100, width: 420, height: 280
      });
      qualGrid.appendChild(wrap);
    });
    el.appendChild(qualGrid);
  }

  // --- Per-run scatter: context volume vs outcome ---
  h = document.createElement('h3'); h.textContent = 'Per-Run: Context Volume vs Outcome'; el.appendChild(h);
  p = document.createElement('p'); p.className = 'note';
  p.textContent = 'Each dot is a single run. Color = pass (green) / fail (red).';
  el.appendChild(p);

  var perRunGrid = document.createElement('div');
  perRunGrid.style.cssText = 'display:flex;flex-wrap:wrap;gap:16px;margin:12px 0';

  // Context volume vs quality (per run)
  var runPtsQual = results.filter(function(r){return r._quality_score != null}).map(function(r) {
    return {x: r._context_volume||0, y: r._quality_score||0,
      label: '', color: r.acceptance_pass ? '#198754' : '#dc3545'};
  });
  if (runPtsQual.length > 0) {
    var wq = document.createElement('div');
    renderScatterPlot(wq, runPtsQual, {
      xLabel: 'Context Volume', yLabel: 'Quality Score',
      yMax: 100, width: 420, height: 280
    });
    perRunGrid.appendChild(wq);
  }

  // MCP calls vs quality (per run)
  var runPtsMcp = results.filter(function(r){return r._quality_score != null}).map(function(r) {
    return {x: r.mcp_tool_calls||0, y: r._quality_score||0,
      label: '', color: r.acceptance_pass ? '#198754' : '#dc3545'};
  });
  if (runPtsMcp.length > 0) {
    var wm = document.createElement('div');
    renderScatterPlot(wm, runPtsMcp, {
      xLabel: 'MCP Tool Calls', yLabel: 'Quality Score',
      yMax: 100, width: 420, height: 280
    });
    perRunGrid.appendChild(wm);
  }

  el.appendChild(perRunGrid);
}

// ============ TAB 5: Context ============
function renderContextTab(el, results) {
  // Context Volume Analysis
  var h = document.createElement('h3'); h.textContent = 'Context Volume vs Outcomes'; el.appendChild(h);
  var p = document.createElement('p'); p.className = 'note'; p.textContent = 'Context volume = hook injections + MCP tool calls'; el.appendChild(p);
  var volBuckets = {'0 (none)':[],'1-3 (light)':[],'4-7 (moderate)':[],'8-12 (heavy)':[],'13+ (saturated)':[]};
  results.forEach(function(r) {
    var vol = r._context_volume || 0;
    if (vol === 0) volBuckets['0 (none)'].push(r);
    else if (vol <= 3) volBuckets['1-3 (light)'].push(r);
    else if (vol <= 7) volBuckets['4-7 (moderate)'].push(r);
    else if (vol <= 12) volBuckets['8-12 (heavy)'].push(r);
    else volBuckets['13+ (saturated)'].push(r);
  });
  var headers = ['Context Volume','Runs','Pass%','Tamper%','Avg Tokens','Avg Cost'];
  var aligns = ['l','r','r','r','r','r'];
  var rows = [];
  ['0 (none)','1-3 (light)','4-7 (moderate)','8-12 (heavy)','13+ (saturated)'].forEach(function(label) {
    var runs = volBuckets[label]; if (!runs.length) return;
    var s = bucketStats(runs);
    rows.push([label, s.n, s.passPct, s.tamperPct, s.avgTokens, s.avgCost]);
  });
  renderTable(el, headers, rows, aligns);

  // Facet Coverage
  h = document.createElement('h3'); h.textContent = 'Facet Coverage vs Outcomes'; el.appendChild(h);
  p = document.createElement('p'); p.className = 'note'; p.textContent = 'Unique facets surfaced by hooks during the run'; el.appendChild(p);
  var facBuckets = {'0 facets':[],'1-5 facets':[],'6-10 facets':[],'11+ facets':[]};
  results.forEach(function(r) {
    var f = r.hook_unique_facets || 0;
    if (f === 0) facBuckets['0 facets'].push(r);
    else if (f <= 5) facBuckets['1-5 facets'].push(r);
    else if (f <= 10) facBuckets['6-10 facets'].push(r);
    else facBuckets['11+ facets'].push(r);
  });
  rows = [];
  ['0 facets','1-5 facets','6-10 facets','11+ facets'].forEach(function(label) {
    var runs = facBuckets[label]; if (!runs.length) return;
    var s = bucketStats(runs);
    rows.push([label, s.n, s.passPct, s.tamperPct, s.avgTokens, s.avgCost]);
  });
  renderTable(el, headers, rows, aligns);

  // Context vs Pass Scatter (table)
  var bddRuns = results.filter(function(r){return(r.hook_begins||0)>0||(r.mcp_tool_calls||0)>0});
  if (bddRuns.length > 0) {
    h = document.createElement('h3'); h.textContent = 'Per-Run BDD Context Detail'; el.appendChild(h);
    p = document.createElement('p'); p.className = 'note'; p.textContent = 'All BDD-active runs sorted by context volume (descending).'; el.appendChild(p);
    headers = ['Task','Treatment','Pass','CtxVol','Inj','MCP','Facets','Variant','Tokens','Cost'];
    aligns = ['l','l','c','r','r','r','r','l','r','r'];
    rows = [];
    bddRuns.sort(function(a,b){return(b._context_volume||0)-(a._context_volume||0)});
    bddRuns.forEach(function(r) {
      rows.push([r.task, r.treatment, fmtBool(r.acceptance_pass),
        r._context_volume||0, r.hook_injections||0, r.mcp_tool_calls||0,
        r.hook_unique_facets||0, r._hook_variant||'none',
        fmtTokens(r.tokens_total||0), fmtCost(r.budget_used_usd||0)]);
    });
    renderTable(el, headers, rows, aligns);
  }
}

// ============ TAB 6: Diagnostics ============
function renderDiagnosticsTab(el, results) {
  // Treatment Features
  var h = document.createElement('h3'); h.textContent = 'Treatment Feature Matrix'; el.appendChild(h);
  var byT = groupBy(results, function(r){return r.treatment});
  var headers = ['Treatment','Hooks','MCP','Agents','Skills','Hook Variant','Engagement'];
  var aligns = ['l','c','c','c','c','l','l'];
  var rows = [];
  sortedKeys(byT).forEach(function(t) {
    var runs = byT[t];
    var anyH = runs.some(function(r){return r._has_hooks});
    var anyM = runs.some(function(r){return r._has_mcp});
    var anyA = runs.some(function(r){return r._has_agents});
    var anyS = runs.some(function(r){return r._has_skills});
    var eng;
    if (anyA && anyM && anyH) eng = 'Agent+MCP+Hooks';
    else if (anyA && anyM) eng = 'Agent+MCP';
    else if (anyA && anyH) eng = 'Agent+Hooks';
    else if (anyA) eng = 'Agent only';
    else if (anyM && anyH) eng = 'MCP+Hooks';
    else if (anyM) eng = 'MCP only';
    else if (anyH) eng = 'Hooks only';
    else eng = 'No BDD';
    var variant = DATA.constants.HOOK_VARIANTS[t] || (anyH ? 'standard' : 'none');
    rows.push([t, anyH?'Y':'-', anyM?'Y':'-', anyA?'Y':'-', anyS?'Y':'-', variant, eng]);
  });
  renderTable(el, headers, rows, aligns);

  // Reliability
  h = document.createElement('h3'); h.textContent = 'Tool & Hook Reliability by Treatment'; el.appendChild(h);
  headers = ['Treatment','Runs','Tool Errs','Hook Starts','Hook Fails','Fail%','Top Error'];
  aligns = ['l','r','r','r','r','r','l'];
  rows = [];
  sortedKeys(byT).forEach(function(t) {
    var runs = byT[t], n = runs.length;
    var tStarts = sum(runs,function(r){return r.hook_begins||0});
    var tFails = sum(runs,function(r){return r.hook_failures||0});
    var errCounts = {};
    runs.forEach(function(r) {
      var types = r.tool_error_types || {};
      Object.keys(types).forEach(function(msg){errCounts[msg]=(errCounts[msg]||0)+types[msg]});
    });
    var topErr = '-';
    var maxC = 0;
    Object.keys(errCounts).forEach(function(msg){if(errCounts[msg]>maxC){maxC=errCounts[msg];topErr=msg}});
    if (topErr.length > 40) topErr = topErr.substring(0,37)+'...';
    rows.push([t, n, fmtFloat(avg(runs,function(r){return r.tool_errors||0})),
      fmtFloat(avg(runs,function(r){return r.hook_begins||0})),
      fmtFloat(avg(runs,function(r){return r.hook_failures||0})),
      tStarts>0?fmtPct(tFails,tStarts):'-', topErr]);
  });
  renderTable(el, headers, rows, aligns);

  // BDD Diagnosis
  h = document.createElement('h3'); h.textContent = 'BDD Diagnosis: Where Is BDD Failing?'; el.appendChild(h);

  // High context
  var hcFails = results.filter(function(r){return(r._context_volume||0)>=5 && !r.acceptance_pass});
  var hcPasses = results.filter(function(r){return(r._context_volume||0)>=5 && r.acceptance_pass});
  var div = document.createElement('div'); div.className = 'diag-section';
  var s = document.createElement('strong'); s.textContent = 'High context (5+ interactions) outcomes:'; div.appendChild(s);
  var totalHC = hcFails.length + hcPasses.length;
  if (totalHC > 0) {
    var mp = document.createElement('p'); mp.className = 'metric';
    mp.textContent = 'Pass: ' + hcPasses.length + '/' + totalHC + ' (' + Math.round(hcPasses.length/totalHC*100) + '%)';
    div.appendChild(mp);
    if (hcFails.length > 0) {
      var ftSet = {}; hcFails.forEach(function(r){ftSet[r.treatment]=1});
      mp = document.createElement('p'); mp.className = 'metric';
      mp.textContent = 'Failed treatments: ' + Object.keys(ftSet).sort().join(', ');
      div.appendChild(mp);
    }
  } else {
    var mp = document.createElement('p'); mp.className = 'metric'; mp.textContent = 'No runs with high BDD context volume.'; div.appendChild(mp);
  }
  el.appendChild(div);

  // Wasted hooks
  var wasted = results.filter(function(r){return(r.hook_begins||0)>0 && (r.hook_injections||0)===0});
  if (wasted.length > 0) {
    div = document.createElement('div'); div.className = 'diag-section';
    s = document.createElement('strong'); s.textContent = 'Hooks fired but zero injections (wasted hooks):'; div.appendChild(s);
    var ul = document.createElement('ul');
    wasted.forEach(function(r) {
      var li = document.createElement('li');
      li.textContent = r.task + ' / ' + r.treatment + ': ' + (r.hook_begins||0) + ' begins, ' + (r.hook_skips||0) + ' skips, ' + (r.hook_failures||0) + ' failures';
      ul.appendChild(li);
    });
    div.appendChild(ul); el.appendChild(div);
  }

  // MCP available but unused
  var hooksNoMcp = DATA.constants.HOOKS_NO_MCP_TREATMENTS || [];
  var mcpUnused = results.filter(function(r){return(r.mcp_tool_calls||0)===0 && (r.hook_begins||0)>0 && hooksNoMcp.indexOf(r.treatment)===-1});
  if (mcpUnused.length > 0) {
    div = document.createElement('div'); div.className = 'diag-section';
    s = document.createElement('strong'); s.textContent = 'BDD treatments where agent never called MCP tools:'; div.appendChild(s);
    var ul = document.createElement('ul');
    mcpUnused.forEach(function(r){var li = document.createElement('li'); li.textContent = r.task+' / '+r.treatment; ul.appendChild(li)});
    div.appendChild(ul); el.appendChild(div);
  }

  // Hook failures
  var hookFails = results.filter(function(r){return(r.hook_failures||0)>0});
  if (hookFails.length > 0) {
    div = document.createElement('div'); div.className = 'diag-section';
    s = document.createElement('strong'); s.textContent = 'Runs with hook failures:'; div.appendChild(s);
    var ul = document.createElement('ul');
    hookFails.forEach(function(r){var li = document.createElement('li'); li.textContent = r.task+' / '+r.treatment+': '+r.hook_failures+' failures out of '+r.hook_begins+' begins'; ul.appendChild(li)});
    div.appendChild(ul); el.appendChild(div);
  }

  // BDD tamper
  var bddTamper = results.filter(function(r){return((r.hook_injections||0)>0||(r.mcp_tool_calls||0)>0)&&r.regression_tests_modified});
  if (bddTamper.length > 0) {
    div = document.createElement('div'); div.className = 'diag-section';
    s = document.createElement('strong'); s.textContent = 'BDD context provided but agent tampered with tests:'; div.appendChild(s);
    var ul = document.createElement('ul');
    bddTamper.forEach(function(r){var li=document.createElement('li');li.textContent=r.task+' / '+r.treatment+': ctx_vol='+(r._context_volume||0)+', pass='+fmtBool(r.acceptance_pass);ul.appendChild(li)});
    div.appendChild(ul); el.appendChild(div);
  }

  // Cost effectiveness
  var bddR = results.filter(function(r){return(r.hook_begins||0)>0||(r.mcp_tool_calls||0)>0});
  var noBddR = results.filter(function(r){return(r.hook_begins||0)===0&&(r.mcp_tool_calls||0)===0&&!r._has_agents});
  if (bddR.length > 0 && noBddR.length > 0) {
    div = document.createElement('div'); div.className = 'diag-section';
    s = document.createElement('strong'); s.textContent = 'BDD cost-effectiveness summary:'; div.appendChild(s);
    var bddAvgCost = avg(bddR,function(r){return r.budget_used_usd||0});
    var noBddAvgCost = avg(noBddR,function(r){return r.budget_used_usd||0});
    var bddPass = count(bddR,function(r){return r.acceptance_pass})/bddR.length*100;
    var noBddPass = count(noBddR,function(r){return r.acceptance_pass})/noBddR.length*100;
    var mp = document.createElement('p'); mp.className='metric';
    mp.textContent='BDD runs: '+bddR.length+' runs, '+Math.round(bddPass)+'% pass, avg cost '+fmtCost(bddAvgCost); div.appendChild(mp);
    mp = document.createElement('p'); mp.className='metric';
    mp.textContent='No-BDD runs: '+noBddR.length+' runs, '+Math.round(noBddPass)+'% pass, avg cost '+fmtCost(noBddAvgCost); div.appendChild(mp);
    if (noBddAvgCost > 0) {
      var overhead = (bddAvgCost - noBddAvgCost) / noBddAvgCost * 100;
      mp = document.createElement('p'); mp.className='metric'; mp.textContent='Cost overhead: '+(overhead>=0?'+':'')+Math.round(overhead)+'%'; div.appendChild(mp);
    }
    var deltaPp = bddPass - noBddPass;
    mp = document.createElement('p'); mp.className='metric'; mp.textContent='Pass rate delta: '+(deltaPp>=0?'+':'')+Math.round(deltaPp)+'pp'; div.appendChild(mp);
    el.appendChild(div);
  }
}

// ============ TAB 7: Detail ============
function renderDetailTab(el, results) {
  var h = document.createElement('h3'); h.textContent = 'Per-Run Detail (' + results.length + ' runs)'; el.appendChild(h);
  var headers = ['Task','Treatment','Pass','R.Dlt','Blks','BDD','MCP','Inj','Facets','Tokens','Turns','Time','Cost'];
  var aligns = ['l','l','r','r','r','c','r','r','r','r','r','r','r'];
  var rows = [];
  results.forEach(function(r) {
    rows.push([r.task, r.treatment, fmtBool(r.acceptance_pass),
      fmtDelta(r.regression_delta||0), r.stop_blocks||0,
      r._engagement_tag||'-', r.mcp_tool_calls||0, r.hook_injections||0,
      r.hook_unique_facets||0, fmtTokens(r.tokens_total||0),
      r.api_turns||0, (r.wall_time_seconds||0)+'s',
      fmtCost(r.budget_used_usd||0)]);
  });
  renderTable(el, headers, rows, aligns);
}

// ============ TAB: Quality ============
function renderQualityTab(el, results) {
  // Filter to results with quality scores
  var scored = results.filter(function(r) { return r._quality_score != null; });
  if (!scored.length) {
    el.textContent = 'No quality scores available. Quality scoring requires expected.json in task directories.';
    return;
  }

  // --- Quality by Treatment ---
  var h = document.createElement('h3'); h.textContent = 'Quality by Treatment'; el.appendChild(h);
  var byT = groupBy(scored, function(r){return r.treatment});
  var headers = ['Treatment','Runs','Avg Quality','Correctness','File Prec','File Recall','Conciseness','Integrity','Clean Code'];
  var aligns = ['l','r','r','r','r','r','r','r','r'];
  var rows = [];
  sortedKeys(byT).forEach(function(t) {
    var runs = byT[t], n = runs.length;
    rows.push([t, n,
      fmtFloat(avg(runs,function(r){return r._quality_score||0})),
      fmtFloat(avg(runs,function(r){return r._correctness||0})),
      fmtFloat(avg(runs,function(r){return r._file_precision||0})),
      fmtFloat(avg(runs,function(r){return r._file_recall||0})),
      fmtFloat(avg(runs,function(r){return r._conciseness||0})),
      fmtFloat(avg(runs,function(r){return r._integrity||0})),
      fmtFloat(avg(runs,function(r){return r._clean_code||0}))]);
  });
  renderTable(el, headers, rows, aligns);

  // --- Quality by Task ---
  h = document.createElement('h3'); h.textContent = 'Quality by Task'; el.appendChild(h);
  var byK = groupBy(scored, function(r){return r.task});
  headers = ['Task','Runs','Avg Quality','Correctness','File Prec','File Recall','Conciseness'];
  aligns = ['l','r','r','r','r','r','r'];
  rows = [];
  sortedKeys(byK).forEach(function(k) {
    var runs = byK[k], n = runs.length;
    rows.push([k, n,
      fmtFloat(avg(runs,function(r){return r._quality_score||0})),
      fmtFloat(avg(runs,function(r){return r._correctness||0})),
      fmtFloat(avg(runs,function(r){return r._file_precision||0})),
      fmtFloat(avg(runs,function(r){return r._file_recall||0})),
      fmtFloat(avg(runs,function(r){return r._conciseness||0}))]);
  });
  renderTable(el, headers, rows, aligns);

  // --- Quality by Tier ---
  var TIERS = DATA.constants.TIER_ORDER || [];
  var TIER_LABELS = DATA.constants.TIER_LABELS || {};
  var byTier = groupBy(scored, function(r){return r._tier||'none'});
  if (Object.keys(byTier).length > 1) {
    h = document.createElement('h3'); h.textContent = 'Quality by Tier'; el.appendChild(h);
    headers = ['Tier','Runs','Avg Quality','Pass%','File Precision','File Recall'];
    aligns = ['l','r','r','r','r','r'];
    rows = [];
    TIERS.forEach(function(tier) {
      var runs = byTier[tier];
      if (!runs || !runs.length) return;
      var n = runs.length;
      rows.push([TIER_LABELS[tier]||tier, n,
        fmtFloat(avg(runs,function(r){return r._quality_score||0})),
        fmtPct(count(runs,function(r){return r.acceptance_pass}),n),
        fmtFloat(avg(runs,function(r){return r._file_precision||0})),
        fmtFloat(avg(runs,function(r){return r._file_recall||0}))]);
    });
    renderTable(el, headers, rows, aligns);
  }

  // --- Anti-pattern Frequency ---
  var allAnti = {};
  scored.forEach(function(r) {
    var ap = r._antipatterns || {};
    for (var k in ap) { allAnti[k] = (allAnti[k]||0) + ap[k]; }
  });
  if (Object.keys(allAnti).length > 0) {
    h = document.createElement('h3'); h.textContent = 'Anti-pattern Frequency'; el.appendChild(h);
    headers = ['Pattern','Total Occurrences','Runs Affected'];
    aligns = ['l','r','r'];
    rows = [];
    for (var pat in allAnti) {
      var affected = count(scored, function(r){ return (r._antipatterns||{})[pat] > 0; });
      rows.push([pat, allAnti[pat], affected]);
    }
    renderTable(el, headers, rows, aligns);
  }

  // --- Per-Run Quality Detail ---
  h = document.createElement('h3'); h.textContent = 'Per-Run Quality Detail (' + scored.length + ' scored runs)'; el.appendChild(h);
  headers = ['Task','Treatment','Quality','Correct','F.Prec','F.Recall','Concise','Integrity','Clean','Unexpected Files'];
  aligns = ['l','l','r','r','r','r','r','r','r','l'];
  rows = [];
  scored.forEach(function(r) {
    rows.push([r.task, r.treatment,
      fmtFloat(r._quality_score||0),
      fmtFloat(r._correctness||0),
      fmtFloat(r._file_precision||0),
      fmtFloat(r._file_recall||0),
      fmtFloat(r._conciseness||0),
      fmtFloat(r._integrity||0),
      fmtFloat(r._clean_code||0),
      (r._unexpected_files||[]).join(', ')||'-']);
  });
  renderTable(el, headers, rows, aligns);
}

// ============ TAB 8: Sequences ============
function renderSequencesTab(el, seqs) {
  if (!seqs.length) { el.textContent = 'No sequence results.'; return; }

  var h = document.createElement('h3'); h.textContent = 'Sequence Summary'; el.appendChild(h);
  var headers = ['Sequence','Treatment','Steps','All Pass','Cumul Pass','Passed','Failed','Tokens','Time','Cost','Regressions'];
  var aligns = ['l','l','r','c','c','r','r','r','r','r','r'];
  var rows = [];
  seqs.forEach(function(r) {
    var agg = r.aggregate || {};
    rows.push([r.sequence, r.treatment, r.num_steps||0,
      fmtBool(agg.all_steps_pass||false), fmtBool(agg.cumulative_pass_at_every_step||false),
      agg.steps_passed||0, agg.steps_failed||0,
      fmtTokens(agg.total_tokens||0), (agg.total_wall_time_seconds||0)+'s',
      fmtCost(agg.total_budget_used_usd||0), agg.prior_step_regressions||0]);
  });
  renderTable(el, headers, rows, aligns);

  // Step Detail
  h = document.createElement('h3'); h.textContent = 'Sequence Step Detail'; el.appendChild(h);
  headers = ['Sequence','Treatment','Step','Task','Accept','Regress','Prior OK','Cumul','Tokens','Time','Cost'];
  aligns = ['l','l','r','l','c','c','c','c','r','r','r'];
  rows = [];
  seqs.forEach(function(r) {
    (r.steps||[]).forEach(function(step) {
      var priorP = step.prior_steps_passed||0;
      var priorF = step.prior_steps_failed||0;
      rows.push([r.sequence, r.treatment, step.step, step.task,
        fmtBool(step.acceptance_pass||false), fmtBool(step.regression_pass||false),
        priorP+'/'+(priorP+priorF), fmtBool(step.cumulative_pass||false),
        fmtTokens(step.tokens_total||0), (step.wall_time_seconds||0)+'s',
        fmtCost(step.budget_used_usd||0)]);
    });
  });
  renderTable(el, headers, rows, aligns);
}

// === Init ===
(function() {
  // Restore filters from localStorage
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem('bdd-bench-filters') || '{}'); } catch(e) {}
  if (saved.subject) document.getElementById('f-subject').value = saved.subject;
  if (saved.treatment) document.getElementById('f-treatment').value = saved.treatment;
  if (saved.task) document.getElementById('f-task').value = saved.task;
  if (saved.start) document.getElementById('f-start').value = saved.start;
  if (saved.end) document.getElementById('f-end').value = saved.end;
  if (saved.activeTab) state.activeTab = saved.activeTab;

  // Wire tabs
  document.querySelectorAll('.tab-bar button').forEach(function(btn) {
    btn.addEventListener('click', function() { switchTab(btn.dataset.tab); saveFilters(); });
  });

  // Wire filter inputs with debounce
  var debounceTimer;
  var filterEls = ['f-subject','f-treatment','f-task','f-start','f-end'];
  filterEls.forEach(function(id) {
    document.getElementById(id).addEventListener('input', function() {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function() { getFilteredResults(); saveFilters(); }, 200);
    });
  });

  function saveFilters() {
    var obj = {
      subject: document.getElementById('f-subject').value,
      treatment: document.getElementById('f-treatment').value,
      task: document.getElementById('f-task').value,
      start: document.getElementById('f-start').value,
      end: document.getElementById('f-end').value,
      activeTab: state.activeTab
    };
    try { localStorage.setItem('bdd-bench-filters', JSON.stringify(obj)); } catch(e) {}
  }

  // Restore active tab
  switchTab(state.activeTab);

  // Initial filter
  getFilteredResults();
})();
</script>
</body>
</html>"""


# ============================================================
# Quality Scoring
# ============================================================

def _parse_diff_files(diff_patch: str) -> list[str]:
    """Extract list of touched files from a diff.patch."""
    files = set()
    for line in diff_patch.split("\n"):
        if line.startswith("diff --git"):
            # "diff --git a/foo/bar.py b/foo/bar.py"
            parts = line.split()
            if len(parts) >= 4:
                files.add(parts[3].lstrip("b/"))
        elif line.startswith("+++ b/"):
            files.add(line[6:])
    return sorted(files)


def _parse_diff_lines(diff_patch: str) -> tuple[int, int]:
    """Count real lines added/removed (excluding blank/comment-only)."""
    added = 0
    removed = 0
    for line in diff_patch.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:].strip()
            if content and not content.startswith("#"):
                added += 1
        elif line.startswith("-") and not line.startswith("---"):
            content = line[1:].strip()
            if content and not content.startswith("#"):
                removed += 1
    return added, removed


def _scan_antipatterns(diff_patch: str) -> dict[str, int]:
    """Scan diff for anti-patterns in added lines."""
    counts: dict[str, int] = defaultdict(int)
    for line in diff_patch.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            if re.search(r'\bTODO\b', content, re.IGNORECASE):
                counts["TODO"] += 1
            if re.search(r'\bFIXME\b', content, re.IGNORECASE):
                counts["FIXME"] += 1
            if re.search(r'\bprint\s*\(', content) and 'import' not in content:
                counts["debug_print"] += 1
            # Commented-out code (# followed by code-like content)
            stripped = content.strip()
            if stripped.startswith("#") and re.search(r'[=\(\)\[\]{}]', stripped[1:]):
                counts["commented_code"] += 1
    return dict(counts)


def load_golden_ref(task_dir: Path) -> dict | None:
    """Load expected.json golden reference from a task directory."""
    expected_path = task_dir / "expected.json"
    if not expected_path.exists():
        return None
    try:
        with open(expected_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _find_task_dir(bench_dir: Path, task_name: str, subject_name: str = "") -> Path | None:
    """Find the task directory for a given task name."""
    # Try tasks_2/ first (for adk_playground), then tasks/
    for tasks_parent in ["tasks_2", "tasks"]:
        candidate = bench_dir / tasks_parent / task_name
        if candidate.is_dir():
            return candidate
    return None


def compute_quality_score(metrics: dict, golden_ref: dict | None,
                          diff_patch: str) -> dict:
    """Compute composite quality score 0-100 for a single run.

    Returns dict with quality_score and sub-scores.
    """
    if not golden_ref:
        return {"quality_score": None}

    # --- Correctness (35%) ---
    accept_total = metrics.get("acceptance_total", 0)
    accept_passed = metrics.get("acceptance_passed", 0)
    correctness = (accept_passed / accept_total * 100) if accept_total > 0 else 0

    # --- File Precision (15%) ---
    expected_files = set(golden_ref.get("expected_files", []))
    optional_files = set(golden_ref.get("optional_files", []))
    noise_files = set(golden_ref.get("noise_files", []))
    touched_files = set(_parse_diff_files(diff_patch))

    # Remove noise files from touched
    real_touched = touched_files - noise_files
    expected_touched = real_touched & (expected_files | optional_files)
    unexpected_touched = real_touched - expected_files - optional_files

    if len(real_touched) > 0:
        file_precision = len(expected_touched) / len(real_touched) * 100
    else:
        file_precision = 0

    # --- File Recall (10%) ---
    if len(expected_files) > 0:
        file_recall = len(real_touched & expected_files) / len(expected_files) * 100
    else:
        file_recall = 100

    # --- Conciseness (15%) ---
    lines_spec = golden_ref.get("expected_lines_added", {})
    target = lines_spec.get("target", 30)
    min_lines = lines_spec.get("min", 5)
    max_lines = lines_spec.get("max", 100)
    actual_added, _ = _parse_diff_lines(diff_patch)

    if actual_added == 0:
        conciseness = 0
    elif min_lines <= actual_added <= max_lines:
        # Score based on distance from target
        if actual_added <= target:
            conciseness = 100
        else:
            overshoot = (actual_added - target) / (max_lines - target)
            conciseness = max(0, 100 - overshoot * 50)
    elif actual_added < min_lines:
        conciseness = actual_added / min_lines * 60  # partial credit
    else:
        # Over max
        overshoot = (actual_added - max_lines) / max_lines
        conciseness = max(0, 40 - overshoot * 40)

    # --- Integrity (15%) ---
    no_tamper = not metrics.get("regression_tests_modified", False)
    no_regression = metrics.get("regression_pass", False)
    integrity = 100 if (no_tamper and no_regression) else (50 if no_tamper else 0)

    # --- Clean Code (10%) ---
    antipatterns = _scan_antipatterns(diff_patch)
    total_antipatterns = sum(antipatterns.values())
    if total_antipatterns == 0:
        clean_code = 100
    elif total_antipatterns <= 2:
        clean_code = 70
    elif total_antipatterns <= 5:
        clean_code = 40
    else:
        clean_code = 10

    # --- Composite ---
    composite = (
        correctness * 0.35 +
        file_precision * 0.15 +
        file_recall * 0.10 +
        conciseness * 0.15 +
        integrity * 0.15 +
        clean_code * 0.10
    )

    return {
        "quality_score": round(composite, 1),
        "correctness": round(correctness, 1),
        "file_precision": round(file_precision, 1),
        "file_recall": round(file_recall, 1),
        "conciseness": round(conciseness, 1),
        "integrity": round(integrity, 1),
        "clean_code": round(clean_code, 1),
        "files_touched": sorted(real_touched),
        "expected_files_hit": sorted(real_touched & expected_files),
        "unexpected_files": sorted(unexpected_touched),
        "lines_added_real": actual_added,
        "antipatterns": antipatterns,
    }


def enrich_quality(results: list[dict], bench_dir: Path) -> list[dict]:
    """Add quality scores to each result dict (mutates in place).

    Loads expected.json from task dirs and diff.patch from result dirs.
    """
    for r in results:
        task = r.get("task", "")
        subject = r.get("subject", "taskboard")

        # Find task directory
        task_dir = _find_task_dir(bench_dir, task, subject)
        golden_ref = load_golden_ref(task_dir) if task_dir else None

        # Find diff.patch in result directory
        diff_patch = ""
        # Try to find result dir from timestamp
        ts = r.get("timestamp", "")
        treatment = r.get("treatment", "")
        # Search for matching result dir
        results_dir = bench_dir / "results"
        for pattern in [
            f"{ts}-{subject}-{task}-{treatment}",
            f"{ts}-{task}-{treatment}",  # old format
        ]:
            candidate = results_dir / pattern
            diff_file = candidate / "diff.patch"
            if diff_file.exists():
                try:
                    diff_patch = diff_file.read_text()
                except OSError:
                    pass
                break

        quality = compute_quality_score(r, golden_ref, diff_patch)
        r["_quality_score"] = quality.get("quality_score")
        r["_correctness"] = quality.get("correctness")
        r["_file_precision"] = quality.get("file_precision")
        r["_file_recall"] = quality.get("file_recall")
        r["_conciseness"] = quality.get("conciseness")
        r["_integrity"] = quality.get("integrity")
        r["_clean_code"] = quality.get("clean_code")
        r["_antipatterns"] = quality.get("antipatterns", {})
        r["_unexpected_files"] = quality.get("unexpected_files", [])

    return results


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
    opts = {"csv": False, "since": "", "markdown": False, "html": False}
    i = 0
    while i < len(argv):
        if argv[i] == "--csv":
            opts["csv"] = True
            i += 1
        elif argv[i] == "--markdown":
            opts["markdown"] = True
            i += 1
        elif argv[i] == "--html":
            opts["html"] = True
            i += 1
        elif argv[i] == "--since" and i + 1 < len(argv):
            opts["since"] = argv[i + 1]
            i += 2
        else:
            print(f"Usage: analyze.py [--since TIMESTAMP] [--markdown] [--html] [--csv]")
            print(f"  --since     Only include results at or after TIMESTAMP (e.g. 20260217T170000Z)")
            print(f"  --markdown  Print markdown tables to stdout (legacy)")
            print(f"  --html      Write interactive HTML report (default)")
            print(f"  --csv       Export results to CSV")
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

    # Enrich results with computed classification fields
    enrich_results(results)

    # Enrich results with quality scores
    enrich_quality(results, bench_dir)

    # Determine output mode: --markdown for legacy stdout, HTML by default
    do_markdown = opts["markdown"]
    do_html = opts["html"] or not do_markdown

    if do_markdown:
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

    if do_html:
        html_path = results_dir / "report.html"
        generate_html_report(results, seq_results, html_path,
                             since=since, num_rate_limited=num_rate_limited)

    # Export CSV if requested
    if opts["csv"]:
        csv_path = results_dir / "results.csv"
        export_csv(results, csv_path)


if __name__ == "__main__":
    main()
