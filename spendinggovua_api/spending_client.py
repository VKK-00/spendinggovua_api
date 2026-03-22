from __future__ import annotations

import asyncio
from datetime import date
import json
import re
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from spendinggovua_api.models import SearchReportsRequest
from spendinggovua_api.report_render import build_report_html
from spendinggovua_api.settings import Settings


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


def extract_period_bounds(period: dict[str, Any] | None) -> tuple[date | None, date | None]:
    if not period:
        return None, None

    start = period.get("from")
    end = period.get("to")

    try:
        start_date = date.fromisoformat(start) if isinstance(start, str) else None
    except ValueError:
        start_date = None

    try:
        end_date = date.fromisoformat(end) if isinstance(end, str) else None
    except ValueError:
        end_date = None

    return start_date, end_date


def extract_form_codes(value: str | None, *, require_form_word: bool = False) -> set[str]:
    text = normalize_text(value)
    if not text:
        return set()
    if require_form_word and "форма" not in text and "form" not in text:
        return set()

    normalized = text.replace("д", "d").replace("м", "m").replace("№", " ")
    return {
        match.group(1)
        for match in re.finditer(r"(?<![\d.-])(\d+(?:[.-]\d+)?(?:[dm])?)(?![\d])", normalized)
    }


def form_codes_match(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    return re.sub(r"[dm]$", "", expected) == re.sub(r"[dm]$", "", actual)


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
        self._report_view_cache = TTLCache(settings.cache_ttl_seconds)

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

    async def get_report_view_data(self, edrpou: str, report_id: int) -> dict[str, Any]:
        normalized = normalize_edrpou(edrpou)
        cached = self._report_view_cache.get((normalized, int(report_id)))
        if cached is not None:
            return cached

        page = await self._new_page()
        try:
            await page.goto(
                self._settings.report_details_page(normalized, int(report_id)),
                wait_until="domcontentloaded",
            )
            await page.locator("table.report-table-width").last.wait_for()
            payload = await page.evaluate(
                """
                () => {
                  const table =
                    document.querySelectorAll("table.report-table-width")[1] ||
                    document.querySelector("table.report-table-width");
                  const text = (node) => (node?.textContent || "").replace(/\\s+/g, " ").trim();
                  const signedBlock = text(document.querySelector(".report-item-signature"));
                  const notationText = text(document.querySelector(".report_table_notation"));
                  return {
                    source_url: window.location.href,
                    signed_at: signedBlock.replace(/^Підписано\\s*/i, "").replace(/перевірити підпис.*/i, "").trim(),
                    title: text(document.querySelector(".report__view__head")),
                    name: text(document.querySelector(".report__view__name")),
                    period: text(document.querySelector(".report__view__period")),
                    codes: Array.from(document.querySelectorAll(".report__view__code")).map(text).filter(Boolean),
                    fields: Array.from(document.querySelectorAll(".report__view__field")).map((field) => ({
                      name: text(field.querySelector(".report__view__field__name")),
                      value: text(field.querySelector(".report__view__field__underline")),
                    })),
                    notation: notationText
                      ? notationText.split(/(?<=\\.)\\s+/).map((item) => item.trim()).filter(Boolean)
                      : [],
                    table: table
                      ? {
                          header_rows: Array.from(table.querySelectorAll("thead tr")).map((row) =>
                            Array.from(row.querySelectorAll("th,td")).map(text)
                          ),
                          body_rows: Array.from(table.querySelectorAll("tbody tr")).map((row) =>
                            Array.from(row.querySelectorAll("th,td")).map(text)
                          ),
                        }
                      : { header_rows: [], body_rows: [] },
                  };
                }
                """
            )
        finally:
            await page.close()

        if not payload["table"]["body_rows"]:
            raise SpendingGovError(
                f"Не вдалося витягнути табличне представлення звіту для ЄДРПОУ {normalized}, reportId={report_id}."
            )

        self._report_view_cache.set((normalized, int(report_id)), payload)
        return payload

    async def render_report_html(self, edrpou: str, report_id: int) -> str:
        report = await self.get_report_view_data(edrpou, report_id)
        return build_report_html(report)

    async def render_report_pdf(self, edrpou: str, report_id: int) -> bytes:
        html = await self.render_report_html(edrpou, report_id)
        context = await self._ensure_browser()
        page = await context.new_page()
        try:
            await page.set_content(html, wait_until="load")
            pdf_bytes = await page.pdf(
                format="A4",
                landscape=True,
                print_background=True,
                prefer_css_page_size=True,
            )
        finally:
            await page.close()
        return pdf_bytes

    async def search_reports(self, request: SearchReportsRequest) -> dict[str, Any]:
        result, _all_items, _errors = await self._collect_reports(
            request,
            ignore_errors=False,
        )
        return result

    async def search_reports_partial(self, request: SearchReportsRequest) -> dict[str, Any]:
        result, _items, errors = await self._collect_reports(
            request,
            ignore_errors=True,
        )
        result["errors"] = errors
        return result

    async def summarize_report_types(self, request: SearchReportsRequest) -> dict[str, Any]:
        base_request = request.model_copy(
            update={
                "report_type_ids": [],
                "report_types": [],
                "include_details": False,
                "max_reports": None,
            }
        )
        result = await self.search_reports_partial(base_request)

        counts_by_type: Counter[str] = Counter()
        edrpous_by_type: dict[str, set[str]] = defaultdict(set)
        years_by_type: dict[str, Counter[int]] = defaultdict(Counter)

        for item in result["items"]:
            type_name = (
                item.get("reportTypeShortName")
                or item.get("reportName")
                or "Невідомий тип"
            )
            edrpou = str(item.get("edrpou") or "")
            year = item.get("year")

            counts_by_type[type_name] += 1
            if edrpou:
                edrpous_by_type[type_name].add(edrpou)
            if isinstance(year, int):
                years_by_type[type_name][year] += 1

        result["types"] = [
            {
                "name": type_name,
                "reports_count": counts_by_type[type_name],
                "edrpous_count": len(edrpous_by_type[type_name]),
                "edrpous": sorted(edrpous_by_type[type_name]),
                "by_year": dict(
                    sorted(
                        (
                            (str(year), count)
                            for year, count in years_by_type[type_name].items()
                        ),
                        reverse=True,
                    )
                ),
            }
            for type_name, _count in sorted(
                counts_by_type.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]
        return result

    async def _collect_reports(
        self,
        request: SearchReportsRequest,
        *,
        ignore_errors: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]]]:
        edrpous = self._collect_edrpous(request)
        all_items: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        for edrpou in edrpous:
            try:
                catalog, reports = await self._load_catalog_and_reports(edrpou, request.sign_status)
            except SpendingGovError as exc:
                detail = await self._enhance_collect_error(edrpou, exc)
                if not ignore_errors:
                    raise SpendingGovError(detail) from exc
                errors.append({"edrpou": edrpou, "detail": detail})
                continue

            filtered = self._filter_reports(
                reports=reports,
                catalog=catalog,
                years=set(request.years),
                date_from=request.date_from,
                date_to=request.date_to,
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
                "date_from": request.date_from.isoformat() if request.date_from else None,
                "date_to": request.date_to.isoformat() if request.date_to else None,
                "report_type_ids": request.report_type_ids,
                "report_types": request.report_types,
                "sign_status": request.sign_status,
                "include_details": request.include_details,
                "max_reports": request.max_reports,
            },
            "summary": self._build_summary(all_items),
            "items": all_items,
        }, all_items, errors

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
        date_from: date | None,
        date_to: date | None,
        report_type_ids: set[int],
        report_types: set[str],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for raw_report in reports:
            period = catalog["periods"].get(int(raw_report["periodId"]))
            year = extract_year(period)
            period_start, period_end = extract_period_bounds(period)
            report_type_id = int(raw_report["reportTypeId"])
            report_type_short_name = catalog["report_type_map"].get(
                str(report_type_id),
                raw_report.get("reportName") or "Невідомий тип",
            )
            if years and (year is None or year not in years):
                continue
            if date_from and period_end and period_end < date_from:
                continue
            if date_to and period_start and period_start > date_to:
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
        actual_codes = extract_form_codes(short_name) | extract_form_codes(
            raw_report.get("reportName"),
            require_form_word=True,
        )
        for expected in filters:
            expected_codes = extract_form_codes(expected)
            if expected == full_name or expected == short:
                return True
            if expected_codes and actual_codes:
                for expected_code in expected_codes:
                    for actual_code in actual_codes:
                        if form_codes_match(expected_code, actual_code):
                            return True
                continue
            if expected and len(expected) >= 3 and (expected in full_name or expected in short):
                return True
        return False

    async def _enhance_collect_error(self, edrpou: str, exc: SpendingGovError) -> str:
        message = str(exc)
        if "HTTP 500" not in message:
            return message
        details = await self._inspect_reports_page(edrpou)
        final_section = details["final_section"]
        final_url = details["final_url"]

        if final_section != "reports":
            return (
                f"Портал не відкрив розділ звітів для ЄДРПОУ {edrpou}: "
                f"після переходу до reports перенаправляє на {final_section or final_url}. "
                f"Початковий запит завершився HTTP 500."
            )
        if details["has_oops"]:
            return (
                f"Портал відкриває сторінку звітів для ЄДРПОУ {edrpou} з помилкою Oooooooops!. "
                f"Початковий запит завершився HTTP 500."
            )
        return message

    async def _inspect_reports_page(self, edrpou: str) -> dict[str, Any]:
        page = await self._new_page()
        try:
            await page.goto(
                self._settings.disposer_reports_page(edrpou),
                wait_until="domcontentloaded",
            )
            await page.wait_for_timeout(2_000)
            final_url = page.url
            body_text = normalize_text(await page.locator("body").inner_text())
        finally:
            await page.close()

        path = final_url.removeprefix(self._settings.base_url)
        parts = [part for part in path.split("/") if part]
        final_section = parts[-1] if parts else ""

        return {
            "final_url": final_url,
            "final_section": final_section,
            "has_oops": "oooooooops" in body_text or "помилка" in body_text,
        }

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
