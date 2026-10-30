"""
Turn a Turkish time expression ("geçen hafta", "son 3 gün", "1-15 Ekim") into a concrete range.

Deterministic on purpose: the model names the period, code does the calendar arithmetic, so a
"last week" never drifts by a day. Ranges are calendar days in settings.newsletter_timezone (the
app's local zone) and end at "now" when the period is still running. Returns None for anything it
doesn't understand — the agent then asks the user instead of guessing.
"""
import re
from datetime import date, datetime, time, timedelta
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from app.core.config import settings

MONTHS = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
}
_UNITS = {
    "saat": "hour", "gün": "day", "gun": "day", "hafta": "week", "ay": "month",
    "yıl": "year", "yil": "year", "sene": "year",
}
_NUMBER_WORDS = {
    "bir": 1, "iki": 2, "üç": 3, "uc": 3, "dört": 4, "dort": 4, "beş": 5, "bes": 5,
    "altı": 6, "alti": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10,
}
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_UNIT_RE = "|".join(sorted(_UNITS, key=len, reverse=True))
_RANGE_SEP = r"\s*(?:-|–|ile)\s*"
_SINGLE = {
    "bugün": "today", "bugun": "today",
    "dün": "yesterday", "dun": "yesterday",
    "bu hafta": "this_week",
    "geçen hafta": "last_week", "gecen hafta": "last_week", "geçtiğimiz hafta": "last_week",
    "gectigimiz hafta": "last_week", "önceki hafta": "last_week",
    "bu ay": "this_month",
    "geçen ay": "last_month", "gecen ay": "last_month", "geçtiğimiz ay": "last_month",
    "gectigimiz ay": "last_month", "önceki ay": "last_month",
    "bu yıl": "this_year", "bu yil": "this_year", "bu sene": "this_year",
    "geçen yıl": "last_year", "gecen yil": "last_year", "geçen sene": "last_year",
    "gecen sene": "last_year",
}


