"""Telegram-бот на чистом Bot API (без aiogram) — работает на Python 3.14."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_env(ROOT / ".env")

# Постоянный диск на FadeHost — /data (до импорта schedule)
if Path("/data").is_dir() and not os.getenv("DATA_DIR"):
    os.environ["DATA_DIR"] = "/data"

from schedule import (  # noqa: E402
    WEEKDAYS_RU,
    available_days,
    ensure_data_files,
    format_day,
    format_income_4weeks,
    format_week,
    load_events,
    read_uni_text,
    read_work_text,
    resolve_day,
    restore_work_from_backup,
    save_uni,
    save_work,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("schedule-bot")

MENU_TEXTS = {
    "Что сегодня?",
    "Что завтра?",
    "Эта неделя",
    "Мой доход",
    "Выбрать день",
    "Показать работу",
    "Обновить работу",
    "Обновить пары",
    "Вернуть работу",
}

# FadeHost и шаблоны часто ждут TELEGRAM_BOT_TOKEN
BOT_TOKEN = (
    os.getenv("BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
)
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID", "").strip()
WORK_DURATION_MIN = int(os.getenv("WORK_DURATION_MIN", "40"))

# chat_id -> waiting mode
WAITING: dict[int, str] = {}


class Tg:
    def __init__(self, token: str) -> None:
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, **payload) -> dict:
        data = {k: v for k, v in payload.items() if v is not None}
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            self.base + method,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            log.error("Telegram API error %s: %s", e.code, detail)
            raise

    def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
        chunks = _chunk(text, 4000)
        for i, part in enumerate(chunks):
            self.call(
                "sendMessage",
                chat_id=chat_id,
                text=part,
                reply_markup=reply_markup if i == len(chunks) - 1 else None,
            )

    def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)


def _chunk(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    parts: list[str] = []
    while text:
        parts.append(text[:size])
        text = text[size:]
    return parts


def main_kb() -> dict:
    return {
        "keyboard": [
            [{"text": "Что сегодня?"}, {"text": "Что завтра?"}],
            [{"text": "Эта неделя"}, {"text": "Мой доход"}],
            [{"text": "Выбрать день"}, {"text": "Показать работу"}],
            [{"text": "Обновить работу"}, {"text": "Обновить пары"}],
        ],
        "resize_keyboard": True,
    }


def day_picker_kb(days: list[date]) -> dict:
    rows: list[list[dict]] = []
    row: list[dict] = []
    for d in days:
        label = f"{d.strftime('%d.%m')} {WEEKDAYS_RU[d.weekday()][:2]}"
        row.append({"text": label, "callback_data": f"day:{d.isoformat()}"})
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if not rows:
        rows = [[{"text": "Нет дней", "callback_data": "noop"}]]
    return {"inline_keyboard": rows}


def allowed(user_id: int | None) -> bool:
    if not ALLOWED_USER_ID:
        return True
    return str(user_id) == ALLOWED_USER_ID


def get_events():
    return load_events(work_duration_min=WORK_DURATION_MIN)


def looks_like_schedule(text: str) -> bool:
    if text in MENU_TEXTS or text.startswith("/"):
        return False
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 1:
        return False
    import re

    work_line = re.compile(r"\d{1,2}\s+[а-яё]{3}", re.I)
    uni_line = re.compile(r"\d{2}\.\d{2}|пара\s*\|", re.I)
    return any(work_line.search(ln) or uni_line.search(ln) for ln in lines)


def handle_message(bot: Tg, msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    user_id = msg.get("from", {}).get("id")
    text = (msg.get("text") or "").strip()

    if not allowed(user_id):
        bot.send_message(chat_id, "Бот только для владельца.")
        return

    wait = WAITING.get(chat_id)

    if wait and text in MENU_TEXTS:
        WAITING.pop(chat_id, None)
        bot.send_message(chat_id, "Обновление отменено, старое расписание на месте.")
    elif wait and text == "/cancel":
        WAITING.pop(chat_id, None)
        bot.send_message(chat_id, "Ок, отменила. Расписание не трогала.", reply_markup=main_kb())
        return
    elif wait == "work":
        if not looks_like_schedule(text):
            bot.send_message(
                chat_id,
                "Это не похоже на расписание работы — ничего не сохранила.\n"
                "Пришли текст заново или /cancel",
            )
            return
        save_work(text)
        WAITING.pop(chat_id, None)
        n = sum(1 for e in get_events() if e.kind == "work")
        bot.send_message(
            chat_id,
            f"Рабочее расписание сохранено. Занятий: {n}\n"
            f"Предыдущая версия лежит в бэкапе (кнопка «Вернуть работу»).",
            reply_markup=main_kb(),
        )
        return
    elif wait == "uni":
        if not looks_like_schedule(text):
            bot.send_message(
                chat_id,
                "Это не похоже на расписание пар — ничего не сохранила.\n"
                "Пришли текст заново или /cancel",
            )
            return
        save_uni(text)
        WAITING.pop(chat_id, None)
        n = sum(1 for e in get_events() if e.kind == "uni")
        bot.send_message(
            chat_id,
            f"Расписание пар сохранено. Пар: {n}",
            reply_markup=main_kb(),
        )
        return

    if text == "/cancel":
        WAITING.pop(chat_id, None)
        bot.send_message(chat_id, "Ок, отменила.", reply_markup=main_kb())
        return

    if text in ("/start", "start"):
        bot.send_message(
            chat_id,
            "Привет! Расписание: работа + пары + доход.\n\n"
            "• Сегодня / завтра / эта неделя\n"
            "• Мой доход — сумма за 4 недели\n"
            "• Показать работу — текущий текст без риска стереть\n"
            "При пересечении пишу, к какому времени уйти с пары.",
            reply_markup=main_kb(),
        )
        return

    if text in ("Что сегодня?", "/today"):
        bot.send_message(chat_id, format_day(resolve_day("today"), get_events()), reply_markup=main_kb())
        return

    if text in ("Что завтра?", "/tomorrow"):
        bot.send_message(chat_id, format_day(resolve_day("tomorrow"), get_events()), reply_markup=main_kb())
        return

    if text in ("Эта неделя", "/week"):
        bot.send_message(chat_id, format_week(get_events()), reply_markup=main_kb())
        return

    if text in ("Мой доход", "/income"):
        bot.send_message(chat_id, format_income_4weeks(get_events()), reply_markup=main_kb())
        return

    if text in ("Выбрать день", "/day"):
        days = available_days(get_events())
        if not days:
            bot.send_message(chat_id, "Пока нет сохранённых дней. Сначала загрузи расписание.")
            return
        bot.send_message(chat_id, "Выбери день:", reply_markup=day_picker_kb(days))
        return

    if text in ("Показать работу", "/show_work"):
        current = read_work_text().strip()
        if not current:
            bot.send_message(chat_id, "Рабочее расписание пока пустое.", reply_markup=main_kb())
            return
        bot.send_message(
            chat_id,
            "Текущее рабочее расписание (только просмотр):\n\n" + current,
            reply_markup=main_kb(),
        )
        return

    if text in ("Вернуть работу", "/undo_work"):
        if restore_work_from_backup():
            n = sum(1 for e in get_events() if e.kind == "work")
            bot.send_message(
                chat_id,
                f"Вернула предыдущую версию работы. Занятий: {n}",
                reply_markup=main_kb(),
            )
        else:
            bot.send_message(chat_id, "Бэкапа ещё нет.", reply_markup=main_kb())
        return

    if text in ("Обновить работу", "/work"):
        WAITING[chat_id] = "work"
        current = read_work_text().strip()
        bot.send_message(
            chat_id,
            "Сейчас пришлю текущее расписание — можешь скопировать, поправить и прислать обратно.\n"
            "Пока не пришлёшь новый текст, старое НЕ сотрётся.\n"
            "Если передумаешь — нажми любую другую кнопку или /cancel.",
            reply_markup=main_kb(),
        )
        if current:
            bot.send_message(chat_id, current)
        else:
            bot.send_message(
                chat_id,
                "Пока пусто. Пример:\n"
                "3 ноя (ВТ): Иван2 (12)\n"
                "4 ноя (СР): Тая (11), Даниил (18:00), Дима (19)",
            )
        return

    if text in ("Обновить пары", "/uni"):
        WAITING[chat_id] = "uni"
        current = read_uni_text().strip()
        bot.send_message(
            chat_id,
            "Пришли новое расписание пар одним сообщением.\n"
            "Старое не сотрётся, пока не пришлёшь текст. Или /cancel.",
            reply_markup=main_kb(),
        )
        if current:
            preview = current if len(current) <= 3500 else current[:3500] + "\n…"
            bot.send_message(chat_id, "Текущие пары:\n\n" + preview)
        return

    if text == "/reload":
        events = get_events()
        bot.send_message(
            chat_id,
            f"Перечитала файлы.\n"
            f"Работа: {sum(1 for e in events if e.kind == 'work')}\n"
            f"Пары: {sum(1 for e in events if e.kind == 'uni')}",
            reply_markup=main_kb(),
        )
        return

    bot.send_message(
        chat_id,
        "Не поняла. Нажми кнопку меню: сегодня / неделя / доход.",
        reply_markup=main_kb(),
    )


def handle_callback(bot: Tg, cq: dict) -> None:
    user_id = cq.get("from", {}).get("id")
    data = cq.get("data") or ""
    msg = cq.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    cq_id = cq["id"]

    if not allowed(user_id):
        bot.answer_callback(cq_id, "Нет доступа")
        return

    if data == "noop" or chat_id is None:
        bot.answer_callback(cq_id)
        return

    if data.startswith("day:"):
        day = date.fromisoformat(data.split(":", 1)[1])
        bot.send_message(chat_id, format_day(day, get_events()), reply_markup=main_kb())
        bot.answer_callback(cq_id)
        return

    bot.answer_callback(cq_id)


def run() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Укажи BOT_TOKEN или TELEGRAM_BOT_TOKEN в .env / переменных хостинга")

    ensure_data_files()
    log.info("DATA_DIR=%s", os.getenv("DATA_DIR", "data"))

    bot = Tg(BOT_TOKEN)
    me = bot.call("getMe")
    log.info("Started as @%s", me.get("result", {}).get("username"))

    offset = 0
    while True:
        try:
            updates = bot.call(
                "getUpdates",
                offset=offset,
                timeout=50,
                allowed_updates=["message", "callback_query"],
            )
        except Exception:
            log.exception("getUpdates failed, retry in 3s")
            time.sleep(3)
            continue

        for upd in updates.get("result", []):
            offset = upd["update_id"] + 1
            try:
                if "message" in upd:
                    handle_message(bot, upd["message"])
                elif "callback_query" in upd:
                    handle_callback(bot, upd["callback_query"])
            except Exception:
                log.exception("Failed to handle update %s", upd.get("update_id"))


if __name__ == "__main__":
    run()
