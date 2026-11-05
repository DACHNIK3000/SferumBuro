#!/bin/bash

# Переходим в директорию со скриптом (где лежит проект)
cd "$(dirname "$0")"

# GitHub Personal Access Token и репозиторий
GITHUB_TOKEN="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"
GITHUB_REPO="DACHNIK3000/SferumBuro"

# Прописываем remote с токеном (на случай если remote ещё не настроен)
git remote set-url origin "https://${GITHUB_TOKEN}@github.com/${GITHUB_REPO}.git"

# Получаем свежие данные с GitHub, не меняя локальные файлы
git fetch

# Сравниваем локальную ветку с удаленной
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse @{u})

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "Обнаружены новые изменения. Обновляем..."
    # Скачиваем изменения (принудительно сбрасываем локальные коммиты на версию с сервера)
    git reset --hard origin/master
    docker compose -f docker-compose.prod.yml up -d --build
    echo "Бот успешно обновлен и перезапущен!"
else
    echo "Изменений нет. Перезапуск не требуется."
fi