def _start(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def _end(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(23, 59, 59), tzinfo=tz)


def _next_month(year: int, month: int) -> date:
    return date(year + (month == 12), month % 12 + 1, 1)


def _months_back(day: date, months: int) -> date:
    """The same day `months` months earlier (clamped to the month's last day)."""
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    month += 1
    last = (_next_month(year, month) - timedelta(days=1)).day
    return date(year, month, min(day.day, last))


def _normalize(expression: str) -> str:
    text = (expression or "").strip().lower().replace("i̇", "i").replace("’", "'")
    # "Ekim'de" → "ekim"; but keep "Eylül'den beri" whole: _SINCE reads that ending itself.
    text = re.sub(r"'(?:de|da|te|ta|den|dan|ten|tan|in|ın|un|ün|nin|nın)\b(?!\s+(?:beri|bu yana|itibaren))",
                  "", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    # "ağustos ile eylül arasında" → "ağustos ile eylül"
    text = re.sub(r" (?:arası|arasi|arasında|arasinda|arasındaki|arasindaki)$", "", text)
    # "2026 eylül" → "eylül 2026"; "2019 yılının tamamı" → "2019"; "ağustos ayında" → "ağustos"
    text = re.sub(rf"^(\d{{4}}) ({_MONTH_RE})\b", r"\2 \1", text)
    text = re.sub(r"^(\d{4}) (?:yıl|yil|sene)\w*(?: (?:tamamı|tamami|boyunca))?$", r"\1", text)
    return re.sub(rf"^({_MONTH_RE})((?: \d{{4}})?) ay\w*$", r"\1\2", text)


def _number(token: Optional[str]) -> Optional[int]:
    if token is None:
        return 1
    return int(token) if token.isdigit() else _NUMBER_WORDS.get(token)


def _result(start: datetime, end: datetime, label: str) -> Dict[str, str]:
    return {"from": start.isoformat(timespec="seconds"), "to": end.isoformat(timespec="seconds"), "label": label}


def _named(kind: str, now: datetime, tz: ZoneInfo) -> Dict[str, str]:
    today = now.date()
    if kind == "today":
        return _result(_start(today, tz), now, "Bugün")
    if kind == "yesterday":
        day = today - timedelta(days=1)
        return _result(_start(day, tz), _end(day, tz), "Dün")
    if kind == "this_week":
        return _result(_start(today - timedelta(days=today.weekday()), tz), now, "Bu hafta")
    if kind == "last_week":
        monday = today - timedelta(days=today.weekday() + 7)
        return _result(_start(monday, tz), _end(monday + timedelta(days=6), tz), "Geçen hafta")
    if kind == "this_month":
        return _result(_start(today.replace(day=1), tz), now, "Bu ay")
    if kind == "last_month":
        first = _months_back(today.replace(day=1), 1)
        last = _next_month(first.year, first.month) - timedelta(days=1)
        return _result(_start(first, tz), _end(last, tz), "Geçen ay")
    if kind == "this_year":
        return _result(_start(date(today.year, 1, 1), tz), now, "Bu yıl")
    year = today.year - 1  # last_year
    return _result(_start(date(year, 1, 1), tz), _end(date(year, 12, 31), tz), "Geçen yıl")


def _last_n(count: int, unit: str, unit_word: str, now: datetime, tz: ZoneInfo) -> Dict[str, str]:
    """"son N <birim>": a rolling window ending now; day-based units start at midnight."""
    today = now.date()
    label = f"Son {count} {unit_word}"
    if unit == "hour":
        return _result(now - timedelta(hours=count), now, label)
    if unit == "day":
        first = today - timedelta(days=count - 1)
    elif unit == "week":
        first = today - timedelta(days=7 * count - 1)
    elif unit == "month":
        first = _months_back(today, count) + timedelta(days=1)
    else:
        first = _months_back(today, 12 * count) + timedelta(days=1)
    return _result(_start(first, tz), now, label)


def _year_for(month: int, today: date) -> int:
    """A month named without a year is the most recent one (this year, or last year if later)."""
    return today.year if month <= today.month else today.year - 1


# "…den beri / …dan bu yana / …ten itibaren": from the start of the named period until now.
_SINCE = re.compile(r"^(.+?)'?(n?dan|n?den|tan|ten)\s+(?:bu yana|beri|itibaren)$")
# Thirds of a month: "ekim başı" (1-10), "ekim ortası" (11-20), "ekim sonu" (21-end).
_MONTH_PART = {"başı": (1, 10), "basi": (1, 10), "ortası": (11, 20), "ortasi": (11, 20), "sonu": (21, 31)}


def resolve_time_range(expression: str, now: Optional[datetime] = None) -> Optional[Dict[str, str]]:
    """{"from", "to", "label"} (ISO 8601 with offset) for `expression`, or None if not understood."""
    tz = ZoneInfo(settings.newsletter_timezone)
    now = (now or datetime.now(tz)).astimezone(tz)
    text = _normalize(expression)
    if not text:
        return None
    since = _SINCE.match(text)
    if since:
        # "sonundan" = "sonu" + "ndan"; also try the stem with the buffer "n" kept.
        for base in (since.group(1), since.group(1) + since.group(2)[:-3]):
            resolved = _resolve(base, now, tz)
            if resolved is not None:
                return _result(datetime.fromisoformat(resolved["from"]), now, f"{base} → bugün")
        return None
    resolved = _resolve_with_case(text, now, tz)
    if resolved is None:
        # Two periods compared ("bu hafta ile geçen hafta"): the span covering both, so the
        # coverage check and the plan see all of it; the steps then split it.
        parts = re.split(r" (?:ile|ve|vs\.?) ", text, maxsplit=1)
        if len(parts) == 2:
            first, second = (_resolve_with_case(part, now, tz) for part in parts)
            if first and second:
                start = min(first["from"], second["from"], key=datetime.fromisoformat)
                end = max(first["to"], second["to"], key=datetime.fromisoformat)
                return {"from": start, "to": end, "label": f"{first['label']} ve {second['label']}"}
    return resolved


def _resolve_with_case(text: str, now: datetime, tz: ZoneInfo) -> Optional[Dict[str, str]]:
    resolved = _resolve(text, now, tz)
    if resolved is None:
        # The model copies case endings from the question ("son 30 günde", "bu haftanın").
        head, _, last = text.rpartition(" ")
        for suffix in _CASE_SUFFIXES:
            if last.endswith(suffix) and len(last) > len(suffix):
                resolved = _resolve(f"{head} {last[:-len(suffix)]}".strip(), now, tz)
                if resolved is not None:
                    break
    return resolved


_PERIOD_WORD = re.compile(rf"\d|\b(?:{_MONTH_RE}|{_UNIT_RE}|bugün|bugun|dün|dun|beri|yana|itibaren|önce|once)")


def named_by_user(expression: str, user_texts) -> bool:
    """Whether the expression's period words come from what the user wrote (the question, their
    answers, earlier turns). The model sometimes adds a period of its own ("Son 30 gün" for a
    question naming none), which then hides older articles. One shared word is enough:
    "Ekim'in ilk yarısı" → "1-15 Ekim"."""
    user = " " + _normalize(" ".join(user_texts)) + " "
    for token in re.findall(r"\w+", _normalize(expression)):
        if token.isdigit():
            if re.search(rf"(?<!\d){token}(?!\d)", user):
                return True
        elif _PERIOD_WORD.match(token) and re.search(rf"\b{re.escape(token[:4])}", user):
            return True
    return False


def mentions_period(expression: str) -> bool:
    """Whether the expression names a period at all. "son" alone (from "son 5 haber") doesn't —
    asking the user which period they meant is then pointless."""
    return bool(_PERIOD_WORD.search(_normalize(expression)))


# Locative / ablative / genitive / -ki endings, longest first (incl. the buffer "n").
_CASE_SUFFIXES = ("ndaki", "ndeki", "daki", "deki", "taki", "teki", "ndan", "nden", "nda", "nde", "nın", "nin", "nun",
                  "nün", "dan", "den", "tan", "ten", "ın", "in", "un", "ün", "da", "de", "ta", "te", "ki")


def _resolve(text: str, now: datetime, tz: ZoneInfo) -> Optional[Dict[str, str]]:
    today = now.date()

    if text in _SINGLE:
        return _named(_SINGLE[text], now, tz)

    # "son 3 gün", "son hafta", "geçtiğimiz iki ay", "son 24 saat"
    match = re.fullmatch(rf"(?:son|geçtiğimiz|gectigimiz|geçen|gecen) (?:(\w+) )?({_UNIT_RE})", text)
    if match:
        count = _number(match.group(1))
        if not count or count <= 0:
            return None
        return _last_n(count, _UNITS[match.group(2)], match.group(2), now, tz)

    # "3 gün önce": that whole day
    match = re.fullmatch(r"(\w+) (?:gün|gun) (?:önce|once)", text)
    if match:
        count = _number(match.group(1))
        if count is None:
            return None
        day = today - timedelta(days=count)
        return _result(_start(day, tz), _end(day, tz), f"{count} gün önce")

    # "2026-10-01" or "2026-10-01 - 2026-10-15"
    match = re.fullmatch(rf"(\d{{4}}-\d{{2}}-\d{{2}})(?:{_RANGE_SEP}(\d{{4}}-\d{{2}}-\d{{2}}))?", text)
    if match:
        try:
            first = date.fromisoformat(match.group(1))
            last = date.fromisoformat(match.group(2)) if match.group(2) else first
        except ValueError:
            return None
        return _calendar_range(first, last, text, now, tz)

    # "2019": the whole year (until now when it is the current one)
    if re.fullmatch(r"\d{4}", text):
        year = int(text)
        return _calendar_range(date(year, 1, 1), date(year, 12, 31), text, now, tz)

    # "1 eylül - 15 ekim [2026]"
    match = re.fullmatch(
        rf"(\d{{1,2}}) ({_MONTH_RE})(?: (\d{{4}}))?{_RANGE_SEP}(\d{{1,2}}) ({_MONTH_RE})(?: (\d{{4}}))?", text
    )
    if match:
        d1, m1, y1, d2, m2, y2 = match.groups()
        month1, month2 = MONTHS[m1], MONTHS[m2]
        year2 = int(y2) if y2 else _year_for(month2, today)
        year1 = int(y1) if y1 else (year2 if month1 <= month2 else year2 - 1)
        try:
            return _calendar_range(date(year1, month1, int(d1)), date(year2, month2, int(d2)), text, now, tz)
        except ValueError:
            return None

    # "ekim sonu [2026]", "eylül başı"
    match = re.fullmatch(rf"({_MONTH_RE})(?: (\d{{4}}))? ({'|'.join(_MONTH_PART)})", text)
    if match:
        month_name, year_text, part = match.groups()
        month = MONTHS[month_name]
        year = int(year_text) if year_text else _year_for(month, today)
        last_day = (_next_month(year, month) - timedelta(days=1)).day
        first_day, end_day = _MONTH_PART[part]
        return _calendar_range(date(year, month, first_day), date(year, month, min(end_day, last_day)), text, now, tz)

    # "1-15 ekim [2026]", "5 ekim [2026]", "ekim [2026]"
    match = re.fullmatch(rf"(?:(\d{{1,2}})(?:{_RANGE_SEP}(\d{{1,2}}))? )?({_MONTH_RE})(?: (\d{{4}}))?", text)
    if match:
        d1, d2, month_name, year_text = match.groups()
        month = MONTHS[month_name]
        year = int(year_text) if year_text else _year_for(month, today)
        try:
            if d1 and d2:
                first, last = date(year, month, int(d1)), date(year, month, int(d2))
            elif d1:
                first = last = date(year, month, int(d1))
            else:
                first, last = date(year, month, 1), _next_month(year, month) - timedelta(days=1)
        except ValueError:
            return None
        return _calendar_range(first, last, text, now, tz)

    return None


def _calendar_range(first: date, last: date, label: str, now: datetime, tz: ZoneInfo) -> Optional[Dict[str, str]]:
    if last < first:
        return None
    end = now if last >= now.date() else _end(last, tz)
    if end < _start(first, tz):
        return None  # entirely in the future
    return _result(_start(first, tz), end, label)
