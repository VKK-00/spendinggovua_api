from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.models import SearchReportsRequest
from app.settings import Settings


class SpendingGovError(RuntimeError):
    pass


@dataclass(slots=True)
class CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._data: dict[Any, CacheEntry] = {}

    def get(self, key: Any) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        if time.monotonic() >= entry.expires_at:
            self._data.pop(key, None)
            return None
        return entry.value

    def set(self, key: Any, value: Any) -> None:
        self._data[key] = CacheEntry(
            value=value,
            expires_at=time.monotonic() + self._ttl_seconds,
        )


def normalize_edrpou(value: str) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if not digits:
        raise SpendingGovError("ЄДРПОУ має містити цифри.")
    return digits


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"\s+", " ", text).strip()


def extract_year(period: dict[str, Any] | None) -> int | None:
    if not period:
        return None
    date_value = period.get("from") or period.get("to")
    if isinstance(date_value, str) and len(date_value) >= 4 and date_value[:4].isdigit():
        return int(date_value[:4])
    return None


class SpendingGovClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._browser_lock = asyncio.Lock()
        self._catalog_cache = TTLCache(settings.cache_ttl_seconds)
        self._reports_cache = TTLCache(settings.cache_ttl_seconds)
        self._details_cache = TTLCache(settings.cache_ttl_seconds)

    @property
    def started(self) -> bool:
        return self._context is not None

    async def start(self) -> None:
        await self._ensure_browser()

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def get_catalog(self, edrpou: str, sign_status: str = "signed") -> dict[str, Any]:
        normalized = normalize_edrpou(edrpou)
        catalog = self._catalog_cache.get(normalized)
        reports = self._reports_cache.get((normalized, sign_status))
        if catalog is not None:
            return self._catalog_with_report_counts(catalog, reports or [])
        catalog, reports = await self._load_catalog_and_reports(normalized, sign_status)
        return self._catalog_with_report_counts(catalog, reports)

    async def search_reports(self, request: SearchReportsRequest) -> dict[str, Any]:
        edrpous = self._collect_edrpous(request)
        all_items: list[dict[str, Any]] = []

        for edrpou in edrpous:
            catalog, reports = await self._load_catalog_and_reports(edrpou, request.sign_status)
            filtered = self._filter_reports(
                reports=reports,
                catalog=catalog,
                years=set(request.years),
                report_type_ids=set(request.report_type_ids),
                report_types={normalize_text(item) for item in request.report_types if item},
            )
            all_items.extend(filtered)

        all_items.sort(
            key=lambda item: (
                item.get("publishDate") or "",
                item.get("createDate") or "",
                item.get("reportId") or 0,
            ),
            reverse=True,
        )

        if request.max_reports is not None:
            all_items = all_items[: request.max_reports]

        if request.include_details and all_items:
            await self._attach_details(all_items)

        return {
            "query": {
                "edrpous": edrpous,
                "years": request.years,
                "report_type_ids": request.report_type_ids,
                "report_types": request.report_types,
                "sign_status": request.sign_status,
                "include_details": request.include_details,
                "max_reports": request.max_reports,
            },
            "summary": self._build_summary(all_items),
            "items": all_items,
        }

    async def _ensure_browser(self) -> BrowserContext:
        async with self._browser_lock:
            if self._context is not None:
                return self._context

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self._settings.browser_headless,
            )
            self._context = await self._browser.new_context(
                locale="uk-UA",
                user_agent=self._settings.browser_user_agent,
                viewport={"width": 1440, "height": 960},
            )
            self._context.set_default_timeout(self._settings.browser_timeout_ms)
            return self._context

    async def _new_page(self) -> Page:
        context = await self._ensure_browser()
        page = await context.new_page()
        await page.goto(
            self._settings.login_page_url,
            wait_until="domcontentloaded",
        )
        return page

    async def _load_catalog_and_reports(
        self,
        edrpou: str,
        sign_status: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        cached_catalog = self._catalog_cache.get(edrpou)
        cached_reports = self._reports_cache.get((edrpou, sign_status))
        if cached_catalog is not None and cached_reports is not None:
            return cached_catalog, cached_reports

        page = await self._new_page()
        try:
            payload = await page.evaluate(
                """
                async ({ periodsUrl, reportTypesUrl, listUrl }) => {
                  const [periodsResponse, reportTypesResponse, listResponse] = await Promise.all([
                    fetch(periodsUrl, { credentials: "include" }),
                    fetch(reportTypesUrl, { credentials: "include" }),
                    fetch(listUrl, { credentials: "include" }),
                  ]);
                  return {
                    periods: {
                      ok: periodsResponse.ok,
                      status: periodsResponse.status,
                      text: await periodsResponse.text(),
                    },
                    reportTypes: {
                      ok: reportTypesResponse.ok,
                      status: reportTypesResponse.status,
                      text: await reportTypesResponse.text(),
                    },
                    reports: {
                      ok: listResponse.ok,
                      status: listResponse.status,
                      text: await listResponse.text(),
                    }
                  };
                }
                """,
                {
                    "periodsUrl": self._settings.periods_api,
                    "reportTypesUrl": self._settings.report_types_api,
                    "listUrl": self._settings.reports_page_api(
                        edrpou,
                        sign_status=sign_status,
                    )
                },
            )
        finally:
            await page.close()

        if not payload["periods"]["ok"]:
            raise SpendingGovError(
                "Не вдалося отримати список періодів зі spending.gov.ua. "
                f"HTTP {payload['periods']['status']}."
            )
        if not payload["reportTypes"]["ok"]:
            raise SpendingGovError(
                "Не вдалося отримати типи звітів зі spending.gov.ua. "
                f"HTTP {payload['reportTypes']['status']}."
            )
        if not payload["reports"]["ok"]:
            raise SpendingGovError(
                "Не вдалося отримати список звітів зі spending.gov.ua. "
                f"HTTP {payload['reports']['status']}."
            )

        periods = json.loads(payload["periods"]["text"])
        report_types = json.loads(payload["reportTypes"]["text"])
        reports_page = json.loads(payload["reports"]["text"])
        reports = reports_page.get("content", [])
        catalog = self._build_catalog(
            edrpou=edrpou,
            periods=periods,
            report_types=report_types,
        )
        self._catalog_cache.set(edrpou, catalog)
        self._reports_cache.set((edrpou, sign_status), reports)
        return catalog, reports

    def _build_catalog(
        self,
        edrpou: str,
        periods: list[dict[str, Any]],
        report_types: list[dict[str, Any]],
    ) -> dict[str, Any]:
        period_map: dict[int, dict[str, Any]] = {}
        years: set[int] = set()
        for raw_period in periods:
            period = {
                "id": raw_period.get("id"),
                "name": raw_period.get("name"),
                "from": raw_period.get("from"),
                "to": raw_period.get("to"),
                "type": raw_period.get("type"),
            }
            year = extract_year(raw_period)
            if year is not None:
                years.add(year)
                period["year"] = year
            if period["id"] is not None:
                period_map[int(period["id"])] = period

        report_type_map: dict[str, str] = {}
        grouped_type_ids: dict[str, set[int]] = defaultdict(set)
        groups_payload: list[dict[str, Any]] = []
        for report_type in report_types:
            report_type_id = int(report_type["id"])
            short_name = report_type.get("shortName") or report_type.get("name") or f"Тип {report_type_id}"
            report_type_map[str(report_type_id)] = short_name
            grouped_type_ids[short_name].add(report_type_id)

        for name, type_ids in sorted(grouped_type_ids.items()):
            groups_payload.append(
                {
                    "name": name,
                    "report_type_ids": sorted(type_ids),
                }
            )

        return {
            "edrpou": edrpou,
            "available_years": sorted(years, reverse=True),
            "periods": period_map,
            "report_type_groups": groups_payload,
            "report_type_map": report_type_map,
        }

    def _catalog_with_report_counts(
        self,
        catalog: dict[str, Any],
        reports: list[dict[str, Any]],
    ) -> dict[str, Any]:
        type_counts: Counter[str] = Counter()
        year_counts: Counter[int] = Counter()
        for report in reports:
            report_type_name = catalog["report_type_map"].get(
                str(report.get("reportTypeId")),
                report.get("reportName") or "Невідомий тип",
            )
            type_counts[report_type_name] += 1
            period = catalog["periods"].get(int(report.get("periodId")))
            year = extract_year(period)
            if year is not None:
                year_counts[year] += 1

        groups = []
        for group in catalog["report_type_groups"]:
            groups.append(
                {
                    **group,
                    "reports_count": type_counts.get(group["name"], 0),
                }
            )

        return {
            "edrpou": catalog["edrpou"],
            "available_years": sorted(year_counts.keys(), reverse=True),
            "report_type_groups": groups,
            "report_type_map": catalog["report_type_map"],
        }

    def _collect_edrpous(self, request: SearchReportsRequest) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for raw_value in [request.edrpou, *request.edrpous]:
            if raw_value is None:
                continue
            normalized = normalize_edrpou(raw_value)
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _filter_reports(
        self,
        reports: list[dict[str, Any]],
        catalog: dict[str, Any],
        years: set[int],
        report_type_ids: set[int],
        report_types: set[str],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for raw_report in reports:
            period = catalog["periods"].get(int(raw_report["periodId"]))
            year = extract_year(period)
            report_type_id = int(raw_report["reportTypeId"])
            report_type_short_name = catalog["report_type_map"].get(
                str(report_type_id),
                raw_report.get("reportName") or "Невідомий тип",
            )
            if years and (year is None or year not in years):
                continue
            if report_type_ids and report_type_id not in report_type_ids:
                continue
            if report_types and not self._matches_report_type(
                raw_report=raw_report,
                short_name=report_type_short_name,
                filters=report_types,
            ):
                continue

            item = dict(raw_report)
            item["year"] = year
            item["period"] = period
            item["reportTypeShortName"] = report_type_short_name
            items.append(item)
        return items

    def _matches_report_type(
        self,
        raw_report: dict[str, Any],
        short_name: str,
        filters: set[str],
    ) -> bool:
        full_name = normalize_text(raw_report.get("reportName"))
        short = normalize_text(short_name)
        for expected in filters:
            if expected == full_name or expected == short:
                return True
            if expected and (expected in full_name or expected in short):
                return True
        return False

    async def _attach_details(self, items: list[dict[str, Any]]) -> None:
        grouped: dict[str, list[int]] = defaultdict(list)
        for item in items:
            edrpou = normalize_edrpou(item["edrpou"])
            report_id = int(item["reportId"])
            grouped[edrpou].append(report_id)

        details_map: dict[tuple[str, int], dict[str, Any]] = {}
        for edrpou, report_ids in grouped.items():
            missing_ids = [
                report_id
                for report_id in report_ids
                if self._details_cache.get((edrpou, report_id)) is None
            ]
            if missing_ids:
                page = await self._new_page()
                try:
                    response_payload = await page.evaluate(
                        """
                        async ({ urls }) => {
                          const responses = await Promise.all(
                            urls.map(async ({ reportId, url }) => {
                              const response = await fetch(url, { credentials: "include" });
                              const text = await response.text();
                              return {
                                reportId,
                                ok: response.ok,
                                status: response.status,
                                text,
                              };
                            })
                          );
                          return responses;
                        }
                        """,
                        {
                            "urls": [
                                {
                                    "reportId": report_id,
                                    "url": self._settings.report_details_api(edrpou, report_id),
                                }
                                for report_id in missing_ids
                            ]
                        },
                    )
                finally:
                    await page.close()

                for payload in response_payload:
                    if not payload["ok"]:
                        raise SpendingGovError(
                            "Не вдалося отримати деталі звіту зі spending.gov.ua. "
                            f"HTTP {payload['status']} для reportId={payload['reportId']}."
                        )
                    details = json.loads(payload["text"])
                    self._details_cache.set((edrpou, int(payload["reportId"])), details)

            for report_id in report_ids:
                details = self._details_cache.get((edrpou, report_id))
                if details is not None:
                    details_map[(edrpou, report_id)] = details

        for item in items:
            key = (normalize_edrpou(item["edrpou"]), int(item["reportId"]))
            if key in details_map:
                item["details"] = details_map[key]

    def _build_summary(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        by_year = Counter()
        by_type = Counter()
        by_edrpou = Counter()
        by_edrpou_and_year: dict[str, Counter[int]] = defaultdict(Counter)

        for item in items:
            year = item.get("year")
            report_type_name = item.get("reportTypeShortName") or item.get("reportName") or "Невідомий тип"
            edrpou = item.get("edrpou") or "unknown"

            if year is not None:
                by_year[str(year)] += 1
                by_edrpou_and_year[str(edrpou)][int(year)] += 1
            by_type[str(report_type_name)] += 1
            by_edrpou[str(edrpou)] += 1

        return {
            "total_reports": len(items),
            "by_year": dict(sorted(by_year.items(), reverse=True)),
            "by_type": dict(sorted(by_type.items(), key=lambda item: (-item[1], item[0]))),
            "by_edrpou": dict(sorted(by_edrpou.items(), key=lambda item: item[0])),
            "by_edrpou_and_year": {
                edrpou: dict(sorted(((str(year), count) for year, count in year_counter.items()), reverse=True))
                for edrpou, year_counter in sorted(by_edrpou_and_year.items())
            },
        }
