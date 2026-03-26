from __future__ import annotations

import unittest

from spendinggovua_api.analytics import build_reports_summary


def make_item(edrpou: str, year: int | None, report_type: str) -> dict[str, object]:
    return {
        "edrpou": edrpou,
        "year": year,
        "reportTypeShortName": report_type,
        "reportName": report_type,
    }


class BuildReportsSummaryTests(unittest.TestCase):
    def test_builds_counts_and_series(self) -> None:
        items = [
            make_item("11111111", 2024, "Form 2"),
            make_item("11111111", 2024, "Form 7"),
            make_item("22222222", 2025, "Form 2"),
        ]

        summary = build_reports_summary(items, returned_reports=2)

        self.assertEqual(summary["total_reports"], 3)
        self.assertEqual(summary["returned_reports"], 2)
        self.assertEqual(summary["by_year"], {"2025": 1, "2024": 2})
        self.assertEqual(summary["by_type"], {"Form 2": 2, "Form 7": 1})
        self.assertEqual(summary["by_edrpou"], {"11111111": 2, "22222222": 1})
        self.assertEqual(
            summary["by_edrpou_and_year"],
            {
                "11111111": {"2024": 2},
                "22222222": {"2025": 1},
            },
        )
        self.assertEqual(
            summary["series"]["reports_by_year"],
            [
                {"label": "2024", "count": 2},
                {"label": "2025", "count": 1},
            ],
        )
        self.assertEqual(
            summary["series"]["reports_by_type"],
            [
                {"label": "Form 2", "count": 2},
                {"label": "Form 7", "count": 1},
            ],
        )
        self.assertEqual(
            summary["series"]["reports_by_edrpou_top"],
            [
                {"label": "11111111", "count": 2},
                {"label": "22222222", "count": 1},
            ],
        )
        self.assertEqual(
            summary["series"]["reports_by_year_and_type"],
            {
                "labels": ["2024", "2025"],
                "datasets": [
                    {"label": "Form 2", "data": [1, 1]},
                    {"label": "Form 7", "data": [1, 0]},
                ],
            },
        )

    def test_limits_top_edrpou_series_to_ten(self) -> None:
        items = [make_item(f"{index:08d}", 2025, "Form 2") for index in range(12)]

        summary = build_reports_summary(items)

        self.assertEqual(len(summary["series"]["reports_by_edrpou_top"]), 10)
        self.assertEqual(summary["series"]["reports_by_edrpou_top"][0]["label"], "00000000")

    def test_handles_empty_inputs(self) -> None:
        summary = build_reports_summary([], returned_reports=0)

        self.assertEqual(summary["total_reports"], 0)
        self.assertEqual(summary["returned_reports"], 0)
        self.assertEqual(summary["by_year"], {})
        self.assertEqual(summary["by_type"], {})
        self.assertEqual(summary["by_edrpou"], {})
        self.assertEqual(summary["by_edrpou_and_year"], {})
        self.assertEqual(summary["series"]["reports_by_year"], [])
        self.assertEqual(summary["series"]["reports_by_type"], [])
        self.assertEqual(summary["series"]["reports_by_edrpou_top"], [])
        self.assertEqual(
            summary["series"]["reports_by_year_and_type"],
            {"labels": [], "datasets": []},
        )
