# OSINT Ukraine Analysis — local-first v0.3

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
```

Web UI показывает dashboard, категории, документы, результаты поиска, найденные фрагменты и ссылки на исходный локальный файл. Для PDF ссылка на результат ведёт к соответствующей странице (`#page=N`).

Исходные документы не изменяются и не удаляются.

## Быстрый запуск на Windows

```powershell
git clone https://github.com/l3459048-droid/osint-ukraine-analysis.git
cd osint-ukraine-analysis
git checkout local-ingestion-v1

python -m venv .venv
.venv\Scripts\activate
pip install -e .

osint-local init
```

Отредактируйте `config.json`, например:

```json
{
  "input_dir": "D:/OSINT/Documents",
  "workspace_dir": "D:/OSINT/AnalysisData"
}
```

Затем:

```powershell
osint-local scan
osint-local serve
```

Браузер откроет:

```text
http://127.0.0.1:8080
```

После первой установки можно запускать интерфейс двойным кликом по `start_local.bat`.

## OCR и semantic search

Базовый Web UI и lexical search не требуют тяжёлых ML-зависимостей.

Для OCR:

```powershell
pip install -e ".[ocr]"
```

Для смыслового поиска:

```powershell
pip install -e ".[search]"
osint-local index
```

Или установить всё сразу:

```powershell
pip install -e ".[all]"
```

`osint-local index` строит multilingual embeddings. При первом использовании Sentence Transformers может скачать модель; после кеширования она работает локально. В `search.model` можно указать путь к заранее скачанной модели для полностью offline-режима.

Режим поиска `auto` использует semantic search только когда embeddings существуют для всей текущей коллекции чанков. Если индекс неполный, система безопасно откатывается на lexical search, чтобы новые документы не исчезали из результатов.

## Основные команды

```powershell
osint-local init                 # создать config.json и рабочие папки
osint-local doctor               # диагностика
osint-local scan                 # обработать локальные документы
osint-local watch                # следить за новыми/изменёнными файлами
osint-local index                # построить semantic embeddings
osint-local search "FPV drones" # поиск из CLI
osint-local serve                # запустить Web UI
osint-local status               # статистика базы
```

По умолчанию Web UI слушает только `127.0.0.1` и недоступен другим устройствам в сети. Привязка к внешнему интерфейсу требует явного `--allow-network`.

## API для будущей автоматизации

Пока Web UI работает, доступны локальные read-only endpoints:

```text
GET /api/stats
GET /api/search?q=fpv&mode=lexical&limit=10
```

## Обновление с v0.1/v0.2

SQLite-база мигрируется автоматически. v0.3 не требует заново извлекать текст только ради Web UI. Старые документы v0.1 без чанков автоматически переобрабатываются при `scan`, как и в v0.2.

## Документация

Подробности локального pipeline: [`README_LOCAL.md`](README_LOCAL.md).

Старые Google Drive-скрипты пока сохранены как legacy-код и не являются основным runtime v0.3.
