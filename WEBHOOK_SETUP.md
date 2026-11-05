# Настройка Webhook для Сферум Бота

Сферум настоятельно рекомендует использовать Webhook, если бот крутится на реальном сервере. Это быстрее, надежнее и потребляет меньше ресурсов.

В нашем коде **уже всё готово** для работы через Webhook. Бот автоматически запустится в режиме Webhook, если в файле `.env` указан адрес!

## Шаг 1: Настройка домена и Nginx на сервере
Для работы Webhook требуется домен (например, `bot.myschool.ru`) и SSL-сертификат (https).
Поскольку на вашем сервере уже есть другие контейнеры, скорее всего, там установлен Nginx.

Вам нужно создать конфигурацию Nginx (обычно в `/etc/nginx/sites-available/bot`), которая перенаправляет запросы на порт **8080**, который мы открыли в `docker-compose.prod.yml`:

```nginx
server {
    listen 80;
    server_name bot.myschool.ru; # ВАШ ДОМЕН

    # Перенаправление HTTP на HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name bot.myschool.ru; # ВАШ ДОМЕН

    # Пути к вашим SSL сертификатам (например, от Certbot/Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/bot.myschool.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bot.myschool.ru/privkey.pem;

    location / {
        # Перенаправляем запросы внутрь Docker-контейнера с ботом
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
*Не забудьте перезапустить Nginx: `sudo systemctl restart nginx`*

## Шаг 2: Изменение файла .env
В файле `.env`, который вы загружаете через FileZilla, нужно добавить следующие строки:

```env
# Включаем режим Webhook (укажите ваш реальный домен с https)
WEBHOOK_BASE_URL=https://bot.myschool.ru

# (Опционально) Секретный ключ, чтобы никто, кроме Сферума, не мог присылать данные
MAX_WEBHOOK_SECRET=my_super_secret_code_123

# Настройки для Sferum API
MAX_TOKEN=твой_токен
# ... (и остальные настройки) ...
```

## Шаг 3: Перезапуск бота
После того как вы изменили `.env` и загрузили его на сервер через FileZilla, зайдите в консоль сервера и перезапустите бота:

```bash
docker-compose -f docker-compose.prod.yml up -d --build
```

**Готово!** При старте бот сам зарегистрирует ваш Webhook в Сферуме. 
В логах `docker logs sferumburo_bot_prod` вы должны увидеть сообщение: 
`[INIT] Registering webhook: https://bot.myschool.ru/webhook`
