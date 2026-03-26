from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _report_type_name(item: dict[str, Any]) -> str:
    return str(item.get("reportTypeShortName") or item.get("reportName") or "Unknown type")


def _edrpou_name(item: dict[str, Any]) -> str:
    return str(item.get("edrpou") or "unknown")


def build_reports_summary(
    items: list[dict[str, Any]],
    *,
    returned_reports: int | None = None,
) -> dict[str, Any]:
    by_year: Counter[int] = Counter()
    by_type: Counter[str] = Counter()
    by_edrpou: Counter[str] = Counter()
    by_year_and_type: dict[int, Counter[str]] = defaultdict(Counter)
    by_edrpou_and_year: dict[str, Counter[int]] = defaultdict(Counter)

    for item in items:
        year = item.get("year")
        report_type_name = _report_type_name(item)
        edrpou = _edrpou_name(item)

        by_type[report_type_name] += 1
        by_edrpou[edrpou] += 1

        if isinstance(year, int):
            by_year[year] += 1
            by_year_and_type[year][report_type_name] += 1
            by_edrpou_and_year[edrpou][year] += 1

    sorted_years_desc = sorted(by_year.keys(), reverse=True)
    sorted_years_asc = sorted(by_year.keys())
    sorted_types = sorted(by_type.items(), key=lambda item: (-item[1], item[0]))
    sorted_edrpous = sorted(by_edrpou.items(), key=lambda item: item[0])
    top_edrpous = sorted(by_edrpou.items(), key=lambda item: (-item[1], item[0]))[:10]

    return {
        "total_reports": len(items),
        "returned_reports": returned_reports if returned_reports is not None else len(items),
        "by_year": {str(year): by_year[year] for year in sorted_years_desc},
        "by_type": dict(sorted_types),
        "by_edrpou": dict(sorted_edrpous),
        "by_edrpou_and_year": {
            edrpou: {
                str(year): year_counter[year]
                for year in sorted(year_counter.keys(), reverse=True)
            }
            for edrpou, year_counter in sorted(by_edrpou_and_year.items())
        },
        "series": {
            "reports_by_year": [
                {"label": str(year), "count": by_year[year]}
                for year in sorted_years_asc
            ],
            "reports_by_type": [
                {"label": label, "count": count}
                for label, count in sorted_types
            ],
            "reports_by_edrpou_top": [
                {"label": label, "count": count}
                for label, count in top_edrpous
            ],
            "reports_by_year_and_type": {
                "labels": [str(year) for year in sorted_years_asc],
                "datasets": [
                    {
                        "label": type_name,
                        "data": [by_year_and_type[year].get(type_name, 0) for year in sorted_years_asc],
                    }
                    for type_name, _count in sorted_types
                ],
            },
        },
    }
