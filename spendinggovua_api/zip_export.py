from __future__ import annotations

from collections import defaultdict
from datetime import datetime, UTC
from io import BytesIO
import json
import re
import zipfile
from typing import Any


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug or "reports-export"


def _report_filename(item: dict[str, Any], index: int) -> str:
    year = item.get("year") or "unknown-year"
    publish_date = item.get("publishDate") or "unknown-date"
    report_id = item.get("reportId") or index
    return f"{year}_{publish_date}_report-{report_id}.json"


def _latest_only(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    picked: dict[str, dict[str, Any]] = {}
    for item in items:
        edrpou = str(item.get("edrpou") or "")
        if edrpou not in picked:
            picked[edrpou] = item
    return list(picked.values())


def build_reports_zip(
    *,
    query: dict[str, Any],
    summary: dict[str, Any],
    items: list[dict[str, Any]],
    errors: list[dict[str, str]] | None,
    latest_only_per_edrpou: bool,
    archive_name: str | None,
) -> tuple[bytes, str]:
    export_items = _latest_only(items) if latest_only_per_edrpou else list(items)

    requested_edrpous = [str(item) for item in query.get("edrpous", [])]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in export_items:
        grouped[str(item.get("edrpou"))].append(item)

    errors_map = {
        str(item.get("edrpou")): str(item.get("detail") or "Unknown export error.")
        for item in (errors or [])
        if item.get("edrpou")
    }
    without_reports = [
        edrpou
        for edrpou in requested_edrpous
        if edrpou not in grouped and edrpou not in errors_map
    ]
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    manifest = {
        "generated_at": generated_at,
        "query": query,
        "summary": summary,
        "latest_only_per_edrpou": latest_only_per_edrpou,
        "requested_edrpous": requested_edrpous,
        "edrpous_with_reports": sorted(grouped.keys()),
        "edrpous_with_errors": sorted(errors_map.keys()),
        "edrpous_without_reports": without_reports,
        "errors": [
            {"edrpou": edrpou, "detail": detail}
            for edrpou, detail in sorted(errors_map.items())
        ],
        "total_exported_reports": len(export_items),
    }

    base_name = _slugify(archive_name or f"reports-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    zip_name = f"{base_name}.zip"

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )

        for edrpou in requested_edrpous:
            folder = f"{edrpou}/"
            reports = grouped.get(edrpou, [])
            if edrpou in errors_map:
                archive.writestr(
                    f"{folder}error.json",
                    json.dumps(
                        {
                            "edrpou": edrpou,
                            "message": "Не вдалося отримати звіти по цьому ЄДРПОУ.",
                            "detail": errors_map[edrpou],
                            "query": query,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if not reports:
                archive.writestr(
                    f"{folder}no_reports.json",
                    json.dumps(
                        {
                            "edrpou": edrpou,
                            "message": "По цьому ЄДРПОУ звітів за заданими фільтрами не знайдено.",
                            "query": query,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            archive.writestr(
                f"{folder}index.json",
                json.dumps(
                    {
                        "edrpou": edrpou,
                        "reports_count": len(reports),
                        "report_ids": [item.get("reportId") for item in reports],
                        "reports": [
                            {
                                "reportId": item.get("reportId"),
                                "reportName": item.get("reportName"),
                                "reportTypeShortName": item.get("reportTypeShortName"),
                                "year": item.get("year"),
                                "period": item.get("period", {}).get("name"),
                                "publishDate": item.get("publishDate"),
                            }
                            for item in reports
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )

            for index, item in enumerate(reports, start=1):
                archive.writestr(
                    f"{folder}{_report_filename(item, index)}",
                    json.dumps(item, ensure_ascii=False, indent=2),
                )

    buffer.seek(0)
    return buffer.getvalue(), zip_name
