"""Unit tests for Azure DevOps tool helpers (no network)."""

import pytest

from yeaboi.tools.azure_devops import _DEFAULT_WORK_ITEM_STATE, _normalize_work_item_state


class TestNormalizeWorkItemState:
    """WIQL-injection defense (F5): `state` is whitelisted before interpolation."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Active", "Active"),
            ("active", "Active"),
            ("  NEW ", "New"),
            ("resolved", "Resolved"),
            ("Closed", "Closed"),
            ("done", "Done"),
            ("Removed", "Removed"),
            ("all", "All"),
        ],
    )
    def test_known_states_pass_through_canonicalized(self, raw, expected):
        assert _normalize_work_item_state(raw) == expected

    @pytest.mark.parametrize(
        "attack",
        [
            "Active' OR '1'='1",
            "'; DROP TABLE WorkItems; --",
            "Active'",
            "unknown-state",
            "",
        ],
    )
    def test_injection_attempts_coerced_to_default(self, attack):
        # Anything not in the whitelist can never reach the WIQL string as-is.
        assert _normalize_work_item_state(attack) == _DEFAULT_WORK_ITEM_STATE

    def test_result_never_contains_a_single_quote(self):
        for candidate in ("Active' OR '1'='1", "x'--", "New", "all"):
            assert "'" not in _normalize_work_item_state(candidate)
