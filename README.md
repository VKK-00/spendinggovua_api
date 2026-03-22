# spendinggovua_api

Веб-додаток і API для витягування звітів з `spending.gov.ua` по одному ЄДРПОУ або групі ЄДРПОУ, з фільтрацією по роках і типах звітів.

## Що вже є

- `GET /` з веб-інтерфейсом для користувача
- `GET /health`
- `GET /api/catalog/{edrpou}`
- `POST /api/reports/search`
- `POST /api/reports/export/zip`
- browser-backed доступ до `spending.gov.ua` через `Playwright`
- Docker-конфіг для деплою на сервер

## Важливе обмеження

`GitHub` підходить для зберігання коду, але не для запуску цього сервісу як додатка.

Причина проста:

- `GitHub Pages` вміє тільки статичні сайти
- тут потрібен бекенд `FastAPI`
- бекенд запускає `Playwright + Chromium`
- `spending.gov.ua` блокує прямі `requests/curl`, а також headless Chromium

Тому правильна схема така:

1. код зберігається на GitHub
2. сам додаток деплоїться на VPS або будь-який Docker-сумісний хостинг

## Локальний запуск

```powershell
uv venv
.venv\Scripts\activate
uv pip install -e .
python -m playwright install chromium
uvicorn app.main:app --reload
```

Після запуску:

- UI: `http://127.0.0.1:8000/`
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

## Веб-інтерфейс

Головна сторінка дає:

- поле для одного або кількох ЄДРПОУ
- завантаження підказок по роках і типах форм
- пошук по роках
- пошук по типах звітів
- опцію `include_details`
- скачування `zip` по поточних фільтрах
- таблицю результатів
- перегляд повного JSON для звіту

## Приклад API-запиту

```json
{
  "edrpous": ["02545815", "14360570"],
  "years": [2025, 2024],
  "report_types": ["Форма № 7", "Форма № 2"],
  "include_details": false
}
```

```powershell
curl -X POST "http://127.0.0.1:8000/api/reports/search" `
  -H "Content-Type: application/json" `
  -d "{\"edrpous\":[\"02545815\"],\"years\":[2025],\"report_types\":[\"Форма № 7\"]}"
```

## Docker

Збірка:

```powershell
docker build -t spendinggovua-api .
```

Запуск:

```powershell
docker run -p 8000:8000 spendinggovua-api
```

У контейнері сервіс стартує через `xvfb-run`, щоб Chromium працював у non-headless режимі.

## ZIP-експорт

`POST /api/reports/export/zip` повертає архів, де:

- є `manifest.json` у корені
- для кожного ЄДРПОУ створюється окрема папка
- якщо звіти знайдені, в папці буде `index.json` і окремі `json`-файли звітів
- якщо звітів немає, в папці буде `no_reports.json`

Приклад для `Форма № 2`:

```json
{
  "edrpous": ["26408431", "24983020"],
  "report_types": ["Форма № 2"],
  "include_details": true,
  "latest_only_per_edrpou": false
}
```

## Файли

- `app/main.py` - HTTP API і роздача UI
- `app/spending_client.py` - доступ до `spending.gov.ua`
- `app/zip_export.py` - збірка zip-архівів
- `app/static/index.html` - UI
- `app/static/app.css` - стилі
- `app/static/app.js` - логіка інтерфейсу
- `Dockerfile` - деплой через контейнер
