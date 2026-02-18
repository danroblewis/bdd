# Benchmark Analysis Pipeline

This document explains how a benchmark run produces its results and how `analyze.py` aggregates them into the HTML report.

## How a Run Works (`run.sh`)

Each run executes a single **task x treatment** pair on a **subject** codebase:

```
./run.sh --task 210-fix-callback-regen --treatment baseline --subject subject_2
```

### Execution Flow

1. **Workspace creation** — copies the subject codebase into an isolated temp directory and initializes git.
2. **Treatment application** — copies CLAUDE.md (subject-specific variant if available), context files, runs `setup.sh` (installs catalog, hooks, MCP config).
3. **Prompt assembly** — combines any `pre_prompt` from `treatment.yaml` with `prompt.md` from the task directory.
4. **Claude agent execution** — runs `claude` CLI with stream-json output, budget cap, and the assembled prompt.
5. **Diff capture** — `git diff` captures everything the agent changed.
6. **Test execution** — acceptance and regression tests run separately (see below).
7. **Metrics extraction** — parses JSONL output, JUnit XML, hook logs, and edit logs into `metrics.json`.

### Pass/Fail Decision

There are two independent boolean verdicts per run. **Both must be true for a run to be considered successful.**

#### Acceptance Pass (`acceptance_pass`)

The task's acceptance test file (e.g. `test_210_fix_callback_regen.py`) is copied into the workspace's `tests/` directory and run with pytest:

```bash
$BENCH_VENV_PYTHON -m pytest tests/test_210_fix_callback_regen.py -v --tb=short
```

- **true** if pytest exit code is 0 (all tests pass)
- **false** if any test fails, errors, or collection fails

The test file is authored by the benchmark creator and defines what "correct implementation" means. Claude never sees this file during execution — it's injected only at verification time.

#### Regression Pass (`regression_pass`)

The subject's existing test suite runs against the agent's modified code:

```bash
$BENCH_VENV_PYTHON -m pytest tests/ -v --tb=short           # subject_2 (full dir)
$BENCH_VENV_PYTHON -m pytest tests/test_taskboard.py -v      # subject (single file)
```

The regression test file path comes from `subject.json`:

```json
{
  "regression_test_file": "tests/",
  "regression_baseline": 81
}
```

- **true** if pytest exit code is 0
- **false** if any existing test fails or errors during collection

This catches cases where the agent broke existing functionality while implementing the new feature.

#### Derived Metrics

From the JUnit XML output, run.sh also extracts:

| Metric | Source | Meaning |
|--------|--------|---------|
| `acceptance_total` | JUnit XML | Number of acceptance test cases |
| `acceptance_passed` | JUnit XML | Tests that passed |
| `acceptance_failed` | JUnit XML | Tests that failed assertions |
| `acceptance_errors` | JUnit XML | Tests that errored (import failures, etc.) |
| `regression_total` | JUnit XML | Number of regression test cases |
| `regression_baseline` | subject.json | Expected test count for the subject |
| `regression_delta` | Computed | `regression_total - regression_baseline` (positive means agent added tests) |
| `regression_tests_modified` | git diff | Whether the agent edited the regression test file (test tampering) |
| `stop_blocks` | `.bdd/stop-blocks.log` | Times the Stop hook blocked the agent from finishing |

### Test Tampering Detection

After tests run, `run.sh` checks `git diff --name-only` to see if the agent modified any files under the regression test path. If so, `regression_tests_modified` is set to `true`. This flags runs where the agent "cheated" by changing the tests to make them pass instead of fixing the code.

## How Analysis Works (`analyze.py`)

### Data Loading

`analyze.py` recursively scans the `results/` directory for `metrics.json` files. Each file represents one run.

**Filtering at load time:**
- Sequence-type results (`"type": "sequence"`) are loaded separately
- Rate-limited runs (zero tokens AND zero cost) are excluded entirely
- Optional `--since` flag filters by timestamp

### Result Enrichment

After loading, two enrichment passes run:

1. **`enrich_results()`** — classifies each run by:
   - **Tier**: `none`, `context-only`, `mcp-only`, `hooks-only`, `hooks+mcp`, `agent`
   - **Engagement**: what BDD features were actually used (hooks, MCP tools, agents, skills)
   - **Context volume**: `hook_injections + mcp_tool_calls` (proxy for how much BDD context the agent received)
   - **Hook variant**: `standard`, `differential`, `narrative`, `progressive`, `best-chain`, etc.

2. **`enrich_quality()`** — computes quality scores (see Quality Scoring below)

### HTML Report

The report is a single self-contained HTML file with embedded JavaScript. All data is inlined as a JSON blob. Tabs render tables on demand from this data.

