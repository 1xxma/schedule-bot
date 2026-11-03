"""Длительность и ставка по ученикам."""

from __future__ import annotations

DEFAULT_DURATION_MIN = 40
DEFAULT_PAY = 600

# минуты занятия
DURATION_BY_NAME = {
    "тая": 90,
    "дима": 40,
    "алена": 60,
}

# рублей за занятие
PAY_BY_NAME = {
    "тая": 1000,
    "дима": 500,
    "алена": 600,
}


def _key(name: str) -> str:
    return name.strip().lower()


def duration_for(name: str, default: int = DEFAULT_DURATION_MIN) -> int:
    return DURATION_BY_NAME.get(_key(name), default)


def pay_for(name: str, default: int = DEFAULT_PAY) -> int:
    return PAY_BY_NAME.get(_key(name), default)
