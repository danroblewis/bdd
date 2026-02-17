"""Tests proving BDD MCP tools produce meaningfully different outputs.

Uses a multi-goal catalog (3 goals, 5 expectations, 10 facets) spanning
three disjoint domains (auth, billing, reporting) with distinct status
profiles (failing, untested, passing). A matching index maps each domain
to exclusive source files with no cross-domain overlap.
"""

import json
import os
import sys

import pytest

# Import bdd_server from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bdd_server


# ---------------------------------------------------------------------------
# Catalog and index builders
# ---------------------------------------------------------------------------

def _make_catalog():
    """3-goal, 5-expectation, 10-facet catalog across auth/billing/reporting."""
    return {
        "version": 1,
        "nodes": [
            # --- Auth (g-001): computes as FAILING ---
            {"id": "g-001", "type": "goal", "text": "User authentication works",
             "parent": None, "priority": 1, "labels": []},
            {"id": "e-001", "type": "expectation", "text": "Login handles credentials",
             "parent": "g-001", "priority": 1, "labels": []},
            {"id": "e-002", "type": "expectation", "text": "Session management is reliable",
             "parent": "g-001", "priority": 2, "labels": []},
            {"id": "f-001", "type": "facet", "text": "Valid credentials return token",
             "parent": "e-001", "test": "tests/test_auth.py::test_login_valid",
             "status": "passing"},
            {"id": "f-002", "type": "facet", "text": "Invalid credentials return error",
             "parent": "e-001", "test": "tests/test_auth.py::test_login_invalid",
             "status": "failing"},
            {"id": "f-003", "type": "facet", "text": "Session is created on login",
             "parent": "e-002", "test": "tests/test_auth.py::test_session_create",
             "status": "passing"},
            {"id": "f-004", "type": "facet", "text": "Session expires after timeout",
             "parent": "e-002", "test": "tests/test_auth.py::test_session_expire",
             "status": "passing"},

            # --- Billing (g-002): computes as UNTESTED ---
            {"id": "g-002", "type": "goal", "text": "Billing processes payments",
             "parent": None, "priority": 2, "labels": []},
            {"id": "e-003", "type": "expectation", "text": "Credit card charges succeed",
             "parent": "g-002", "priority": 1, "labels": []},
            {"id": "e-004", "type": "expectation", "text": "Invoices are generated correctly",
             "parent": "g-002", "priority": 2, "labels": []},
            {"id": "f-005", "type": "facet", "text": "Charge creates transaction record",
             "parent": "e-003", "test": None, "status": "untested"},
            {"id": "f-006", "type": "facet", "text": "Charge handles declined cards",
             "parent": "e-003", "test": None, "status": "untested"},
            {"id": "f-007", "type": "facet", "text": "Invoice includes line items",
             "parent": "e-004", "test": None, "status": "untested"},
            {"id": "f-008", "type": "facet", "text": "Invoice calculates tax correctly",
             "parent": "e-004", "test": None, "status": "untested"},

            # --- Reporting (g-003): computes as PASSING ---
            {"id": "g-003", "type": "goal", "text": "Reporting dashboard works",
             "parent": None, "priority": 3, "labels": []},
            {"id": "e-005", "type": "expectation", "text": "Reports load correctly",
             "parent": "g-003", "priority": 1, "labels": []},
            {"id": "f-009", "type": "facet", "text": "Report data loads from database",
             "parent": "e-005", "test": "tests/test_reports.py::test_report_load",
             "status": "passing"},
            {"id": "f-010", "type": "facet", "text": "Report renders as HTML",
             "parent": "e-005", "test": "tests/test_reports.py::test_report_render",
             "status": "passing"},
        ],
    }


