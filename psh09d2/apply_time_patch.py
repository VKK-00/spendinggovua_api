from pathlib import Path
import re

root = Path(__file__).resolve().parent
path = root / "acquire_filter.py"
s = path.read_text(encoding="utf-8")

helper = '''def primary_time_prefilter(year: int | None, registration_date: dt.date | None) -> tuple[bool, str, bool]:
    """Gate on primary-case year, not a later court-level registration."""
    if year not in (2024, 2025, 2026):
        return False, "рік канонічного номера первинної справи поза межами", False
    if year in (2024, 2025):
        return True, "рік канонічного номера первинної справи; registration_date може стосуватися поточної судової ланки", False
    if registration_date and DATE_FROM <= registration_date <= DATE_TO:
        return True, "registration_date ДСА у межах 2026-01-01—2026-06-30", False
    return True, "2026 потребує підтвердження найранішою відкритою метадатою ЄДРСР до 30.06", True


def resolve_primary_time(year: int | None, registration_date: dt.date | None, earliest_edrsr: dt.date | None) -> tuple[bool, str]:
    """Resolve final eligibility of a canonical primary case."""
    if year in (2024, 2025):
        return True, "рік канонічного номера первинної справи; весь рік у межах"
    if year == 2026 and registration_date and DATE_FROM <= registration_date <= DATE_TO:
        return True, f"registration_date ДСА {registration_date.isoformat()} у межах"
    if year == 2026 and earliest_edrsr and earliest_edrsr <= DATE_TO:
        return True, f"найраніша відкрита метадата ЄДРСР {earliest_edrsr.isoformat()}"
    if year == 2026:
        return False, "не доведено первинне звернення до 30.06.2026"
    return False, "рік канонічного номера первинної справи поза межами"


'''
if "def primary_time_prefilter" not in s:
    marker = "def detect_text_format(sample: bytes) -> tuple[str, str]:\n"
    if marker not in s:
        raise SystemExit("helper insertion marker not found")
    s = s.replace(marker, helper + marker, 1)

old_prefilter = '''                temporal_basis = ""
                eligible_now = False
                if reg_date:
                    eligible_now = DATE_FROM <= reg_date <= DATE_TO
                    temporal_basis = "registration_date"
                elif year in (2024, 2025):
                    eligible_now = True
                    temporal_basis = "рік канонічного номера; точна дата відсутня"
                    missing_date_pending += 1
                elif year == 2026:
                    # Keep provisionally and resolve against earliest open EDRSR metadata later.
                    eligible_now = True
                    temporal_basis = "2026 без точної дати; потребує перевірки до 30.06"
                    missing_date_pending += 1
                if not eligible_now:
                    continue
'''
new_prefilter = '''                # The task concerns the filing date of the primary case. A DSA
                # registration date on an appellate/cassation row must not pull an
                # older primary case into 2024–2026.
                eligible_now, temporal_basis, needs_confirmation = primary_time_prefilter(year, reg_date)
                if not eligible_now:
                    continue
                if needs_confirmation:
                    missing_date_pending += 1
'''
if old_prefilter in s:
    s = s.replace(old_prefilter, new_prefilter, 1)
elif "needs_confirmation = primary_time_prefilter" not in s:
    raise SystemExit("old temporal prefilter block not found")

s = s.replace(
    "    # Resolve provisional 2026 timing using earliest open EDRSR metadata where exact DSA date is absent.\n",
    "    # Resolve provisional 2026 timing using earliest open EDRSR metadata.\n    # Primary-case years before 2024 were already excluded before regex matching.\n",
    1,
)

old_resolution = '''    for candidate in candidates:
        if candidate.get("registration_date"):
            candidate["time_resolution"] = "точна registration_date ДСА"
            resolved.append(candidate)
            continue
        y = int(candidate.get("year") or 0)
        if y in (2024, 2025):
            candidate["time_resolution"] = "рік канонічного номера; весь рік у межах"
            resolved.append(candidate)
            continue
        earliest = earliest_by_case.get(candidate["canonical_number"])
        if y == 2026 and earliest and earliest <= DATE_TO:
            candidate["time_resolution"] = f"найраніша відкрита метадата ЄДРСР {earliest.isoformat()}"
            candidate["earliest_edrsr_date"] = earliest.isoformat()
            resolved.append(candidate)
        elif y == 2026:
            candidate["time_resolution"] = "не доведено первинне звернення до 30.06.2026"
            candidate["earliest_edrsr_date"] = earliest.isoformat() if earliest else ""
            excluded_time.append(candidate)
        else:
            candidate["time_resolution"] = "рік поза межами"
            excluded_time.append(candidate)
'''
new_resolution = '''    for candidate in candidates:
        y = int(candidate.get("year") or 0)
        reg_date = parse_date(candidate.get("registration_date", ""))
        earliest = earliest_by_case.get(candidate["canonical_number"])
        keep, resolution = resolve_primary_time(y, reg_date, earliest)
        candidate["time_resolution"] = resolution
        candidate["earliest_edrsr_date"] = earliest.isoformat() if earliest else ""
        if keep:
            resolved.append(candidate)
        else:
            excluded_time.append(candidate)
'''
if old_resolution in s:
    s = s.replace(old_resolution, new_resolution, 1)
elif "keep, resolution = resolve_primary_time" not in s:
    raise SystemExit("old temporal resolution block not found")

s = s.replace(
    '"rule": "exact DSA registration date; fallback year; 2026 missing date requires earliest EDRSR metadata <= 2026-06-30",',
    '"rule": "primary canonical case year must be 2024–2026; 2026 requires in-period DSA registration date or earliest EDRSR metadata <= 2026-06-30",',
    1,
)
path.write_text(s, encoding="utf-8")

test_path = root / "test_rules.py"
t = test_path.read_text(encoding="utf-8")
extra = '''


def test_primary_time_gate_excludes_old_primary_case_even_with_current_registration():
    from acquire_filter import primary_time_prefilter
    import datetime as dt
    keep, basis, pending = primary_time_prefilter(2023, dt.date(2026, 1, 10))
    assert not keep
    assert "поза межами" in basis
    assert not pending


def test_2026_late_higher_court_registration_can_be_resolved_by_earlier_metadata():
    from acquire_filter import primary_time_prefilter, resolve_primary_time
    import datetime as dt
    keep, _, pending = primary_time_prefilter(2026, dt.date(2026, 8, 1))
    assert keep and pending
    resolved, message = resolve_primary_time(2026, dt.date(2026, 8, 1), dt.date(2026, 5, 20))
    assert resolved
    assert "2026-05-20" in message
'''
if "test_primary_time_gate_excludes_old_primary_case" not in t:
    test_path.write_text(t + extra, encoding="utf-8")
print("primary-time patch applied")
