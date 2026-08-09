#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import platform
import random
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

START = date(2024, 1, 1)
END = date(2026, 6, 30)
SEED = 9102026

ORG_RE = re.compile(
    r"(?:\b(?:міськ|селищн|сільськ|районн|обласн)\w*\s+(?:рад\w*|виконавч\w*\s+комітет\w*)"
    r"|\bвиконавч\w*\s+комітет\w*|\bміськ\w*\s+голов\w*"
    r"|\bорган\w*\s+місцев\w*\s+самоврядуван\w*|\bомс\b)",
    re.IGNORECASE,
)
CHALLENGE_RE = re.compile(
    r"(?:визнан\w*.{0,48}(?:протиправн|незаконн|нечинн)\w*"
    r"|скасуван\w*|скасуват\w*|зупинен\w*\s+дії|оскаржен\w*)",
    re.IGNORECASE,
)
ACT_RE = re.compile(
    r"(?:\bрішен\w*|\bрозпоряджен\w*|\bрегуляторн\w*\s+акт\w*"
    r"|\bнормативн\w*\s+акт\w*|\bакт\w*|\bприпис\w*|\bнаказ\w*|\bпостан\w*)",
    re.IGNORECASE,
)
LOCAL_RESP_RE = re.compile(
    r"(?:відповідач|боржник)[^\n]{0,420}?(?:"
    r"(?:міськ|селищн|сільськ|районн|обласн)\w*\s+(?:рад\w*|виконавч\w*\s+комітет\w*)"
    r"|виконавч\w*\s+комітет\w*|міськ\w*\s+голов\w*"
    r"|орган\w*\s+місцев\w*\s+самоврядуван\w*)",
    re.IGNORECASE,
)
CASE_RE = re.compile(r"\b\d{1,4}/\d{1,8}/\d{2,4}\b")


