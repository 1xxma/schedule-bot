"""Быстрая проверка парсеров без Telegram."""

from datetime import date

from schedule import format_day, load_events


def main() -> None:
    events = load_events(work_duration_min=60, year=2026)
    print(f"work={sum(1 for e in events if e.kind=='work')} uni={sum(1 for e in events if e.kind=='uni')}")
    taya = next(e for e in events if e.title == "Тая")
    dima = next(e for e in events if e.title == "Дима")
    print(f"Тая: {(taya.end - taya.start).seconds // 60} мин, {taya.pay} ₽")
    print(f"Дима: {(dima.end - dima.start).seconds // 60} мин, {dima.pay} ₽")
    for d in (date(2026, 11, 4), date(2026, 11, 5)):
        print("=" * 40)
        print(format_day(d, events))


if __name__ == "__main__":
    main()
