from __future__ import annotations

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
    report_type_ids: list[int] = Field(
        default_factory=list,
        description="Конкретні reportTypeId з spending.gov.ua.",
    )
    report_types: list[str] = Field(
        default_factory=list,
        description="Назви типів звітів, наприклад 'Форма № 7'.",
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
