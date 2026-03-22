from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, model_validator


class SearchReportsRequest(BaseModel):
    edrpou: str | None = Field(default=None, description="Один ЄДРПОУ.")
    edrpous: list[str] = Field(
        default_factory=list,
        description="Список ЄДРПОУ для групового пошуку.",
    )
    years: list[int] = Field(
        default_factory=list,
        description="Роки, за якими потрібно відібрати звіти.",
    )
    date_from: date | None = Field(
        default=None,
        description="Початок проміжку часу у форматі YYYY-MM-DD.",
    )
    date_to: date | None = Field(
        default=None,
        description="Кінець проміжку часу у форматі YYYY-MM-DD.",
    )
    report_type_ids: list[int] = Field(
        default_factory=list,
        description="Конкретні reportTypeId з spending.gov.ua.",
    )
    report_types: list[str] = Field(
        default_factory=list,
        description="Назви або коди типів звітів, наприклад 'Форма № 7' або '2'.",
    )
    sign_status: str = Field(
        default="signed",
        description="Статус підпису, який передається у spending.gov.ua.",
    )
    include_details: bool = Field(
        default=False,
        description="Чи підтягувати повні дані кожного знайденого звіту.",
    )
    max_reports: int | None = Field(
        default=None,
        ge=1,
        description="Обмеження кількості звітів у відповіді після фільтрації.",
    )

    @model_validator(mode="after")
    def validate_edrpou_input(self) -> "SearchReportsRequest":
        if self.edrpou is None and not self.edrpous:
            raise ValueError("Потрібно передати `edrpou` або непорожній `edrpous`.")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("`date_from` не може бути пізніше за `date_to`.")
        return self


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str
    browser_started: bool


class CatalogResponse(BaseModel):
    edrpou: str
    available_years: list[int]
    report_type_groups: list[dict[str, Any]]
    report_type_map: dict[str, str]


class SearchReportsResponse(BaseModel):
    query: dict[str, Any]
    summary: dict[str, Any]
    items: list[dict[str, Any]]


class ReportTypeSummaryItem(BaseModel):
    name: str
    reports_count: int
    edrpous_count: int
    edrpous: list[str]
    by_year: dict[str, int]


class ReportTypesSummaryResponse(BaseModel):
    query: dict[str, Any]
    summary: dict[str, Any]
    types: list[ReportTypeSummaryItem]
    errors: list[dict[str, str]] = Field(default_factory=list)


class ExportReportsZipRequest(SearchReportsRequest):
    latest_only_per_edrpou: bool = Field(
        default=False,
        description="Експортувати лише найсвіжіший звіт по кожному ЄДРПОУ.",
    )
    archive_name: str | None = Field(
        default=None,
        description="Базова назва zip-архіву без розширення.",
    )
