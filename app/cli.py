from __future__ import annotations

import asyncio
import os

import uvicorn

from app.batch_export import export_form2_html_archive


def run_api() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


def export_form2_archive() -> None:
    asyncio.run(export_form2_html_archive())
