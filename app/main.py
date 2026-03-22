from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path as FilePath

from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
    CatalogResponse,
    ErrorResponse,
    HealthResponse,
    SearchReportsRequest,
    SearchReportsResponse,
)
from app.settings import Settings
from app.spending_client import SpendingGovClient, SpendingGovError, normalize_edrpou

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
