"""Сборка дневного расписания, недели, дохода и пересечений."""

from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from parsers import MSK, Event, overlaps, parse_uni, parse_work

WEEKDAYS_RU = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)
WEEKDAYS_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

import os

_BUNDLE_DATA = Path(__file__).resolve().parent / "data"


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", str(_BUNDLE_DATA)))


def _work_file() -> Path:
    return data_dir() / "work.txt"


def _uni_file() -> Path:
    return data_dir() / "uni.txt"


def _work_bak() -> Path:
    return data_dir() / "work.bak.txt"


def _uni_bak() -> Path:
    return data_dir() / "uni.bak.txt"


def ensure_data_files() -> None:
    """Создаёт DATA_DIR и копирует стартовые файлы, если их ещё нет."""
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name in ("work.txt", "uni.txt"):
        dest = d / name
        src = _BUNDLE_DATA / name
        if not dest.exists() and src.exists() and src.resolve() != dest.resolve():
            shutil.copy2(src, dest)


def load_events(work_duration_min: int = 40, year: int | None = None) -> list[Event]:
    ensure_data_files()
    work_text = read_work_text()
    uni_text = read_uni_text()
    year = year or datetime.now(MSK).year
    return parse_work(work_text, year=year, duration_min=work_duration_min) + parse_uni(
        uni_text, year=year
    )


def read_work_text() -> str:
    path = _work_file()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_uni_text() -> str:
    path = _uni_file()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def save_work(text: str) -> None:
    ensure_data_files()
    path = _work_file()
    if path.exists():
        shutil.copy2(path, _work_bak())
    path.write_text(text.strip() + "\n", encoding="utf-8")


def save_uni(text: str) -> None:
    ensure_data_files()
    path = _uni_file()
    if path.exists():
        shutil.copy2(path, _uni_bak())
    path.write_text(text.strip() + "\n", encoding="utf-8")


def restore_work_from_backup() -> bool:
    bak = _work_bak()
    if not bak.exists():
        return False
    shutil.copy2(bak, _work_file())
    return True


def available_days(events: list[Event]) -> list[date]:
    return sorted({e.day for e in events})


def events_for_day(events: list[Event], day: date) -> list[Event]:
    return sorted([e for e in events if e.day == day], key=lambda e: e.start)


def events_in_range(events: list[Event], start: date, end: date) -> list[Event]:
    return [e for e in events if start <= e.day <= end]


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_range(day: date | None = None) -> tuple[date, date]:
    start = monday_of(day or datetime.now(MSK).date())
    return start, start + timedelta(days=6)


def conflicting_uni(events: list[Event]) -> dict[int, datetime]:
    """Индекс пары -> время начала работы, из‑за которой уходить."""
    work = [e for e in events if e.kind == "work"]
    bad: dict[int, datetime] = {}
    for i, e in enumerate(events):
        if e.kind != "uni":
            continue
        hits = [w for w in work if overlaps(e, w)]
        if hits:
            bad[i] = min(hits, key=lambda w: w.start).start
    return bad


def fmt_range(e: Event) -> str:
    return f"{e.start.strftime('%H:%M')}–{e.end.strftime('%H:%M')}"


def day_pay(events: list[Event], day: date) -> int:
    return sum(e.pay for e in events_for_day(events, day) if e.kind == "work")


def format_day(day: date, events: list[Event]) -> str:
    day_events = events_for_day(events, day)
    header = f"📅 {WEEKDAYS_RU[day.weekday()]}, {day.strftime('%d.%m.%Y')}"

    if not day_events:
        return f"{header}\n\nНа этот день ничего нет."

    conflict = conflicting_uni(day_events)
    work_items = [e for e in day_events if e.kind == "work"]
    uni_items = [(i, e) for i, e in enumerate(day_events) if e.kind == "uni"]

    lines = [header, ""]

    lines.append("💼 Работа")
    total_pay = 0
    if work_items:
        for e in work_items:
            total_pay += e.pay
            lines.append(f"• {fmt_range(e)} — {e.title} · {e.pay} ₽")
        lines.append(f"💰 За день: {total_pay} ₽")
    else:
        lines.append("• нет")
        lines.append("💰 За день: 0 ₽")

    lines.append("")
    lines.append("🎓 Пары")
    if uni_items:
        for i, e in uni_items:
            if i in conflict:
                leave_at = conflict[i].strftime("%H:%M")
                mark = f"  ⚠️ (С ЭТОЙ ПАРЫ УЙТИ к {leave_at})"
            else:
                mark = ""
            lines.append(f"• {fmt_range(e)} — {e.title}{mark}")
            if e.meta:
                lines.append(f"  {e.meta}")
    else:
        lines.append("• нет")

    if conflict:
        lines.append("")
        lines.append("⚠️ Есть пересечение работы и пар — смотри пометки выше.")

    return "\n".join(lines)


