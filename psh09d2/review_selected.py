from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from striprtf.striprtf import rtf_to_text

ROOT = Path(__file__).resolve().parent
TARGETS = json.loads(gzip.decompress(base64.b64decode((ROOT / "review_targets.b64").read_text(encoding="utf-8"))))
OUT = ROOT / "review_output"
OUT.mkdir(parents=True, exist_ok=True)

KEYWORDS = re.compile(
    r"(?:позовн|прос(?:ить|ив)|визнан|скасуван|рішен|ухвал|постанов|"
    r"міськ\w* рад|селищн\w* рад|сільськ\w* рад|виконавч\w* комітет|"
    r"розпоряджен|наказ|акт|забезпечен|апеляц|касац|набрал\w* законн\w* сил|виконан)",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[\t\r\f\v]+", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_excerpt(text: str, max_chars: int = 90000) -> str:
    text = normalize(text)
    if len(text) <= max_chars:
        return text
    windows: list[tuple[int, int]] = [(0, 12000), (max(0, len(text) - 28000), len(text))]
    for match in KEYWORDS.finditer(text):
        windows.append((max(0, match.start() - 1400), min(len(text), match.end() + 2600)))
    windows.sort()
    merged: list[tuple[int, int]] = []
    for start, end in windows:
        if not merged or start > merged[-1][1] + 200:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    chunks: list[str] = []
    used = 0
    for start, end in merged:
        chunk = text[start:end].strip()
        if not chunk:
            continue
        room = max_chars - used
        if room <= 0:
            break
        chunks.append(chunk[:room])
        used += min(len(chunk), room)
    return "\n\n[...фрагмент...]\n\n".join(chunks)


def decode_rtf(data: bytes) -> str:
    raw = data.decode("latin-1", errors="replace")
    try:
        return rtf_to_text(raw, errors="ignore")
    except TypeError:
        return rtf_to_text(raw)


def fetch(session: requests.Session, url: str) -> tuple[requests.Response | None, str]:
    error = ""
    for attempt in range(1, 4):
        try:
            response = session.get(url, timeout=(20, 90), allow_redirects=True)
            if response.status_code == 200:
                return response, ""
            error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.6 * attempt)
    return None, error


def main() -> None:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    session = requests.Session()
    session.headers.update({"User-Agent": "PSH-09-D2-open-data-review/1.0 (official open EDRSR files only)"})
    rows: list[dict[str, str]] = []
    for index, target in enumerate(TARGETS, 1):
        response, error = fetch(session, target["doc_url"])
        row = dict(target)
        row.update({
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "http_status": "",
            "final_url": "",
            "bytes": "0",
            "sha256": "",
            "content_type": "",
            "error": error,
            "text_length": "0",
            "text_excerpt": "",
        })
        if response is not None:
            data = response.content
            text = decode_rtf(data)
            row.update({
                "http_status": str(response.status_code),
                "final_url": response.url,
                "bytes": str(len(data)),
                "sha256": hashlib.sha256(data).hexdigest(),
                "content_type": response.headers.get("content-type", ""),
                "error": "",
                "text_length": str(len(text)),
                "text_excerpt": extract_excerpt(text),
            })
        rows.append(row)
        print(f"{index}/{len(TARGETS)} {target['case_number']} doc={target['doc_id']} status={row['http_status'] or row['error']}", flush=True)
        time.sleep(0.15)

    fields = [
        "case_number", "doc_id", "adjudication_date", "court_name", "judgment_form",
        "stage_name", "dataset_code", "doc_url", "retrieved_at", "http_status",
        "final_url", "bytes", "sha256", "content_type", "error", "text_length", "text_excerpt",
    ]
    output = OUT / "review_texts.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "targets": len(TARGETS),
        "successes": sum(row["http_status"] == "200" for row in rows),
        "failures": sum(row["http_status"] != "200" for row in rows),
        "output_bytes": output.stat().st_size,
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    (OUT / "review_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
