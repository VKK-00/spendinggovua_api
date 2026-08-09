#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
import unicodedata
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup

CASE_RE = re.compile(r"\b\d{1,4}/\d{1,8}/\d{2,4}\b")
ROLE_RE = re.compile(
    r"(?P<label>Позивач|Відповідач(?:\s*\(Боржник\))?|Боржник|Заявник|Третя особа|"
    r"Представник позивача|Представник відповідача|Прокурор)\s*:\s*",
    re.IGNORECASE,
)
LOCAL_RE = re.compile(
    r"(?:\b(?:міськ|селищн|сільськ|районн|обласн)\w*\s+(?:рад\w*|виконавч\w*\s+комітет\w*)"
    r"|\bвиконавч\w*\s+комітет\w*|\bміськ\w*\s+голов\w*"
    r"|\bорган\w*\s+місцев\w*\s+самоврядуван\w*)",
    re.IGNORECASE,
)
PUBLIC_ORG_TERM_RE = re.compile(
    r"(?:рада|виконавч(?:ий|ого|ому)?\s+комітет|міськ(?:ий|ого|ому)?\s+голов|"
    r"департамент|управління|відділ|служба|інспекція|комісія|адміністрація|міністерство|"
    r"прокуратура|поліція|реєстратор|комунальн(?:е|ий|а)\s+(?:підприємство|установа|заклад))",
    re.IGNORECASE,
)
KEYWORD_RE = re.compile(
    r"(?:визнан\w*|скасуван\w*|скасуват\w*|нечинн\w*|незаконн\w*|протиправн\w*|"
    r"рішен\w*|розпоряджен\w*|припис\w*|постан\w*|рад\w*|виконавч\w*\s+комітет\w*|"
    r"забезпечен\w*\s+позов\w*|позов\w*\s+(?:задовольн|відмов))",
    re.IGNORECASE,
)


def norm(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).replace("\x00", " ")
    return re.sub(r"\s+", " ", text).strip()


def canonical_case(value: Any) -> str:
    m = CASE_RE.search(norm(value))
    return m.group(0) if m else ""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def choose_encoding(sample: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            sample.decode(enc)
            return enc
        except UnicodeDecodeError:
            pass
    return "utf-8"


def choose_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text, delimiters=",\t;|").delimiter
    except csv.Error:
        head = text.splitlines()[0] if text.splitlines() else ""
        counts = {d: head.count(d) for d in ",\t;|"}
        return max(counts, key=counts.get)


def iter_zip_csv(zf: zipfile.ZipFile, info: zipfile.ZipInfo):
    with zf.open(info) as raw:
        sample = raw.read(131072)
    enc = choose_encoding(sample)
    delimiter = choose_delimiter(sample.decode(enc, errors="replace"))
    with zf.open(info) as raw:
        text = io.TextIOWrapper(raw, encoding=enc, errors="replace", newline="")
        reader = csv.DictReader(text, delimiter=delimiter)
        fields = [norm(x).lstrip("\ufeff") for x in (reader.fieldnames or [])]
        reader.fieldnames = fields
        for line_no, row in enumerate(reader, start=2):
            yield line_no, {norm(k).lstrip("\ufeff"): norm(v) for k, v in row.items() if k is not None}, enc, delimiter, fields


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in fields})


def split_roles(participants: str) -> list[tuple[str, str]]:
    text = norm(participants)
    matches = list(ROLE_RE.finditer(text))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[m.end():end].strip(" ,;|")
        out.append((norm(m.group("label")).lower(), value))
    return out


def classify_entity(value: str) -> str:
    low = norm(value).lower()
    if not low or low == "-":
        return "не встановлено"
    if LOCAL_RE.search(low):
        return "орган місцевого самоврядування/його орган"
    if re.search(r"\b(комунальн\w*\s+(?:підприємств|установ|заклад)|кп\b)", low):
        return "комунальна юридична особа"
    if re.search(r"\b(міністерств|державн\w*\s+(?:служб|інспекц|агентств|адміністрац)|поліц|прокуратур|пенсійн\w*\s+фонд)", low):
        return "державний орган/прокуратура"
    if re.search(r"\b(тов|тзов|пп\b|приватн\w*\s+підприємств|акціонерн|юридичн\w*\s+особ|організаці|фонд|кооператив)", low):
        return "юридична особа"
    if re.search(r"\b(фізичн\w*\s+особ|особа[_\s]*\d+|громадян)", low):
        return "фізична особа"
    if PUBLIC_ORG_TERM_RE.search(low):
        return "публічний/комунальний орган або установа"
    return "фізична особа або невстановлена категорія"


