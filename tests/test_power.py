from __future__ import annotations

import unittest

from rau.power import comparison, summarize


class PowerAcceptanceTests(unittest.TestCase):
    def test_summary_uses_median_and_wakeup_rate(self):
        report = summarize(
            pid=10,
            label="after",
            started_at=100.0,
            ended_at=110.0,
            samples=[
                {"cpu_percent": 1.0, "rss_kib": 1024, "pids": [10]},
                {"cpu_percent": 3.0, "rss_kib": 3072, "pids": [10, 11]},
                {"cpu_percent": 2.0, "rss_kib": 2048, "pids": [10]},
            ],
            wakeup_deltas={10: 15, 11: 5},
        )
        self.assertEqual(report["median_cpu_percent"], 2.0)
        self.assertEqual(report["mean_rss_mib"], 2.0)
        self.assertEqual(report["wakeups_per_sec"], 2.0)
        self.assertEqual(report["observed_pids"], [10, 11])

    def test_comparison_enforces_half_reduction_for_available_metrics(self):
        result = comparison(
            {"label": "before", "median_cpu_percent": 4, "wakeups_per_sec": 10},
            {"label": "after", "median_cpu_percent": 2, "wakeups_per_sec": 4},
        )
        self.assertEqual(result["median_cpu_reduction_percent"], 50.0)
        self.assertEqual(result["wakeup_reduction_percent"], 60.0)
        self.assertTrue(result["passes_available_metrics"])


if __name__ == "__main__":
    unittest.main()
