# spendinggovua_api

Веб-додаток і API для витягування звітів з `spending.gov.ua` по одному ЄДРПОУ або групі ЄДРПОУ.

Сервіс працює через `Playwright + Chromium`, тому не залежить від прямих `requests/curl`, які портал часто блокує або повертає з помилками.

## Що вміє

- пошук звітів по одному або багатьох ЄДРПОУ
- фільтрація по роках, діапазону дат і типах форм
- зведення доступних типів звітів по групі ЄДРПОУ
- витягування сирого JSON звіту
- HTML-подання конкретного звіту з табличкою як на порталі
- PDF конкретного звіту
- ZIP-архіви по групі ЄДРПОУ

## API

- `GET /`
- `GET /health`
- `GET /api/catalog/{edrpou}`
- `POST /api/reports/search`
- `POST /api/report-types/summary`
- `GET /api/reports/{edrpou}/{report_id}/html`
- `GET /api/reports/{edrpou}/{report_id}/pdf`
- `POST /api/reports/export/zip`

## Важливе обмеження

Це не статичний сайт. `GitHub Pages` для нього не підходить.

Причина:

- потрібен живий `FastAPI` бекенд
- потрібен браузерний `Playwright`
- `spending.gov.ua` часто блокує headless або прямі HTTP-запити

Нормальна схема:

1. код зберігається на GitHub
2. застосунок запускається на VPS, Render, Railway, Fly.io або іншому сервері з Docker / Python

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
- Swagger: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

## Запуск як пакет

Після встановлення в editable або звичайному режимі доступні CLI-команди:

```powershell
spendinggovua-api
spendinggovua-form2-export
```

Перша запускає API, друга збирає загальний HTML ZIP по `Форма № 2` для заданого в коді списку ЄДРПОУ.

## Збірка пакета

Проєкт вже можна збирати як Python-пакет:

```powershell
uv build
```

Після цього артефакти з'являться в `dist/`.

## Приклади

Пошук звітів:

```json
{
  "edrpous": ["43861328", "02125473"],
  "report_types": ["Форма № 2"],
  "date_from": "2021-01-01",
  "date_to": "2025-12-31",
  "include_details": false
}
```

Зведення доступних форм по групі:

```json
{
  "edrpous": ["43861328", "02125473", "02071033"]
}
```

HTML / PDF одного звіту:

```text
/api/reports/43861328/1701610529/html
/api/reports/43861328/1701610529/pdf
```

## ZIP-експорт

`POST /api/reports/export/zip` повертає архів такого типу:

- `manifest.json` у корені
- окрема папка на кожний ЄДРПОУ
- `index.json` і файли звітів, якщо звіти знайдено
- `no_reports.json`, якщо по ЄДРПОУ немає даних
- `error.json`, якщо сам портал повернув помилку

Приклад:

```json
{
  "edrpous": ["43861328", "02125473"],
  "report_types": ["Форма № 2"],
  "include_details": true,
  "latest_only_per_edrpou": false
}
```

## HTML і PDF звітів

Для конкретного `reportId` сервіс може побудувати читабельне подання звіту:

- `HTML` з шапкою і таблицею
- `PDF`, згенерований Chromium з цього HTML

Це корисно, коли треба не сирий JSON, а документ у вигляді, близькому до сторінки порталу.

## Масова підготовка форми 2

Для масового архіву по `Форма № 2` використовуйте скрипт:

```powershell
.venv\Scripts\python scripts\export_form2_html_zip.py
```

Скрипт збирає:

- всі доступні звіти форми 2 по заданому списку ЄДРПОУ
- HTML-файли з табличним поданням
- один загальний ZIP-архів

Результати зберігаються в `output/`.

## Файли

- `app/main.py` - HTTP API
- `app/spending_client.py` - робота з порталом через Playwright
- `app/report_render.py` - HTML-рендер звіту
- `app/zip_export.py` - збірка ZIP-архівів
- `app/static/index.html` - UI
- `app/static/app.js` - логіка UI
- `app/static/app.css` - стилі UI
- `Dockerfile` - контейнерний запуск
