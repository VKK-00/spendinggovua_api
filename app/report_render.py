from __future__ import annotations

import html
import re
from typing import Any


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug or "report"


def build_report_filename(edrpou: str, report_id: int, extension: str) -> str:
    return f"report-{_slugify(edrpou)}-{report_id}.{extension}"


def build_report_html(report: dict[str, Any]) -> str:
    signed_at = report.get("signed_at") or "Невідомо"
    title = report.get("title") or "Звіт"
    name = report.get("name") or ""
    period = report.get("period") or ""
    source_url = report.get("source_url") or ""
    codes = report.get("codes") or []
    fields = report.get("fields") or []
    notation = report.get("notation") or []
    header_rows = report.get("table", {}).get("header_rows") or []
    body_rows = report.get("table", {}).get("body_rows") or []

    code_items = "".join(
        f'<div class="pill">{_escape(item)}</div>'
        for item in codes
        if str(item).strip()
    )
    field_items = "".join(
        (
            '<article class="field">'
            f'<div class="field-name">{_escape(item.get("name"))}</div>'
            f'<div class="field-value">{_escape(item.get("value")) or "&nbsp;"}</div>'
            "</article>"
        )
        for item in fields
    )
    note_items = "".join(
        f"<li>{_escape(item)}</li>"
        for item in notation
        if str(item).strip()
    )
    head_html = "".join(
        "<tr>"
        + "".join(f"<th>{_escape(cell)}</th>" for cell in row)
        + "</tr>"
        for row in header_rows
    )
    body_html = "".join(
        "<tr>"
        + "".join(f"<td>{_escape(cell)}</td>" for cell in row)
        + "</tr>"
        for row in body_rows
    )

    source_block = (
        f'<p class="source">Джерело: <a href="{_escape(source_url)}">{_escape(source_url)}</a></p>'
        if source_url
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="uk">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{_escape(title)} - {_escape(period)}</title>
    <style>
      @page {{
        size: A4 landscape;
        margin: 12mm;
      }}

      :root {{
        --ink: #142033;
        --muted: #546173;
        --line: #cfd8e3;
        --surface: #ffffff;
        --surface-alt: #f4f7fb;
        --surface-strong: #e8eef6;
        --accent: #0d5e8c;
      }}

      * {{
        box-sizing: border-box;
      }}

      body {{
        margin: 0;
        font-family: Arial, Helvetica, sans-serif;
        color: var(--ink);
        background: var(--surface);
      }}

      .page {{
        padding: 20px 24px 28px;
      }}

      .hero {{
        display: grid;
        gap: 10px;
        margin-bottom: 18px;
        padding-bottom: 14px;
        border-bottom: 2px solid var(--surface-strong);
      }}

      .eyebrow {{
        margin: 0;
        color: var(--accent);
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}

      h1 {{
        margin: 0;
        font-size: 28px;
        line-height: 1.15;
      }}

      .report-name {{
        margin: 0;
        font-size: 18px;
        line-height: 1.35;
        font-weight: 700;
      }}

      .meta-line {{
        margin: 0;
        color: var(--muted);
        font-size: 13px;
      }}

      .pill-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 6px;
      }}

      .pill {{
        padding: 6px 10px;
        border: 1px solid var(--line);
        border-radius: 999px;
        background: var(--surface-alt);
        font-size: 12px;
        font-weight: 700;
      }}

      .field-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin: 18px 0 14px;
      }}

      .field {{
        padding: 10px 12px;
        border: 1px solid var(--line);
        border-radius: 10px;
        background: var(--surface-alt);
        break-inside: avoid;
      }}

      .field-name {{
        margin-bottom: 4px;
        color: var(--muted);
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
      }}

      .field-value {{
        font-size: 13px;
        line-height: 1.4;
        white-space: pre-wrap;
        word-break: break-word;
      }}

      .note-list {{
        margin: 0 0 14px 18px;
        padding: 0;
        color: var(--muted);
        font-size: 12px;
      }}

      .table-wrap {{
        border: 1px solid var(--line);
        border-radius: 12px;
        overflow: hidden;
      }}

      table {{
        width: 100%;
        border-collapse: collapse;
        table-layout: fixed;
        font-size: 10px;
        line-height: 1.3;
      }}

      thead {{
        display: table-header-group;
      }}

      tr {{
        page-break-inside: avoid;
      }}

      th,
      td {{
        border: 1px solid var(--line);
        padding: 6px 7px;
        vertical-align: top;
        word-break: break-word;
      }}

      thead th {{
        background: var(--surface-strong);
        text-align: center;
        font-weight: 700;
      }}

      thead tr:last-child th {{
        background: var(--surface-alt);
      }}

      tbody tr:nth-child(even) td {{
        background: #fbfdff;
      }}

      tbody td:first-child {{
        width: 31%;
        font-weight: 700;
      }}

      tbody td:nth-child(2),
      tbody td:nth-child(3) {{
        width: 9%;
        text-align: center;
      }}

      .source {{
        margin: 14px 0 0;
        color: var(--muted);
        font-size: 11px;
      }}

      .source a {{
        color: inherit;
      }}
    </style>
  </head>
  <body>
    <main class="page">
      <section class="hero">
        <p class="eyebrow">Spending.gov.ua Report Export</p>
        <h1>{_escape(title)}</h1>
        <p class="report-name">{_escape(name)}</p>
        <p class="meta-line">Період: {_escape(period)}</p>
        <p class="meta-line">Підписано: {_escape(signed_at)}</p>
        <div class="pill-row">{code_items}</div>
      </section>

      <section class="field-grid">{field_items}</section>

      <ul class="note-list">{note_items}</ul>

      <section class="table-wrap">
        <table>
          <thead>{head_html}</thead>
          <tbody>{body_html}</tbody>
        </table>
      </section>

      {source_block}
    </main>
  </body>
</html>
"""
