# Школьное бюро находок + шеринг

Чат-бот для мессенджера МАКС. Помогает вернуть потерянные вещи и одалживать школьные принадлежности.

## Что умеет

- Принять заявку о потере — бот сам ищет совпадения с найденными вещами
- Зарегистрировать находку — владелец получит уведомление автоматически
- Показать каталог вещей которые лежат на вахте
- Шеринг — одолжить зарядку, ручку, циркуль на урок

## Стек

Python 3.11, aiohttp, PostgreSQL, Docker, Nginx

Работает в двух режимах: Long Polling (для локалки) и Webhook (продакшен).

## Запуск

### Локально (без Docker)

```bash
pip install -r requirements.txt
```

Создать файл `.env`:
```
MAX_BOT_TOKEN=токен_от_бота
```

```bash
python sferum_buro_bot.py
```

### Docker (локальная проверка)

```bash
docker compose up -d --build
```

Посмотреть логи:
```bash
docker logs -f sferumburo_bot
```

### Docker (продакшен с вебхуком)

Заполнить `.env`:
```
MAX_BOT_TOKEN=токен
WEBHOOK_BASE_URL=https://ваш-домен.ru
MAX_WEBHOOK_SECRET=секрет
DATABASE_URL=postgresql://postgres:пароль@db:5432/buro_bot
```

Запуск:
```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## Файлы

- `sferum_buro_bot.py` — основной файл, вся логика бота
- `requirements.txt` — зависимости
- `Dockerfile` — сборка образа
- `docker-compose.yml` — для локального запуска
- `docker-compose.prod.yml` — для сервера (с nginx)
- `nginx.conf` — конфиг прокси
- `.env` — переменные окружения (токен и т.д.)
- `webapp/` — мини-приложение (HTML/CSS/JS)
