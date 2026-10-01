"""Canonicalisation and digesting, which is what makes the cross-engine check sound."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from orashift.seed import verify


def test_decimals_that_are_numerically_equal_canonicalise_identically():
    """Oracle returns Decimal('500'); PostgreSQL returns Decimal('500.00')."""
    assert verify.canonical(Decimal("500")) == verify.canonical(Decimal("500.00"))
    assert verify.canonical(Decimal("0.0000")) == verify.canonical(Decimal("0"))
    assert verify.canonical(Decimal("1.50")) == verify.canonical(Decimal("1.5"))


def test_canonical_decimal_avoids_scientific_notation():
    assert verify.canonical(Decimal("500.00")) == "500"
    assert "E" not in verify.canonical(Decimal("1E+4"))


def test_numerically_different_decimals_stay_different():
    assert verify.canonical(Decimal("1.50")) != verify.canonical(Decimal("1.51"))


def test_null_is_distinct_from_the_text_that_spells_it():
    assert verify.canonical(None) != verify.canonical("NULL")
    assert verify.canonical(None) != verify.canonical("None")
    assert verify.canonical(None) != verify.canonical("")


def test_timestamps_canonicalise_to_the_second():
    value = dt.datetime(2024, 3, 7, 14, 35, 59)
    assert verify.canonical(value) == "2024-03-07 14:35:59"


def test_digest_is_insensitive_to_row_order():
    a = [(1, "x"), (2, "y"), (3, "z")]
    b = [(3, "z"), (1, "x"), (2, "y")]
    assert verify.digest_rows(a) == verify.digest_rows(b)


def test_digest_changes_when_a_value_changes():
    assert verify.digest_rows([(1, "x")]) != verify.digest_rows([(1, "y")])


def test_digest_changes_when_a_null_replaces_a_value():
    assert verify.digest_rows([(1, None)]) != verify.digest_rows([(1, "x")])


def test_digest_is_not_confused_by_field_boundaries():
    """('ab','c') must not digest the same as ('a','bc')."""
    assert verify.digest_rows([("ab", "c")]) != verify.digest_rows([("a", "bc")])


def test_digest_distinguishes_a_duplicated_row():
    assert verify.digest_rows([(1, "x")]) != verify.digest_rows([(1, "x"), (1, "x")])


def test_comparison_reports_ok_only_when_counts_and_digests_agree():
    same = verify.TableComparison("t", 5, 5, "abc", "abc")
    assert same.ok

    bad_count = verify.TableComparison("t", 5, 4, "abc", "abc")
    assert not bad_count.ok and not bad_count.counts_match

    bad_digest = verify.TableComparison("t", 5, 5, "abc", "xyz")
    assert not bad_digest.ok and bad_digest.counts_match and not bad_digest.digests_match
