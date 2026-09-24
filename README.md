# OSINT Ukraine Analysis — local-first v0.5

Локальная система для обработки, индексации и поиска по коллекции OSINT-документов. Google Drive для основного рабочего сценария не нужен: документы могут находиться в любой папке на ПК, а Web UI открывается локально в браузере.

## Что уже работает

```text
локальная папка
      ↓
PDF / DOCX / TXT / MD
      ↓
извлечение текста + опциональный OCR
      ↓
SHA-256 / дедупликация / SQLite
      ↓
тематическая классификация
      ↓
page-aware chunks
      ↓
lexical search / multilingual semantic search
      ↓
локальный Web UI на http://127.0.0.1:8080
      ↓
опциональный локальный перевод → соседняя папка translations/
```

Web UI показывает dashboard, категории, документы, результаты поиска, найденные фрагменты и ссылки на исходный локальный файл. Для PDF ссылка на результат ведёт к соответствующей странице (`#page=N`). Исходные документы не изменяются и не удаляются.

## Быстрый запуск на Windows

```powershell
git clone https://github.com/l3459048-droid/osint-ukraine-analysis.git
cd osint-ukraine-analysis
git checkout local-ingestion-v1

python -m venv .venv
.venv\Scripts\activate
pip install -e .

osint-local serve
```

На **первом запуске** `serve` сам создаст `config.json` и предложит выбрать папку с документами прямо в Web UI. Отдельный `osint-local init` больше не обязателен для обычного desktop-сценария.

После первой установки можно запускать интерфейс двойным кликом по `start_local.bat`.

## Минималистичный desktop-like UX

v0.5 сохраняет минималистичный подход: только основные действия постоянно на виду:

- `Scan` — обработать новые и изменённые документы;
- `Build index` / `Update index` — построить или обновить semantic index;
- `Folder` — открыть папку документов в проводнике;
- `Settings` — сменить папку документов и посмотреть служебные пути.

Semantic status явно показывает одно из состояний: `Index not built`, `Index update needed`, `Index current`, `Semantic unavailable`.

Выбор папки использует локальный системный диалог, когда он доступен. Если GUI-диалог недоступен (например, на минимальной Linux-системе без tkinter), путь всегда можно вставить вручную в Settings.

## Локальный перевод

На странице каждого документа есть компактная строка `From → To → Translate`. Оригинал не изменяется. Результат сохраняется как Markdown в отдельной папке `translations/<язык>/`, которая по умолчанию создаётся рядом с выбранной папкой документов. Для PDF сохраняются заголовки страниц, чтобы перевод оставался связан с оригиналом.

Установка движка:

```powershell
pip install -e ".[translate]"
```

По умолчанию используется Argos Translate. Нужная языковая модель может быть загружена при первом переводе, после чего перевод работает локально. Поддерживаемые в UI языки первой версии: English, Russian, Ukrainian.

Из CLI:

```powershell
osint-local translate <SHA256> --from auto --to ru
```

## OCR и semantic search

Базовый Web UI и lexical search не требуют тяжёлых ML-зависимостей.

Для OCR:

```powershell
pip install -e ".[ocr]"
```

Для смыслового поиска:

```powershell
pip install -e ".[search]"
```

Или установить всё сразу:

```powershell
pip install -e ".[all]"
```

`osint-local index` и кнопка Web UI строят multilingual embeddings. При первом использовании Sentence Transformers может скачать модель; после кеширования она работает локально. В `search.model` можно указать путь к заранее скачанной модели для полностью offline-режима.

Режим поиска `auto` использует semantic search только когда embeddings существуют для всей текущей коллекции чанков. Если индекс неполный, система безопасно откатывается на lexical search, чтобы новые документы не исчезали из результатов.

## Основные команды

```powershell
osint-local serve                # основной desktop-like запуск
osint-local init                 # ручное создание config.json (опционально)
osint-local doctor               # диагностика
osint-local scan                 # обработать локальные документы
osint-local watch                # следить за новыми/изменёнными файлами
osint-local index                # построить semantic embeddings
osint-local search "FPV drones" # поиск из CLI
osint-local translate <SHA256> --to ru # локальный перевод
osint-local status               # статистика базы
```

По умолчанию Web UI слушает только `127.0.0.1` и недоступен другим устройствам в сети. Привязка к внешнему интерфейсу требует явного `--allow-network`.

## API

Пока Web UI работает, доступны локальные read-only endpoints:

```text
GET /api/stats
GET /api/search?q=fpv&mode=lexical&limit=10
GET /api/activity
```

## Обновление с предыдущих версий

SQLite-база мигрируется автоматически. Старые документы v0.1 без чанков автоматически переобрабатываются при `scan`. v0.5 не требует уничтожать существующую базу или повторно OCR-ить документы только из-за обновления интерфейса.

Подробности локального pipeline: [`README_LOCAL.md`](README_LOCAL.md).

Старые Google Drive-скрипты пока сохранены как legacy-код и не являются основным runtime.