def format_week(events: list[Event], day: date | None = None) -> str:
    start, end = week_range(day)
    lines = [f"📆 Неделя {start.strftime('%d.%m')}–{end.strftime('%d.%m.%Y')}", ""]
    week_total = 0
    conflict_days: list[str] = []

    for i in range(7):
        d = start + timedelta(days=i)
        day_events = events_for_day(events, d)
        work = [e for e in day_events if e.kind == "work"]
        uni = [e for e in day_events if e.kind == "uni"]
        pay = sum(e.pay for e in work)
        week_total += pay

        has_conflict = bool(conflicting_uni(day_events))
        flag = " ⚠️" if has_conflict else ""
        if has_conflict:
            conflict_days.append(WEEKDAYS_SHORT[i])

        if not work and not uni:
            lines.append(f"{WEEKDAYS_SHORT[i]} {d.strftime('%d.%m')} — выходной{flag}")
            continue

        if work:
            work_bit = ", ".join(f"{e.title} {e.start.strftime('%H:%M')}" for e in work)
            money_bit = f" · {pay} ₽"
        else:
            work_bit = "работы нет"
            money_bit = ""
        uni_bit = f"{len(uni)} пар" if uni else "пар нет"
        lines.append(
            f"{WEEKDAYS_SHORT[i]} {d.strftime('%d.%m')} — {work_bit}{money_bit} · {uni_bit}{flag}"
        )

    lines.append("")
    lines.append(f"💰 Итого за неделю: {week_total} ₽")
    if conflict_days:
        lines.append(f"⚠️ Пересечения: {', '.join(conflict_days)}")
    return "\n".join(lines)


def format_income_4weeks(events: list[Event], day: date | None = None) -> str:
    """Отчёт за текущую + 3 предыдущие недели (4 недели)."""
    ref = day or datetime.now(MSK).date()
    this_monday = monday_of(ref)
    first_monday = this_monday - timedelta(weeks=3)
    last_sunday = this_monday + timedelta(days=6)

    lines = [
        f"📊 Доход за 4 недели",
        f"{first_monday.strftime('%d.%m')}–{last_sunday.strftime('%d.%m.%Y')}",
        "",
    ]
    grand = 0
    lessons = 0

    for w in range(4):
        start = first_monday + timedelta(weeks=w)
        end = start + timedelta(days=6)
        chunk = [e for e in events if e.kind == "work" and start <= e.day <= end]
        pay = sum(e.pay for e in chunk)
        n = len(chunk)
        grand += pay
        lessons += n
        mark = " ← эта" if start == this_monday else ""
        lines.append(
            f"Неделя {start.strftime('%d.%m')}–{end.strftime('%d.%m')}: "
            f"{n} зан. · {pay} ₽{mark}"
        )

    lines.append("")
    lines.append(f"💰 Всего за 4 недели: {grand} ₽")
    lines.append(f"🧾 Занятий: {lessons}")
    if lessons:
        lines.append(f"📈 Среднее за неделю: {grand // 4} ₽")

    next_start = this_monday + timedelta(weeks=1)
    next_end = next_start + timedelta(days=6)
    next_chunk = [e for e in events if e.kind == "work" and next_start <= e.day <= next_end]
    if next_chunk:
        next_pay = sum(e.pay for e in next_chunk)
        lines.append("")
        lines.append(
            f"🗓️ След. неделя {next_start.strftime('%d.%m')}–{next_end.strftime('%d.%m')} "
            f"(план): {len(next_chunk)} зан. · {next_pay} ₽"
        )

    # топ учеников за период
    by_name: dict[str, tuple[int, int]] = {}
    period = [
        e
        for e in events
        if e.kind == "work" and first_monday <= e.day <= last_sunday
    ]
    for e in period:
        cnt, money = by_name.get(e.title, (0, 0))
        by_name[e.title] = (cnt + 1, money + e.pay)
    if by_name:
        lines.append("")
        lines.append("👥 По ученикам:")
        for name, (cnt, money) in sorted(by_name.items(), key=lambda x: -x[1][1]):
            lines.append(f"• {name}: {cnt} · {money} ₽")

    return "\n".join(lines)


def resolve_day(which: str) -> date:
    now = datetime.now(MSK).date()
    if which == "today":
        return now
    if which == "tomorrow":
        return now + timedelta(days=1)
    raise ValueError(which)
