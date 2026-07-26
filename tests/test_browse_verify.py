"""Credential checks for browse backends."""
from __future__ import annotations

import unittest
from unittest import mock

from rau.providers import verify


class FirecrawlVerifyTests(unittest.TestCase):
    def test_credit_usage_proves_the_key(self) -> None:
        with mock.patch.object(
            verify,
            "_get_json",
            return_value={"success": True, "data": {"remainingCredits": 1234}},
        ) as get:
            result = verify._verify_firecrawl("fc-test")
        self.assertTrue(result["ok"])
        self.assertIn("1,234", result["detail"])
        self.assertTrue(get.call_args[0][0].endswith("/v2/team/credit-usage"))
        self.assertEqual(
            get.call_args[0][1]["Authorization"], "Bearer fc-test"
        )

    def test_verify_dispatch_reaches_firecrawl(self) -> None:
        with mock.patch.object(
            verify, "_verify_firecrawl", return_value={"ok": True, "detail": "ok", "models": []}
        ) as check:
            with mock.patch.object(verify, "get_secret", return_value="fc-saved"):
                result = verify.verify("firecrawl")
        self.assertTrue(result["ok"])
        check.assert_called_once_with("fc-saved")

    def test_missing_key_is_an_honest_failure(self) -> None:
        with mock.patch.object(verify, "get_secret", return_value=""):
            result = verify.verify("firecrawl")
        self.assertFalse(result["ok"])
        self.assertIn("No key", result["detail"])


if __name__ == "__main__":
    unittest.main()
