from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path
import json
import zipfile

from app.models import SearchReportsRequest
from app.report_render import build_report_filename
from app.settings import Settings
from app.spending_client import SpendingGovClient


EDRPOUS = [
    "26408431",
    "24983020",
    "02125473",
    "00374350",
    "43997335",
    "26614030",
    "02137097",
    "43021411",
    "26249278",
    "01127799",
    "43861328",
    "20933314",
    "02071033",
    "02214254",
    "00493008",
    "08571570",
    "26006260",
    "39686840",
    "02071079",
    "02010801",
    "01127777",
    "02071062",
    "02071091",
    "43199338",
    "42084287",
    "42400178",
]

ARCHIVE_NAME = "forma-2-all-mentioned-edrpou-html.zip"
OUTPUT_DIR = Path("output")
CONCURRENCY = 5


async def render_report(
    client: SpendingGovClient,
    semaphore: asyncio.Semaphore,
    item: dict[str, object],
) -> dict[str, object]:
    edrpou = str(item["edrpou"])
    report_id = int(item["reportId"])

    async with semaphore:
        html = await client.render_report_html(edrpou, report_id)

    return {
        "edrpou": edrpou,
        "report_id": report_id,
        "filename": build_report_filename(edrpou, report_id, "html"),
        "html": html,
        "meta": {
            "reportId": report_id,
            "reportTypeShortName": item.get("reportTypeShortName"),
            "reportName": item.get("reportName"),
            "publishDate": item.get("publishDate"),
            "year": item.get("year"),
            "period": (item.get("period") or {}).get("name"),
            "budget": item.get("budget"),
            "fund": item.get("fund"),
            "progKlasCod": item.get("progKlasCod"),
            "progKlas": item.get("progKlas"),
        },
    }


async def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    archive_path = OUTPUT_DIR / ARCHIVE_NAME

    client = SpendingGovClient(Settings())
    await client.start()
    try:
        search = SearchReportsRequest(
            edrpous=EDRPOUS,
            report_types=["2"],
            include_details=False,
        )
        result = await client.search_reports_partial(search)
        items = result["items"]
        errors = result.get("errors", [])

        grouped_items: dict[str, list[dict[str, object]]] = defaultdict(list)
        for item in items:
            grouped_items[str(item["edrpou"])].append(item)

        semaphore = asyncio.Semaphore(CONCURRENCY)
        tasks = [render_report(client, semaphore, item) for item in items]

        rendered: list[dict[str, object]] = []
        render_errors: list[dict[str, object]] = []

        total = len(tasks)
        completed = 0
        for task in asyncio.as_completed(tasks):
            try:
                rendered_item = await task
                rendered.append(rendered_item)
            except Exception as exc:  # pragma: no cover - one-off export script
                render_errors.append({"detail": str(exc)})
            completed += 1
            if completed % 25 == 0 or completed == total:
                print(f"Rendered {completed}/{total}")

        rendered_by_edrpou: dict[str, list[dict[str, object]]] = defaultdict(list)
        for item in rendered:
            rendered_by_edrpou[str(item["edrpou"])].append(item)

        manifest = {
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "query": result["query"],
            "summary": result["summary"],
            "requested_edrpous": EDRPOUS,
            "edrpous_with_reports": sorted(rendered_by_edrpou.keys()),
            "edrpous_without_reports": sorted(
                edrpou
                for edrpou in EDRPOUS
                if edrpou not in grouped_items and edrpou not in {err["edrpou"] for err in errors}
            ),
            "errors": errors,
            "render_errors": render_errors,
            "total_reports_found": len(items),
            "total_reports_rendered": len(rendered),
        }

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )

            error_map = {str(item["edrpou"]): item["detail"] for item in errors}
            for edrpou in EDRPOUS:
                folder = f"{edrpou}/"
                if edrpou in error_map:
                    archive.writestr(
                        f"{folder}error.json",
                        json.dumps(
                            {
                                "edrpou": edrpou,
                                "detail": error_map[edrpou],
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                    continue

                reports = rendered_by_edrpou.get(edrpou, [])
                if not reports:
                    archive.writestr(
                        f"{folder}no_reports.json",
                        json.dumps(
                            {
                                "edrpou": edrpou,
                                "message": "По цьому ЄДРПОУ звіти форми 2 не знайдено.",
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                    continue

                reports.sort(
                    key=lambda item: (
                        str(item["meta"].get("publishDate") or ""),
                        int(item["report_id"]),
                    ),
                    reverse=True,
                )

                archive.writestr(
                    f"{folder}index.json",
                    json.dumps(
                        {
                            "edrpou": edrpou,
                            "reports_count": len(reports),
                            "reports": [item["meta"] for item in reports],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )

                for report in reports:
                    archive.writestr(f"{folder}{report['filename']}", str(report["html"]))

        print(f"Archive ready: {archive_path}")
        print(f"Reports found: {len(items)}")
        print(f"Reports rendered: {len(rendered)}")
        if errors:
            print(f"Portal errors: {len(errors)}")
        if render_errors:
            print(f"Render errors: {len(render_errors)}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
