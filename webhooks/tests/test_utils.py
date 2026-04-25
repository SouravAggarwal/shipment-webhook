"""Tests for utility functions."""

from datetime import datetime
from decimal import Decimal

from django.test import TestCase

from webhooks.utils import canonical_json_hash, normalize_status, parse_amount, parse_timestamp


class CanonicalJsonHashTest(TestCase):
    def test_same_payload_same_hash(self):
        h1 = canonical_json_hash("vendor1", {"a": 1, "b": 2})
        h2 = canonical_json_hash("vendor1", {"a": 1, "b": 2})
        self.assertEqual(h1, h2)

    def test_different_key_order_same_hash(self):
        h1 = canonical_json_hash("vendor1", {"b": 2, "a": 1})
        h2 = canonical_json_hash("vendor1", {"a": 1, "b": 2})
        self.assertEqual(h1, h2)

    def test_different_user_different_hash(self):
        h1 = canonical_json_hash("vendor1", {"a": 1})
        h2 = canonical_json_hash("vendor2", {"a": 1})
        self.assertNotEqual(h1, h2)

    def test_different_payload_different_hash(self):
        h1 = canonical_json_hash("vendor1", {"a": 1})
        h2 = canonical_json_hash("vendor1", {"a": 2})
        self.assertNotEqual(h1, h2)

    def test_nested_objects_same_hash(self):
        h1 = canonical_json_hash("v", {"a": {"c": 3, "b": 2}})
        h2 = canonical_json_hash("v", {"a": {"b": 2, "c": 3}})
        self.assertEqual(h1, h2)

    def test_hash_length(self):
        h = canonical_json_hash("v", {"test": True})
        self.assertEqual(len(h), 64)


class NormalizeStatusTest(TestCase):
    def test_valid_statuses(self):
        self.assertEqual(normalize_status("TRANSIT"), "TRANSIT")
        self.assertEqual(normalize_status("DELIVERED"), "DELIVERED")
        self.assertEqual(normalize_status("EXCEPTION"), "EXCEPTION")

    def test_variant_mappings(self):
        self.assertEqual(normalize_status("shipped"), "TRANSIT")
        self.assertEqual(normalize_status("completed"), "DELIVERED")
        self.assertEqual(normalize_status("lost"), "EXCEPTION")

    def test_none_and_unknown(self):
        self.assertIsNone(normalize_status(None))
        self.assertIsNone(normalize_status("UNKNOWN"))


class ParseTimestampTest(TestCase):
    def test_valid_iso(self):
        self.assertIsInstance(parse_timestamp("2024-01-15T10:30:00Z"), datetime)

    def test_invalid(self):
        self.assertIsNone(parse_timestamp("not-a-date"))
        self.assertIsNone(parse_timestamp(None))


class ParseAmountTest(TestCase):
    def test_valid(self):
        self.assertEqual(parse_amount(100.50), Decimal("100.50"))
        self.assertEqual(parse_amount("99.99"), Decimal("99.99"))

    def test_invalid(self):
        self.assertIsNone(parse_amount(-50))
        self.assertIsNone(parse_amount("abc"))
        self.assertIsNone(parse_amount(None))