def norm(value: Any) -> str:
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value)).replace("\x00", " ")
    return re.sub(r"\s+", " ", s).strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_date(value: str) -> date | None:
    s = norm(value)
    if not s:
        return None
    s = s.split()[0]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.search(r"(\d{2})[.\-/](\d{2})[.\-/](\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def choose_encoding(sample: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            sample.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def choose_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text, delimiters=",\t;|").delimiter
    except csv.Error:
        head = text.splitlines()[0] if text.splitlines() else ""
        counts = {d: head.count(d) for d in ",\t;|"}
        return max(counts, key=counts.get)


def court_kind(court_name: str, case_type: str) -> str:
    t = f"{court_name} {case_type}".lower()
    if "адміністратив" in t:
        return "адміністративний"
    if "господар" in t:
        return "господарський"
    if "апеляційн" in t:
        return "апеляційний загальний"
    if any(x in t for x in ("районн", "міськрайон", "міський суд", "верховний суд")):
        return "загальний"
    return "інший/невстановлений"


def oblast_from_court(court_name: str) -> str:
    s = norm(court_name)
    low = s.lower()
    if "міста києва" in low or "м. києва" in low or low.endswith("м.києва"):
        return "м. Київ"
    if "севастопол" in low:
        return "м. Севастополь"
    if "автономної республіки крим" in low or "ар крим" in low:
        return "Автономна Республіка Крим"
    known = [
        "Вінницька", "Волинська", "Дніпропетровська", "Донецька", "Житомирська", "Закарпатська",
        "Запорізька", "Івано-Франківська", "Київська", "Кіровоградська", "Луганська", "Львівська",
        "Миколаївська", "Одеська", "Полтавська", "Рівненська", "Сумська", "Тернопільська",
        "Харківська", "Херсонська", "Хмельницька", "Черкаська", "Чернівецька", "Чернігівська",
    ]
    for item in known:
        if item.lower() in low:
            return item + " область"
    return "не встановлено"


def redact_participants(value: str) -> str:
    s = norm(value)
    labels: list[str] = []
    for label in (
        "позивач", "відповідач", "боржник", "заявник", "третя особа", "прокурор",
        "представник позивача", "представник відповідача", "орган місцевого самоврядування",
    ):
        if re.search(rf"\b{re.escape(label)}\b", s, re.IGNORECASE):
            labels.append(label)
    if LOCAL_RESP_RE.search(s):
        labels.append("місцевий орган як відповідач/боржник")
    return "|".join(dict.fromkeys(labels)) or "ролі не встановлено"


def proximity(text: str) -> bool:
    org = ORG_RE.search(text)
    challenge = CHALLENGE_RE.search(text)
    act = ACT_RE.search(text)
    if not (org and challenge and act):
        return False
    return min(abs(challenge.start() - act.start()), abs(org.start() - act.start())) <= 220


def sample_stratified(records: list[dict[str, Any]], n: int, seed: int) -> set[str]:
    if len(records) <= n:
        return {r["номер_справи"] for r in records}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        groups[(str(r["рік"]), r["вид_суду"])].append(r)
    total = len(records)
    exact = {k: n * len(v) / total for k, v in groups.items()}
    allocation = {k: max(1, int(math.floor(x))) for k, x in exact.items()}
    while sum(allocation.values()) > n:
        reducible = [k for k in allocation if allocation[k] > 1]
        if not reducible:
            break
        k = min(reducible, key=lambda z: (exact[z] - allocation[z], -len(groups[z]), z))
        allocation[k] -= 1
    while sum(allocation.values()) < n:
        eligible = [k for k in allocation if allocation[k] < len(groups[k])]
        if not eligible:
            break
        k = max(eligible, key=lambda z: (exact[z] - allocation[z], len(groups[z]), tuple(map(str, z))))
        allocation[k] += 1
    rng = random.Random(seed)
    chosen: set[str] = set()
    for k in sorted(groups):
        items = sorted(groups[k], key=lambda r: r["номер_справи"])
        rng.shuffle(items)
        chosen.update(r["номер_справи"] for r in items[: allocation[k]])
    return chosen


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";", quoting=csv.QUOTE_MINIMAL, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: psh09d1_extract.py SNAPSHOT.zip OUTPUT_DIR", file=sys.stderr)
        return 2
    archive = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    archive_sha = sha256_file(archive)
    members_meta: list[dict[str, Any]] = []
    stats = Counter()
    case_acc: dict[str, dict[str, Any]] = {}
    file_schemas: list[dict[str, Any]] = []

    with zipfile.ZipFile(archive) as zf:
        data_members = [i for i in zf.infolist() if not i.is_dir() and i.filename.lower().endswith((".csv", ".txt"))]
        if not data_members:
            raise RuntimeError("No CSV/TXT member found in archive")
        for info in sorted(data_members, key=lambda x: x.filename):
            members_meta.append({"name": info.filename, "size": info.file_size, "compressed": info.compress_size, "crc": f"{info.CRC:08x}"})
            with zf.open(info) as raw:
                sample = raw.read(131072)
            enc = choose_encoding(sample)
            sample_text = sample.decode(enc, errors="replace")
            delim = choose_delimiter(sample_text)
            with zf.open(info) as raw:
                text = io.TextIOWrapper(raw, encoding=enc, errors="replace", newline="")
                reader = csv.DictReader(text, delimiter=delim)
                raw_fields = [norm(x).lstrip("\ufeff") for x in (reader.fieldnames or [])]
                if reader.fieldnames:
                    reader.fieldnames = raw_fields
                file_schemas.append({"member": info.filename, "encoding": enc, "delimiter": repr(delim), "fields": raw_fields})
                for line_no, row in enumerate(reader, start=2):
                    stats["rows_total"] += 1
                    row = {norm(k).lstrip("\ufeff"): v for k, v in row.items() if k is not None}
                    reg = parse_date(row.get("registration_date", ""))
                    if reg is None or not (START <= reg <= END):
                        continue
                    stats["rows_period"] += 1
                    raw_case = norm(row.get("case_number", ""))
                    match = CASE_RE.search(raw_case)
                    if not match:
                        stats["rows_no_valid_case"] += 1
                        continue
                    case_no = match.group(0)
                    court = norm(row.get("court_name", ""))
                    participants = norm(row.get("participants", ""))
                    desc = norm(row.get("description", ""))
                    cause_result = norm(row.get("cause_result", ""))
                    cause_dep = norm(row.get("cause_dep", ""))
                    ctype = norm(row.get("type", ""))
                    joined = " | ".join(x for x in (participants, desc, cause_result, cause_dep, ctype) if x)
                    has_org = bool(ORG_RE.search(joined))
                    has_challenge = bool(CHALLENGE_RE.search(joined))
                    has_act = bool(ACT_RE.search(joined))
                    has_local_resp = bool(LOCAL_RESP_RE.search(participants))
                    is_admin = "адміністратив" in f"{court} {ctype}".lower()
                    is_prox = proximity(joined)
                    main_hit = has_org and has_challenge and has_act and has_local_resp and is_admin
                    missing = [name for name, flag in (("ACT", has_act), ("LOCAL_RESPONDENT", has_local_resp), ("ADMIN", is_admin)) if not flag]
                    wide_hit = has_org and has_challenge and len(missing) == 1 and not main_hit
                    if not (main_hit or wide_hit):
                        continue
                    stats["candidate_rows"] += 1
                    layer = "основний" if main_hit else "широкий_можливі_пропуски"
                    evidence_score = sum((has_org, has_challenge, has_act, has_local_resp, is_admin, is_prox))
                    src = f"{info.filename}:{line_no}"
                    rule = "+".join([
                        "ORG" if has_org else "~ORG", "CHALLENGE" if has_challenge else "~CHALLENGE",
                        "ACT" if has_act else "~ACT", "LOCAL_RESPONDENT" if has_local_resp else "~LOCAL_RESPONDENT",
                        "ADMIN" if is_admin else "~ADMIN", "PROX" if is_prox else "~PROX",
                    ])
                    rec = {
                        "номер_справи": case_no,
                        "дата_первинної_реєстрації": reg.isoformat(),
                        "рік": reg.year,
                        "суд": court,
                        "область": oblast_from_court(court),
                        "вид_суду": court_kind(court, ctype),
                        "шар_відбору": layer,
                        "правило_збігу": rule,
                        "відсутній_ключ_широкого_шару": "|".join(missing),
                        "джерельний_рядок": src,
                        "джерельні_рядки_усі": [src],
                        "опис_предмета": desc,
                        "результат_або_стадія": cause_result,
                        "категорія_справи": cause_dep,
                        "тип": ctype,
                        "учасники_за_ролями": redact_participants(participants),
                        "ознака_близькості": "так" if is_prox else "ні",
                        "evidence_score": evidence_score,
                    }
                    old = case_acc.get(case_no)
                    if old is None:
                        case_acc[case_no] = rec
                    else:
                        old["джерельні_рядки_усі"].append(src)
                        new_key = (1 if layer == "основний" else 0, evidence_score, -line_no)
                        old_key = (1 if old["шар_відбору"] == "основний" else 0, int(old["evidence_score"]), 0)
                        if new_key > old_key:
                            keep_sources = old["джерельні_рядки_усі"]
                            case_acc[case_no] = rec
                            case_acc[case_no]["джерельні_рядки_усі"] = keep_sources

    records = list(case_acc.values())
    for record in records:
        record["джерельні_рядки_усі"] = "|".join(dict.fromkeys(record["джерельні_рядки_усі"]))
    main_records = [r for r in records if r["шар_відбору"] == "основний"]
    wide_records = [r for r in records if r["шар_відбору"] != "основний"]
    main_chosen = sample_stratified(main_records, 400, SEED)
    wide_chosen = sample_stratified(wide_records, 100, SEED)
    chosen = main_chosen | wide_chosen
    records.sort(key=lambda r: (0 if r["шар_відбору"] == "основний" else 1, r["рік"], r["вид_суду"], r["номер_справи"]))
    for idx, record in enumerate(records, start=1):
        record["код_кандидата"] = f"PSH09D1-C{idx:05d}"
        record["обрано_для_перевірки"] = "так" if record["номер_справи"] in chosen else "ні"
        record["початкове_число_відбору"] = SEED

    fieldnames = [
        "код_кандидата", "номер_справи", "дата_первинної_реєстрації", "рік", "суд", "область", "вид_суду",
        "шар_відбору", "правило_збігу", "відсутній_ключ_широкого_шару", "джерельний_рядок",
        "джерельні_рядки_усі", "опис_предмета", "результат_або_стадія", "категорія_справи", "тип",
        "учасники_за_ролями", "ознака_близькості", "обрано_для_перевірки", "початкове_число_відбору",
    ]
    write_csv(out_dir / "candidates.csv", fieldnames, records)
    write_csv(out_dir / "selected_for_review.csv", fieldnames, [r for r in records if r["обрано_для_перевірки"] == "так"])

    meta = {
        "archive": archive.name,
        "archive_size_bytes": archive.stat().st_size,
        "archive_sha256": archive_sha,
        "retrieved_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_url": os.environ.get("SOURCE_URL", ""),
        "period": {"start": START.isoformat(), "end": END.isoformat()},
        "seed": SEED,
        "python": sys.version,
        "platform": platform.platform(),
        "members": members_meta,
        "schemas": file_schemas,
        "counts": {
            **stats,
            "unique_candidates": len(records),
            "main_candidates": len(main_records),
            "wide_candidates": len(wide_records),
            "main_selected": len(main_chosen),
            "wide_selected": len(wide_chosen),
        },
        "regex": {
            "ORG": ORG_RE.pattern,
            "CHALLENGE": CHALLENGE_RE.pattern,
            "ACT": ACT_RE.pattern,
            "LOCAL_RESPONDENT": LOCAL_RESP_RE.pattern,
            "case_number": CASE_RE.pattern,
        },
        "main_rule": "ORG & CHALLENGE & ACT & LOCAL_RESPONDENT & ADMIN",
        "wide_rule": "ORG & CHALLENGE & exactly one missing among ACT, LOCAL_RESPONDENT, ADMIN",
        "deduplication": "canonical case_number; any main hit outranks wide; otherwise strongest evidence row retained; all source rows recorded",
        "sampling": "if main >400: Hamilton proportional allocation by registration year x court kind, then Python random.Random(9102026); if wide >100: same algorithm and seed",
    }
    (out_dir / "snapshot_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta["counts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