**Filters** (top bar): Subject, Treatment, Task (all regex), From/To (datetime). Filters persist in localStorage and apply to all tabs.

### Report Tabs

| Tab | What it shows |
|-----|---------------|
| **Summary** | Per-treatment aggregates: runs, pass rate, avg tokens/cost/turns, tamper% |
| **Matrix** | Task x Treatment grid with pass/fail cells |
| **Efficiency** | Cost and tokens per successful run |
| **BDD Analysis** | Hook/MCP usage breakdown, BDD vs non-BDD pass rates |
| **Context** | Context volume analysis, high-context failures |
| **Diagnostics** | Tool error breakdown, sequence results |
| **Detail** | Every individual run with all metrics |
| **Quality** | Quality scores by treatment, task, and tier |
| **Sequences** | Multi-step sequence results |

### How Pass Rate is Calculated

In summary tables, **pass rate** = percentage of runs where `acceptance_pass` is true:

```
pass_rate = count(acceptance_pass == true) / total_runs * 100
```

Note: `regression_pass` is not factored into the pass rate directly. It is tracked separately as "tamper%" and "regression delta" columns. The rationale is that regression failures are an integrity issue (the agent broke something), while acceptance failures mean the feature wasn't implemented correctly.

For efficiency calculations, a run is only counted as a "success" if **both** `acceptance_pass` AND `regression_pass` are true.

## Quality Scoring

Quality scoring is available when tasks have an `expected.json` golden reference file. It produces a composite score from 0-100.

### Golden Reference (`expected.json`)

Each task can optionally include:

```json
{
  "expected_files": ["backend/project_manager.py", "backend/main.py"],
  "optional_files": ["backend/models.py"],
  "expected_lines_added": {"min": 20, "target": 40, "max": 80},
  "noise_files": [".claude/settings.json", "CLAUDE.md"]
}
```

### Sub-Scores

| Metric | Weight | What it measures |
|--------|--------|-----------------|
| **Correctness** | 35% | `acceptance_passed / acceptance_total * 100` |
| **File Precision** | 15% | What fraction of files touched were expected (ignores noise files like `.claude/settings.json`) |
| **File Recall** | 10% | What fraction of expected files were actually touched |
| **Conciseness** | 15% | Were the right number of lines added? 100 if at/below target, scales down toward max, penalized above max |
| **Integrity** | 15% | 100 if no test tampering AND regression passes; 50 if no tampering but regression fails; 0 if tests were tampered |
| **Clean Code** | 10% | Penalty for anti-patterns in the diff: TODO/FIXME comments, debug print statements, commented-out code |

### Composite Formula

```
quality = correctness * 0.35
        + file_precision * 0.15
        + file_recall * 0.10
        + conciseness * 0.15
        + integrity * 0.15
        + clean_code * 0.10
```

### Anti-Pattern Detection

The diff is scanned for:
- `TODO` / `FIXME` / `HACK` / `XXX` comments in added lines
- `print(` / `console.log` debug statements in added lines
- Commented-out code (lines starting with `# ` followed by code-like patterns)

## Subject Configuration

Each subject has a `subject.json` that configures the benchmark runner:

```json
{
  "name": "adk_playground",
  "subject_dir": "subject_2",
  "tasks_dir": "tasks_2",
  "regression_test_file": "tests/",
  "regression_baseline": 81,
  "venv_python": ".venv_2/bin/python3"
}
```

| Field | Purpose |
|-------|---------|
| `name` | Display name in reports and result directory names |
| `subject_dir` | Directory containing the codebase to copy into workspace |
| `tasks_dir` | Directory containing task subdirectories |
| `regression_test_file` | Path (relative to workspace) passed to pytest for regression testing |
| `regression_baseline` | Expected number of regression tests (for delta calculation) |
| `venv_python` | Path to Python venv with subject's dependencies |

## Result Directory Structure

Each run produces a timestamped result directory:

```
results/20260218T012015Z-adk_playground-210-fix-callback-regen-narrative-hooks/
  metrics.json              # All quantitative metrics (the primary data source)
  agent-output.jsonl        # Raw Claude stream-json output
  agent-stderr.txt          # Agent stderr
  diff.patch                # Full git diff of agent's changes
  diff-stat.txt             # Diff statistics
  prompt.txt                # Rendered prompt sent to Claude
  acceptance-output.txt     # Acceptance test stdout/stderr
  acceptance-junit.xml      # Acceptance test JUnit XML
  regression-output.txt     # Regression test stdout/stderr
  regression-junit.xml      # Regression test JUnit XML
  bdd-artifacts/            # BDD-specific logs (if applicable)
    hook.log                # Hook injection events
    edit_log.json           # Edit-triggered facet associations
    stop-blocks.log         # Stop hook block events
```