def safe_org_mentions(participants: str) -> list[str]:
    mentions: list[str] = []
    for label, value in split_roles(participants):
        if PUBLIC_ORG_TERM_RE.search(value) or LOCAL_RE.search(value):
            value = re.sub(r"\b(?:представник|адвокат)\b.*$", "", value, flags=re.IGNORECASE).strip(" ,;")
            if len(value) > 280:
                value = value[:280].rsplit(" ", 1)[0] + "…"
            mentions.append(f"{label}: {value}")
    return list(dict.fromkeys(mentions))


def role_categories(participants: str) -> list[str]:
    return [f"{label}: {classify_entity(value)}" for label, value in split_roles(participants)]


def process_dsa(snapshot: Path, selected: set[str], out_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    schema: list[dict[str, Any]] = []
    with zipfile.ZipFile(snapshot) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and i.filename.lower().endswith((".csv", ".txt"))]
        for info in sorted(infos, key=lambda x: x.filename):
            first_meta = None
            for line_no, row, enc, delim, fields in iter_zip_csv(zf, info):
                if first_meta is None:
                    first_meta = {"member": info.filename, "encoding": enc, "delimiter": repr(delim), "fields": fields}
                case_no = canonical_case(row.get("case_number"))
                if case_no not in selected:
                    continue
                participants = row.get("participants", "")
                rows.append({
                    "номер_справи": case_no,
                    "суд": row.get("court_name", ""),
                    "провадження": row.get("case_proc", ""),
                    "дата_реєстрації_рядка": row.get("registration_date", ""),
                    "дата_стадії": row.get("stage_date", ""),
                    "стадія": row.get("stage_name", ""),
                    "результат_стадії": row.get("cause_result", ""),
                    "категорія": row.get("cause_dep", ""),
                    "тип": row.get("type", ""),
                    "опис_предмета": row.get("description", ""),
                    "категорії_учасників": " | ".join(role_categories(participants)),
                    "публічні_організації": " | ".join(safe_org_mentions(participants)),
                    "локальний_орган_у_рядку": "так" if LOCAL_RE.search(participants) else "ні",
                    "джерельний_рядок": f"{info.filename}:{line_no}",
                })
            if first_meta:
                schema.append(first_meta)

    rows.sort(key=lambda r: (r["номер_справи"], r["дата_реєстрації_рядка"], r["дата_стадії"], r["суд"]))
    write_csv(out_dir / "selected_dsa_rows.csv", [
        "номер_справи", "суд", "провадження", "дата_реєстрації_рядка", "дата_стадії", "стадія",
        "результат_стадії", "категорія", "тип", "опис_предмета", "категорії_учасників",
        "публічні_організації", "локальний_орган_у_рядку", "джерельний_рядок",
    ], rows)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["номер_справи"]].append(row)
    summaries = []
    for case_no in sorted(selected):
        case_rows = grouped.get(case_no, [])
        def uniq(field: str, limit: int = 20) -> str:
            vals = [norm(r.get(field)) for r in case_rows if norm(r.get(field))]
            vals = list(dict.fromkeys(vals))
            return " | ".join(vals[:limit])
        summaries.append({
            "номер_справи": case_no,
            "кількість_рядків_ДСА": len(case_rows),
            "суди": uniq("суд"),
            "провадження": uniq("провадження"),
            "дати_реєстрації_рядків": uniq("дата_реєстрації_рядка"),
            "дати_стадій": uniq("дата_стадії"),
            "стадії": uniq("стадія"),
            "результати_стадій": uniq("результат_стадії"),
            "категорії": uniq("категорія"),
            "типи": uniq("тип"),
            "описи_предмета": uniq("опис_предмета"),
            "категорії_учасників": uniq("категорії_учасників"),
            "публічні_організації": uniq("публічні_організації"),
            "джерельні_рядки": uniq("джерельний_рядок", 100),
        })
    write_csv(out_dir / "case_dsa_summary.csv", list(summaries[0].keys()), summaries)
    return {
        "archive_size_bytes": snapshot.stat().st_size,
        "archive_sha256": sha256_file(snapshot),
        "rows_selected": len(rows),
        "cases_with_rows": len(grouped),
        "schemas": schema,
    }


