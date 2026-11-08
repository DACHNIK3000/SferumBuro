# Деплой на сервер

## Почему docker-compose.prod.yml отдельный

На хакатонном сервере уже крутятся чужие контейнеры. Чтобы не сломать их, сделал отдельный prod-файл:
- порт PostgreSQL не торчит наружу (нет конфликта с чужим postgres на 5432)
- контейнеры с уникальными именами: `sferumburo_bot_prod`, `sferumburo_postgres_prod`
- база хранится в отдельном volume `sferumburo_pgdata_prod`

## Шаг 1 — загрузить файлы

Через FileZilla или git clone закинуть на сервер:
- `sferum_buro_bot.py`
- `requirements.txt`
- `Dockerfile`
- `docker-compose.prod.yml`
- `.env` (может быть скрытым — включи показ скрытых файлов в FileZilla)
- папку `webapp/`

## Шаг 2 — запуск

```bash
cd /путь/до/папки
docker compose -f docker-compose.prod.yml up -d --build
```

## Шаг 3 — проверка

```bash
docker ps
```

Должны быть видны `sferumburo_bot_prod` и `sferumburo_postgres_prod` со статусом `Up`.

Если что-то не так — смотреть логи:
```bash
docker logs -f sferumburo_bot_prod
```
