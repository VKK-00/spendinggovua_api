from __future__ import annotations

from contextlib import asynccontextmanager
import re
from pathlib import Path as FilePath

from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.responses import FileResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.models import (
    CatalogResponse,
    ErrorResponse,
    ExportReportsZipRequest,
    HealthResponse,
    ReportTypesSummaryResponse,
    SearchReportsRequest,
    SearchReportsResponse,
)
from app.settings import Settings
from app.spending_client import SpendingGovClient, SpendingGovError, normalize_edrpou
from app.zip_export import build_reports_zip

settings = Settings()
client = SpendingGovClient(settings)
BASE_DIR = FilePath(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    app.state.spending_client = client
    yield
    await client.close()


app = FastAPI(
    title="spending.gov.ua reports API",
    version="0.1.0",
    summary="API для витягування звітів spending.gov.ua по ЄДРПОУ, роках і типах звітів.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_client(request: Request) -> SpendingGovClient:
    return request.app.state.spending_client


def _ascii_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "reports-export.zip"


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["service"],
)
async def health(request: Request) -> HealthResponse:
    spending_client = get_client(request)
    return HealthResponse(status="ok", browser_started=spending_client.started)


@app.get(
    "/api/catalog/{edrpou}",
    response_model=CatalogResponse,
    responses={502: {"model": ErrorResponse}},
    tags=["reports"],
)
async def catalog(
    request: Request,
    edrpou: str = Path(..., description="ЄДРПОУ організації."),
) -> CatalogResponse:
    spending_client = get_client(request)
    try:
        payload = await spending_client.get_catalog(normalize_edrpou(edrpou))
    except SpendingGovError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return CatalogResponse.model_validate(payload)


@app.post(
    "/api/reports/search",
    response_model=SearchReportsResponse,
    responses={502: {"model": ErrorResponse}},
    tags=["reports"],
)
async def search_reports(
    request: Request,
    payload: SearchReportsRequest,
) -> SearchReportsResponse:
    spending_client = get_client(request)
    try:
        result = await spending_client.search_reports(payload)
    except SpendingGovError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SearchReportsResponse.model_validate(result)


@app.post(
    "/api/report-types/summary",
    response_model=ReportTypesSummaryResponse,
    responses={502: {"model": ErrorResponse}},
    tags=["reports"],
)
async def report_types_summary(
    request: Request,
    payload: SearchReportsRequest,
) -> ReportTypesSummaryResponse:
    spending_client = get_client(request)
    try:
        result = await spending_client.summarize_report_types(payload)
    except SpendingGovError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ReportTypesSummaryResponse.model_validate(result)


@app.post(
    "/api/reports/export/zip",
    responses={502: {"model": ErrorResponse}},
    tags=["reports"],
)
async def export_reports_zip(
    request: Request,
    payload: ExportReportsZipRequest,
) -> Response:
    spending_client = get_client(request)
    try:
        search_payload = payload.model_copy(update={"include_details": True})
        result = await spending_client.search_reports_partial(search_payload)
        zip_bytes, zip_name = build_reports_zip(
            query=result["query"],
            summary=result["summary"],
            items=result["items"],
            errors=result.get("errors", []),
            latest_only_per_edrpou=payload.latest_only_per_edrpou,
            archive_name=payload.archive_name,
        )
    except SpendingGovError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    safe_name = _ascii_filename(zip_name)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )
