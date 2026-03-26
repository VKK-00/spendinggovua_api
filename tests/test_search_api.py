from __future__ import annotations

import unittest
from types import SimpleNamespace

from spendinggovua_api.main import search_reports
from spendinggovua_api.models import SearchReportsRequest
from spendinggovua_api.settings import Settings
from spendinggovua_api.spending_client import SpendingGovClient


class StubSpendingGovClient(SpendingGovClient):
    async def _load_catalog_and_reports(
        self,
        edrpou: str,
        sign_status: str,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        periods = [
            {
                "id": 1,
                "name": "2024 year",
                "from": "2024-01-01",
                "to": "2024-12-31",
                "type": {"id": 1, "name": "year"},
            },
            {
                "id": 2,
                "name": "2025 year",
                "from": "2025-01-01",
                "to": "2025-12-31",
                "type": {"id": 1, "name": "year"},
            },
        ]
        report_types = [{"id": 59, "shortName": "Form 2"}]
        reports = [
            {
                "reportId": 10,
                "periodId": 1,
                "reportTypeId": 59,
                "reportName": "Form 2",
                "publishDate": "2024-02-01",
                "createDate": "2024-02-01",
                "edrpou": edrpou,
            },
            {
                "reportId": 20,
                "periodId": 2,
                "reportTypeId": 59,
                "reportName": "Form 2",
                "publishDate": "2025-02-01",
                "createDate": "2025-02-01",
                "edrpou": edrpou,
            },
        ]
        return self._build_catalog(edrpou=edrpou, periods=periods, report_types=report_types), reports

    async def _attach_details(self, items: list[dict[str, object]]) -> None:
        for item in items:
            item["details"] = {"reportId": item["reportId"]}


class CollectReportsTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_uses_full_filtered_set_before_max_reports(self) -> None:
        client = StubSpendingGovClient(Settings())
        request = SearchReportsRequest(
            edrpous=["12345678"],
            report_types=["2"],
            include_details=True,
            max_reports=1,
        )

        result, items, errors = await client._collect_reports(request, ignore_errors=False)

        self.assertEqual(errors, [])
        self.assertEqual(result["summary"]["total_reports"], 2)
        self.assertEqual(result["summary"]["returned_reports"], 1)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(items), 1)
        self.assertIn("details", result["items"][0])
        self.assertEqual(
            result["summary"]["series"]["reports_by_year"],
            [
                {"label": "2024", "count": 1},
                {"label": "2025", "count": 1},
            ],
        )


class SearchRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_returns_extended_summary_shape(self) -> None:
        payload = {
            "query": {"edrpous": ["12345678"]},
            "summary": {
                "total_reports": 2,
                "returned_reports": 1,
                "by_year": {"2025": 2},
                "by_type": {"Form 2": 2},
                "by_edrpou": {"12345678": 2},
                "by_edrpou_and_year": {"12345678": {"2025": 2}},
                "series": {
                    "reports_by_year": [{"label": "2025", "count": 2}],
                    "reports_by_type": [{"label": "Form 2", "count": 2}],
                    "reports_by_edrpou_top": [{"label": "12345678", "count": 2}],
                    "reports_by_year_and_type": {
                        "labels": ["2025"],
                        "datasets": [{"label": "Form 2", "data": [2]}],
                    },
                },
            },
            "items": [{"edrpou": "12345678", "reportId": 20, "reportName": "Form 2"}],
        }

        class FakeClient:
            async def search_reports(self, _request: SearchReportsRequest) -> dict[str, object]:
                return payload

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(spending_client=FakeClient())
            )
        )

        response = await search_reports(
            request,
            SearchReportsRequest(edrpous=["12345678"]),
        )

        self.assertEqual(response.summary["total_reports"], 2)
        self.assertEqual(response.summary["returned_reports"], 1)
        self.assertEqual(
            response.summary["series"]["reports_by_year_and_type"]["datasets"][0]["data"],
            [2],
        )
        self.assertEqual(response.items[0]["reportId"], 20)