def load_dictionary(zf: zipfile.ZipFile, suffix: str, key: str) -> dict[str, dict[str, str]]:
    matches = [i for i in zf.infolist() if not i.is_dir() and i.filename.lower().endswith(suffix.lower())]
    if not matches:
        return {}
    result: dict[str, dict[str, str]] = {}
    for _, row, _, _, _ in iter_zip_csv(zf, matches[0]):
        k = norm(row.get(key))
        if k:
            result[k] = row
    return result


def process_edrsr(year: int, archive: Path, selected: set[str], out_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected_docs: list[dict[str, Any]] = []
    with zipfile.ZipFile(archive) as zf:
        courts = load_dictionary(zf, "courts.csv", "court_code")
        instances = load_dictionary(zf, "instances.csv", "instance_code")
        regions = load_dictionary(zf, "regions.csv", "region_code")
        forms = load_dictionary(zf, "judgment_forms.csv", "judgment_code")
        justice = load_dictionary(zf, "justice_kinds.csv", "justice_kind")
        categories = load_dictionary(zf, "cause_categories.csv", "category_code")
        doc_members = [i for i in zf.infolist() if not i.is_dir() and i.filename.lower().endswith("documents.csv")]
        if not doc_members:
            raise RuntimeError(f"documents.csv not found in {archive}")
        schema_meta = None
        for line_no, row, enc, delim, fields in iter_zip_csv(zf, doc_members[0]):
            if schema_meta is None:
                schema_meta = {"member": doc_members[0].filename, "encoding": enc, "delimiter": repr(delim), "fields": fields}
            case_no = canonical_case(row.get("cause_num"))
            if case_no not in selected:
                continue
            court = courts.get(row.get("court_code", ""), {})
            selected_docs.append({
                "номер_справи": case_no,
                "рік_архіву": year,
                "doc_id": row.get("doc_id", ""),
                "doc_url": row.get("doc_url", "") or (f"https://reyestr.court.gov.ua/Review/{row.get('doc_id')}" if row.get("doc_id") else ""),
                "дата_ухвалення": row.get("adjudication_date", ""),
                "дата_надходження": row.get("receipt_date", ""),
                "дата_оприлюднення": row.get("date_publ", ""),
                "статус_загального_доступу": row.get("status", ""),
                "код_суду": row.get("court_code", ""),
                "суд": court.get("name", ""),
                "інстанція": instances.get(court.get("instance_code", ""), {}).get("name", ""),
                "регіон": regions.get(court.get("region_code", ""), {}).get("name", ""),
                "форма_рішення": forms.get(row.get("judgment_code", ""), {}).get("name", ""),
                "форма_судочинства": justice.get(row.get("justice_kind", ""), {}).get("name", ""),
                "категорія_ЄДРСР": categories.get(row.get("category_code", ""), {}).get("name", ""),
                "джерельний_рядок": f"{doc_members[0].filename}:{line_no}",
            })
        members = [{"name": i.filename, "size": i.file_size, "compressed_size": i.compress_size, "crc32": f"{i.CRC:08x}"} for i in zf.infolist() if not i.is_dir()]
    meta = {
        "year": year,
        "archive": archive.name,
        "size_bytes": archive.stat().st_size,
        "sha256": sha256_file(archive),
        "selected_documents": len(selected_docs),
        "cases_with_documents": len({d["номер_справи"] for d in selected_docs}),
        "members": members,
        "documents_schema": schema_meta,
    }
    return selected_docs, meta


def parse_date_key(value: str) -> tuple[int, int, int, str]:
    s = norm(value)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        try:
            d = datetime.strptime(s, fmt)
            return d.year, d.month, d.day, s
        except ValueError:
            pass
    return 9999, 12, 31, s


def choose_docs_for_fetch(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public = [d for d in docs if norm(d.get("doc_url")) and norm(d.get("статус_загального_доступу")) != "0"]
    if not public:
        return []
    public.sort(key=lambda d: (parse_date_key(d.get("дата_ухвалення", "")), d.get("doc_id", "")))
    chosen = [public[0], public[-1]]
    substantive = [d for d in public if re.search(r"рішен|постан", d.get("форма_рішення", ""), re.IGNORECASE)]
    if substantive:
        chosen.append(substantive[-1])
    out = []
    seen = set()
    for d in chosen:
        key = d.get("doc_id") or d.get("doc_url")
        if key not in seen:
            out.append(d)
            seen.add(key)
    return out[:3]


def extract_relevant_snippets(text: str, window: int = 850, max_snippets: int = 12) -> str:
    clean = norm(text)
    snippets: list[str] = []
    for m in KEYWORD_RE.finditer(clean):
        start = max(0, m.start() - window)
        end = min(len(clean), m.end() + window)
        snippet = clean[start:end]
        if any(snippet in old or old in snippet for old in snippets):
            continue
        snippets.append(snippet)
        if len(snippets) >= max_snippets:
            break
    return "\n---\n".join(snippets)


def fetch_doc_texts(all_docs: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in all_docs:
        by_case[doc["номер_справи"]].append(doc)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; public-research-verification/1.0)",
        "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.5",
    })
    out_rows: list[dict[str, Any]] = []
    for case_no in sorted(by_case):
        for doc in choose_docs_for_fetch(by_case[case_no]):
            url = doc.get("doc_url", "")
            status = ""
            final_url = ""
            title = ""
            head = ""
            tail = ""
            snippets = ""
            error = ""
            try:
                resp = session.get(url, timeout=45, allow_redirects=True)
                status = str(resp.status_code)
                final_url = resp.url
                if resp.ok:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for tag in soup(["script", "style", "noscript"]):
                        tag.decompose()
                    title = norm(soup.title.get_text(" ") if soup.title else "")
                    text = norm(soup.get_text(" "))
                    head = text[:9000]
                    tail = text[-9000:] if len(text) > 9000 else text
                    snippets = extract_relevant_snippets(text)
                else:
                    error = f"HTTP {resp.status_code}"
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            out_rows.append({
                "номер_справи": case_no,
                "doc_id": doc.get("doc_id", ""),
                "doc_url": url,
                "дата_ухвалення": doc.get("дата_ухвалення", ""),
                "суд": doc.get("суд", ""),
                "форма_рішення": doc.get("форма_рішення", ""),
                "http_status": status,
                "кінцева_адреса": final_url,
                "заголовок": title,
                "початок_тексту": head,
                "кінець_тексту": tail,
                "релевантні_уривки": snippets,
                "помилка": error,
            })
            time.sleep(0.25)
    fields = list(out_rows[0].keys()) if out_rows else ["номер_справи", "doc_id", "doc_url", "помилка"]
    write_csv(out_dir / "edrsr_text_snippets.csv", fields, out_rows)
    return {
        "documents_requested": len(out_rows),
        "documents_http_200": sum(1 for r in out_rows if r["http_status"] == "200"),
        "cases_with_requested_documents": len({r["номер_справи"] for r in out_rows}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--edrsr", nargs=2, action="append", metavar=("YEAR", "ZIP"), default=[])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    selected = {canonical_case(line) for line in args.selected.read_text(encoding="utf-8").splitlines()}
    selected.discard("")

    dsa_meta = process_dsa(args.snapshot, selected, args.out)
    all_docs: list[dict[str, Any]] = []
    archives_meta: list[dict[str, Any]] = []
    for year_s, archive_s in args.edrsr:
        docs, meta = process_edrsr(int(year_s), Path(archive_s), selected, args.out)
        all_docs.extend(docs)
        archives_meta.append(meta)
    all_docs.sort(key=lambda d: (d["номер_справи"], parse_date_key(d["дата_ухвалення"]), d["doc_id"]))
    doc_fields = [
        "номер_справи", "рік_архіву", "doc_id", "doc_url", "дата_ухвалення", "дата_надходження",
        "дата_оприлюднення", "статус_загального_доступу", "код_суду", "суд", "інстанція", "регіон",
        "форма_рішення", "форма_судочинства", "категорія_ЄДРСР", "джерельний_рядок",
    ]
    write_csv(args.out / "edrsr_documents.csv", doc_fields, all_docs)
    text_meta = fetch_doc_texts(all_docs, args.out)
    cases_with_docs = {d["номер_справи"] for d in all_docs}
    missing = sorted(selected - cases_with_docs)
    (args.out / "cases_without_edrsr_documents.txt").write_text("\n".join(missing) + ("\n" if missing else ""), encoding="utf-8")

    meta = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "selected_cases": len(selected),
        "dsa": dsa_meta,
        "edrsr_archives": archives_meta,
        "edrsr_documents": len(all_docs),
        "cases_with_edrsr_documents": len(cases_with_docs),
        "cases_without_edrsr_documents": missing,
        "text_fetch": text_meta,
    }
    (args.out / "verification_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    for path in sorted(args.out.iterdir()):
        if path.is_file():
            print(path.name, path.stat().st_size, sha256_file(path))
    print(json.dumps({
        "selected_cases": len(selected),
        "dsa_rows": dsa_meta["rows_selected"],
        "edrsr_documents": len(all_docs),
        "cases_with_edrsr_documents": len(cases_with_docs),
        **text_meta,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
