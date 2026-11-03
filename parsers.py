"""Парсеры рабочих занятий и пар из текста."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

# Москва без tzdata (на Windows часто нет IANA-зон)
MSK = timezone(timedelta(hours=3))

MONTHS_RU = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "мая": 5,
    "май": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}


@dataclass
class Event:
    kind: str  # work | uni
    title: str
    start: datetime
    end: datetime
    meta: str = ""
    pay: int = 0  # только для work

    @property
    def day(self) -> date:
        return self.start.date()


def _parse_clock(raw: str) -> time:
    raw = raw.strip()
    if ":" in raw:
        h, m = raw.split(":", 1)
        return time(int(h), int(m))
    return time(int(raw), 0)


def parse_work(text: str, year: int | None = None, duration_min: int = 40) -> list[Event]:
    """
    Формат:
      3 ноя (ВТ): Иван2 (12)
      4 ноя (СР): Тая (11), Даниил (18:00), Дима (19)
      2 ноя (ПН): X
    """
    from people import duration_for, pay_for

    year = year or datetime.now(MSK).year
    events: list[Event] = []

    line_re = re.compile(
        r"(?P<day>\d{1,2})\s+(?P<mon>[а-яё]+)\s*\([^)]*\)\s*:\s*(?P<body>.+)",
        re.IGNORECASE,
    )
    item_re = re.compile(r"(?P<name>[^,]+?)\s*\((?P<clock>\d{1,2}(?::\d{2})?)\)")

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = line_re.match(line)
        if not m:
            continue

        mon_key = m.group("mon").lower()[:3]
        month = MONTHS_RU.get(mon_key)
        if not month:
            continue

        day = int(m.group("day"))
        body = m.group("body").strip()
        if body.upper() == "X" or body == "—":
            continue

        for item in item_re.finditer(body):
            name = item.group("name").strip(" ,")
            start_t = _parse_clock(item.group("clock"))
            start = datetime.combine(date(year, month, day), start_t, tzinfo=MSK)
            mins = duration_for(name, duration_min)
            end = start + timedelta(minutes=mins)
            events.append(
                Event(
                    kind="work",
                    title=name,
                    start=start,
                    end=end,
                    pay=pay_for(name),
                )
            )

    return events


def parse_uni(text: str, year: int | None = None) -> list[Event]:
    """
    Формат:
      🗓️ Вторник, 03.11
      13:50–15:20 - 4 пара | ПР  Теория вероятностей...
      🧑‍🏫 Олару Е.М. · 🚪 303
    """
    year = year or datetime.now(MSK).year
    events: list[Event] = []

    day_re = re.compile(r"(?:🗓️\s*)?(?P<wd>[А-Яа-яЁё]+),\s*(?P<dd>\d{2})\.(?P<mm>\d{2})")
    pair_re = re.compile(
        r"(?P<sh>\d{1,2}):(?P<sm>\d{2})\s*[–\-—]\s*(?P<eh>\d{1,2}):(?P<em>\d{2})"
        r"\s*-\s*(?P<num>\d+)\s*пара\s*\|\s*(?P<kind>\S+)\s+(?P<title>.+)"
    )
    teacher_re = re.compile(r"🧑‍🏫\s*(?P<teacher>.+?)(?:\s*[·•]\s*🚪\s*(?P<room>.+))?$")

    current_day: date | None = None
    pending: Event | None = None

    def flush() -> None:
        nonlocal pending
        if pending:
            events.append(pending)
            pending = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue

        dm = day_re.search(line)
        if dm:
            flush()
            current_day = date(year, int(dm.group("mm")), int(dm.group("dd")))
            continue

        if current_day is None:
            continue

        pm = pair_re.match(line)
        if pm:
            flush()
            start = datetime.combine(
                current_day,
                time(int(pm.group("sh")), int(pm.group("sm"))),
                tzinfo=MSK,
            )
            end = datetime.combine(
                current_day,
                time(int(pm.group("eh")), int(pm.group("em"))),
                tzinfo=MSK,
            )
            title = (
                f"{pm.group('num')} пара | {pm.group('kind')}  "
                f"{pm.group('title').strip()}"
            )
            pending = Event(kind="uni", title=title, start=start, end=end)
            continue

        if pending:
            tm = teacher_re.match(line)
            if tm:
                teacher = tm.group("teacher").strip()
                room = (tm.group("room") or "").strip()
                meta = teacher
                if room:
                    meta += f" · {room}"
                pending.meta = meta

    flush()
    return events


def overlaps(a: Event, b: Event) -> bool:
    return a.start < b.end and b.start < a.end