def _make_index():
    """Index with no cross-domain file overlap."""
    return {
        "forward": {
            "src/auth.py": {
                "10": ["f-001", "f-002"],
                "11": ["f-001", "f-002"],
                "12": ["f-001", "f-002"],
                "20": ["f-003", "f-004"],
                "21": ["f-003", "f-004"],
                "22": ["f-003", "f-004"],
            },
            "src/session.py": {
                "5": ["f-003", "f-004"],
                "6": ["f-003", "f-004"],
            },
            "src/billing.py": {
                "10": ["f-005", "f-006"],
                "11": ["f-005", "f-006"],
                "12": ["f-005", "f-006"],
                "30": ["f-007", "f-008"],
                "31": ["f-007", "f-008"],
                "32": ["f-007", "f-008"],
            },
            "src/invoice.py": {
                "5": ["f-007", "f-008"],
                "6": ["f-007", "f-008"],
            },
            "src/reports.py": {
                "10": ["f-009"],
                "11": ["f-010"],
            },
        },
        "reverse": {
            "f-001": {"src/auth.py": [10, 11, 12]},
            "f-002": {"src/auth.py": [10, 11, 12]},
            "f-003": {"src/auth.py": [20, 21, 22], "src/session.py": [5, 6]},
            "f-004": {"src/auth.py": [20, 21, 22], "src/session.py": [5, 6]},
            "f-005": {"src/billing.py": [10, 11, 12]},
            "f-006": {"src/billing.py": [10, 11, 12]},
            "f-007": {"src/billing.py": [30, 31, 32], "src/invoice.py": [5, 6]},
            "f-008": {"src/billing.py": [30, 31, 32], "src/invoice.py": [5, 6]},
            "f-009": {"src/reports.py": [10]},
            "f-010": {"src/reports.py": [11]},
        },
        "test_results": {},
        "facet_status": {},
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path, monkeypatch):
    """Set up a 3-goal project with catalog and index."""
    with open(tmp_path / "catalog.json", "w") as f:
        json.dump(_make_catalog(), f)

    bdd_dir = tmp_path / ".bdd"
    bdd_dir.mkdir()
    with open(bdd_dir / "index.json", "w") as f:
        json.dump(_make_index(), f)

    monkeypatch.setattr(bdd_server, "PROJECT_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def project_with_issues(tmp_path, monkeypatch):
    """Base catalog + 2 defects: overload (f-011) and orphan (f-012)."""
    catalog = _make_catalog()
    # f-011: shares test with f-001 → overload
    catalog["nodes"].append({
        "id": "f-011", "type": "facet", "text": "Duplicate login test case",
        "parent": "e-001", "test": "tests/test_auth.py::test_login_valid",
        "status": "passing",
    })
    # f-012: parent e-999 doesn't exist → structural orphan
    catalog["nodes"].append({
        "id": "f-012", "type": "facet", "text": "Orphaned billing facet",
        "parent": "e-999", "test": None, "status": "untested",
    })

    with open(tmp_path / "catalog.json", "w") as f:
        json.dump(catalog, f)

    # Empty index is fine — overload/structural checks use catalog only
    monkeypatch.setattr(bdd_server, "PROJECT_ROOT", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# TestTreeDifferentiation
# ---------------------------------------------------------------------------

class TestTreeDifferentiation:

    def test_different_subtrees_by_node_id(self, project):
        auth = bdd_server.bdd_tree(node_id="g-001")
        billing = bdd_server.bdd_tree(node_id="g-002")

        # Auth subtree contains only auth nodes
        for nid in ("e-001", "e-002", "f-001", "f-002", "f-003", "f-004"):
            assert nid in auth
        for nid in ("e-003", "e-004", "f-005", "f-006", "f-007", "f-008",
                     "g-002", "g-003"):
            assert nid not in auth

        # Billing subtree contains only billing nodes
        for nid in ("e-003", "e-004", "f-005", "f-006", "f-007", "f-008"):
            assert nid in billing
        for nid in ("e-001", "e-002", "f-001", "f-002", "f-003", "f-004",
                     "g-001", "g-003"):
            assert nid not in billing

    def test_status_filter_differentiates(self, project):
        failing = bdd_server.bdd_tree(status_filter="failing")
        untested = bdd_server.bdd_tree(status_filter="untested")
        passing = bdd_server.bdd_tree(status_filter="passing")

        # Failing: only g-001 branch (has a failure)
        assert "g-001" in failing
        assert "e-001" in failing
        assert "f-002" in failing
        assert "g-002" not in failing
        assert "g-003" not in failing

        # Untested: only g-002 branch
        assert "g-002" in untested
        assert "e-003" in untested
        assert "e-004" in untested
        assert "g-001" not in untested
        assert "g-003" not in untested

        # Passing: only g-003 branch
        assert "g-003" in passing
        assert "e-005" in passing
        assert "f-009" in passing
        assert "f-010" in passing
        assert "g-001" not in passing
        assert "g-002" not in passing

    def test_max_depth_limits_output(self, project):
        depth1 = bdd_server.bdd_tree(max_depth=1)
        depth2 = bdd_server.bdd_tree(max_depth=2)
        depth3 = bdd_server.bdd_tree(max_depth=3)

        # Depth 1: goals only — no expectations or facets
        assert "g-001" in depth1
        assert "g-002" in depth1
        assert "g-003" in depth1
        assert "e-001" not in depth1
        assert "f-001" not in depth1

        # Depth 2: goals + expectations — no facets
        assert "g-001" in depth2
        assert "e-001" in depth2
        assert "e-005" in depth2
        assert "f-001" not in depth2
        assert "f-009" not in depth2

        # Depth 3: everything
        assert "g-001" in depth3
        assert "e-001" in depth3
        assert "f-001" in depth3
        assert "f-010" in depth3

    def test_unsatisfied_filter_hides_passing(self, project):
        unfiltered = bdd_server.bdd_tree(node_id="g-001")
        unsatisfied = bdd_server.bdd_tree(
            node_id="g-001", status_filter="unsatisfied"
        )

        # Unfiltered shows the passing branch (e-002)
        assert "e-002" in unfiltered

        # Unsatisfied hides e-002 and its children
        assert "e-002" not in unsatisfied
        assert "f-003" not in unsatisfied
        assert "f-004" not in unsatisfied

        # But still shows the failing branch
        assert "e-001" in unsatisfied
        assert "f-002" in unsatisfied


# ---------------------------------------------------------------------------
# TestMotivationDifferentiation
# ---------------------------------------------------------------------------

class TestMotivationDifferentiation:

    def test_different_files(self, project):
        auth = bdd_server.bdd_motivation(file="src/auth.py")
        billing = bdd_server.bdd_motivation(file="src/billing.py")

        # Auth file → auth domain chain
        assert "g-001" in auth
        assert "g-002" not in auth

        # Billing file → billing domain chain
        assert "g-002" in billing
        assert "g-001" not in billing

    def test_line_range_narrows(self, project):
        login = bdd_server.bdd_motivation(
            file="src/auth.py", start_line=10, end_line=12
        )
        session = bdd_server.bdd_motivation(
            file="src/auth.py", start_line=20, end_line=22
        )

        # Both share g-001 but differ at expectation level
        assert "g-001" in login
        assert "g-001" in session

        assert "e-001" in login
        assert "e-002" not in login

        assert "e-002" in session
        assert "e-001" not in session

    def test_exclusive_files(self, project):
        session = bdd_server.bdd_motivation(file="src/session.py")
        invoice = bdd_server.bdd_motivation(file="src/invoice.py")

        # Session → auth domain only
        assert "g-001" in session
        assert "g-002" not in session

        # Invoice → billing domain only
        assert "g-002" in invoice
        assert "g-001" not in invoice

    def test_nonexistent_file(self, project):
        result = bdd_server.bdd_motivation(file="src/nonexistent.py")

        assert "No catalog entries" in result

        # Real files produce different (non-error) output
        auth = bdd_server.bdd_motivation(file="src/auth.py")
        assert "No catalog entries" not in auth


# ---------------------------------------------------------------------------
# TestLocateDifferentiation
# ---------------------------------------------------------------------------

class TestLocateDifferentiation:

    def test_different_facets(self, project):
        loc_f001 = bdd_server.bdd_locate(node_id="f-001")
        loc_f007 = bdd_server.bdd_locate(node_id="f-007")

        # f-001 → auth.py only
        assert "src/auth.py" in loc_f001
        assert "src/billing.py" not in loc_f001

        # f-007 → billing.py + invoice.py
        assert "src/billing.py" in loc_f007
        assert "src/invoice.py" in loc_f007
        assert "src/auth.py" not in loc_f007

    def test_expectation_aggregates(self, project):
        loc_e001 = bdd_server.bdd_locate(node_id="e-001")
        loc_e003 = bdd_server.bdd_locate(node_id="e-003")

        # e-001 (login) aggregates f-001+f-002 → auth.py
        assert "src/auth.py" in loc_e001
        assert "src/billing.py" not in loc_e001

        # e-003 (charges) aggregates f-005+f-006 → billing.py
        assert "src/billing.py" in loc_e003
        assert "src/auth.py" not in loc_e003

    def test_goal_aggregates(self, project):
        loc_g001 = bdd_server.bdd_locate(node_id="g-001")
        loc_g002 = bdd_server.bdd_locate(node_id="g-002")

        # g-001 → auth.py + session.py, no billing
        assert "src/auth.py" in loc_g001
        assert "src/session.py" in loc_g001
        assert "src/billing.py" not in loc_g001
        assert "src/invoice.py" not in loc_g001

        # g-002 → billing.py + invoice.py, no auth
        assert "src/billing.py" in loc_g002
        assert "src/invoice.py" in loc_g002
        assert "src/auth.py" not in loc_g002
        assert "src/session.py" not in loc_g002


# ---------------------------------------------------------------------------
# TestStatusDifferentiation
# ---------------------------------------------------------------------------

class TestStatusDifferentiation:

    def test_summary_counts(self, project):
        output = bdd_server.bdd_status()

        assert "Goals: 3" in output
        assert "Expectations: 5" in output
        assert "Facets: 10" in output
        assert "Passing: 5" in output
        assert "Failing: 1" in output
        assert "Untested: 4" in output
        assert "Satisfied: 2/5" in output

    def test_check_categories_differ(self, project_with_issues):
        overload = bdd_server.bdd_status(check="overload")
        structural = bdd_server.bdd_status(check="structural")
        all_checks = bdd_server.bdd_status(check="all")

        # Overload shows Test Overload section, not Structural
        assert "Test Overload" in overload
        assert "Structural" not in overload

        # Structural shows Structural section, not Test Overload
        assert "Structural" in structural
        assert "Test Overload" not in structural

        # All shows both
        assert "Test Overload" in all_checks
        assert "Structural" in all_checks
