# OSINT Ukraine Analysis — local-first v0.2

Локальная система для обработки и поиска по коллекции OSINT-документов. Google Drive для основного workflow не нужен: документы могут лежать в любой папке на ПК.

```text
локальная папка
      ↓
PDF / DOCX / TXT / MD
      ↓
извлечение текста + OCR
      ↓
SHA-256 / SQLite / классификация
      ↓
page-aware search chunks
      ↓
lexical или multilingual semantic search
      ↓
файл + страница + релевантный фрагмент
```

## Windows: быстрый запуск

```powershell
git clone https://github.com/l3459048-droid/osint-ukraine-analysis.git
cd osint-ukraine-analysis
git checkout local-ingestion-v1

python -m venv .venv
.venv\Scripts\activate
pip install -e ".[all]"

osint-local init
```

В `config.json` укажите папки:

```json
{
  "input_dir": "D:/OSINT/Documents",
  "workspace_dir": "D:/OSINT/AnalysisData"
}
```

После этого:

```powershell
osint-local scan
osint-local search "FPV logistics" --mode lexical
osint-local index
osint-local search "изменение тактики применения FPV"
```

`search` возвращает исходный файл, страницу PDF (если применимо) и фрагмент текста. v0.2 использует уже извлечённый v0.1 текст, поэтому старую коллекцию не нужно обрабатывать заново.

Для постоянного наблюдения за исходной папкой:

```powershell
osint-local watch
```

После появления новых документов обычный поиск сам обновит чанки; для обновления semantic embeddings достаточно снова выполнить `osint-local index`.

Подробности: [`README_LOCAL.md`](README_LOCAL.md).

Старые Google Drive-скрипты пока сохранены как legacy и не нужны локальному runtime.
