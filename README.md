# Telegram-бот расписания (работа + пары)

Бот показывает день/неделю: работа, пары, пересечения, доход.

## Локальный запуск

```powershell
cd schedule-bot
# заполни .env (см. .env.example)
py -3 bot.py
```

## Деплой 24/7 (FadeHost, бесплатно)

1. Репозиторий уже можно запушить на GitHub (private).
2. Зайди на [fadehost.com](https://fadehost.com/telegram-bot-hosting/) → зарегистрируйся.
3. Apps → Host something → Telegram bot → подключи GitHub-репозиторий.
4. Start file: `bot.py`
5. Environment variables:

```env
TELEGRAM_BOT_TOKEN=твой_токен
BOT_TOKEN=твой_токен
ALLOWED_USER_ID=твой_telegram_id
WORK_DURATION_MIN=40
DATA_DIR=/data
```

6. Задеплой. В консоли должно быть `Started as @...`
7. **Останови локальный** `bot.py`, иначе будет Conflict 409.

Данные (`work.txt` / `uni.txt`) на FadeHost живут в `/data` и не сбрасываются при деплое.

## Кнопки

| Кнопка | Действие |
|--------|----------|
| Что сегодня? / завтра? | День |
| Эта неделя | Сводка + итог ₽ |
| Мой доход | 4 недели + план |
| Показать работу | Просмотр без риска стереть |
| Обновить работу / пары | Замена текста (со бэкапом) |
