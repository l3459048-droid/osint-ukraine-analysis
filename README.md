# OSINT Ukraine Analysis — local-first v0.9.12

Локальная система для обработки, поиска, чтения, перевода и вопросов по коллекции OSINT-документов. Основной сценарий полностью работает с папкой на ПК; Google Drive не нужен.

## Что делает v0.9.12

```text
папка документов
      ↓
PDF / DOCX / TXT / MD
      ↓
extract / OCR / SHA-256 / SQLite
      ↓
классификация + page-aware chunks
      ↓
lexical / semantic search
      ↓
┌─────────────────────────────────────┐
│ локальный Web UI                    │
│ Search · Ask · Chat · Reader        │
│ System · Translate · Settings       │
└─────────────────────────────────────┘
      ↓
автоматическое обслуживание библиотеки
новые/изменённые файлы → индекс → очередь переводов
```

Исходные документы никогда не изменяются и не удаляются.

## Быстрый запуск

```powershell
git clone https://github.com/l3459048-droid/osint-ukraine-analysis.git
cd osint-ukraine-analysis
git checkout local-ingestion-v1

python -m venv .venv
.venv\Scripts\activate
pip install -e .
osint-local serve
```

Web UI открывается на:

```text
http://127.0.0.1:8080
```

На Windows для обычной работы используй:

```text
START_OSINT.pyw
STOP_OSINT.pyw
```

Окна консоли при обычном запуске не нужны. VBScript больше не используется. Главный экран сам запускает обслуживание библиотеки через несколько секунд после старта.

## Reader: оригинал ↔ русский перевод

Поиск теперь ведёт не просто к документу, а прямо к найденной странице. Страница документа показывает две колонки:

```text
Original                      Русский
Page 12                       Page 12
──────────────────            ──────────────────
original text...              перевод...
```

Есть переходы Previous / Next и открытие исходного PDF на той же странице.

## Перевод

В рабочем сценарии разрешены только:

- English → Russian;
- Ukrainian → Russian.

Результат сохраняется отдельно:

```text
translations/
└── ru/
    └── report.<sha>.ru.md
```

Для PDF сохраняются границы страниц. Оригинал остаётся read-only.

Установка локального переводчика:

```powershell
pip install -e ".[translate]"
```

Ручной перевод:

```powershell
osint-local translate <SHA256> --from auto
```

При первом ручном переводе недостающие Argos-модели могут быть загружены. Для Ukrainian → Russian система может использовать маршрут через English, если прямой пакет отсутствует. После установки моделей перевод выполняется локально.

## Marian tokenizer contract fix v0.9.12

Fast Translation использует Hugging Face MarianMT weights, конвертированные через CTranslate2 TransformersConverter. Для таких моделей source sequence должна содержать специальный EOS token `</s>`, который обычный MarianTokenizer добавляет автоматически. Наш Unicode-safe raw SentencePiece путь ранее не добавлял его. v0.9.12 добавляет `</s>` к каждому source window и учитывает его в лимите входных токенов.

Это исправление направлено на реальную деградацию UK→RU, где начало страницы переводилось правдоподобно, а затем появлялись повторения и token-like fragments. Для проверки после обновления нужно заново перевести проблемный документ; старые сохранённые переводы автоматически не изменяются.

## Fast Translation quality guard v0.9.11

После реального UK→RU документа обнаружена деградация greedy decoding на сложных страницах: повторяющиеся слова/символы и слишком длинные хвосты. Fast Translation теперь использует beam size 2, repetition penalty, запрет повторяющихся 3-грамм и динамический лимит длины вывода, зависящий от реальной длины входного batch. Это намеренно отдаёт приоритет качеству над последними процентами throughput.

Старые уже сохранённые переводы автоматически не переписываются. Чтобы получить исправленный текст, нужный документ следует перевести повторно после обновления; DOCX затем экспортируется из нового результата.

## Translation DOCX export v0.9.10

Сохранённый русский перевод теперь можно экспортировать в **DOCX** прямо со страницы документа. Экспорт не запускает перевод повторно: он использует уже готовый Markdown, включая старые переводы. Для PDF сохраняются границы страниц — в DOCX между исходными страницами ставятся page breaks. В документ также записываются источник, SHA-256, языковая пара, время создания и использованный translation engine.

В карточке готового перевода доступны два действия: открыть Markdown и скачать **DOCX**. Файл сохраняется рядом с переводом как `.ru.docx` и может быть создан заново в любой момент.

## Fast Translation v0.9.9

### Manual translation priority

Manual **Translate** now runs independently from background library maintenance. Starting a user-requested translation no longer fails with `maintenance is already running`; the translation marks interactive work as active and maintenance yields at its existing safe checkpoints. Chat/Ask can still pause translation at Fast Translation batch boundaries.

### Manual translation engine selection

Manual **Translate** now always uses `auto` engine selection, so a stale local `engine: argos` preference cannot silently bypass a ready CTranslate2 model. Progress explicitly reports either **Using Fast Translation · CTranslate2 INT8** or **Using Argos fallback** before translation begins.

### Translation throughput

Fast Translation now batches text across several pages instead of translating each page in isolation. Economy uses 4-page windows and Balanced uses 8-page windows by default. Checkpoints are written once per completed page window instead of rewriting the full accumulated translation after every page. Progress reports both pages/min and chars/s so dense and sparse PDFs can be compared more accurately.

### Windows Unicode path fix

SentencePiece tokenizer files are now read by Python and loaded from memory instead of being opened by the native library using their filesystem path. This avoids `NOT_FOUND` errors when the project path contains non-ASCII folders such as `проекты`.

### Tokenizer self-repair

If a previous Fast Translation setup already produced the converted CTranslate2 weights but missed `source.spm` or `target.spm`, pressing **Prepare** now repairs only the missing tokenizer assets from the OPUS-MT model. The existing INT8 `model.bin` is kept and is not converted again.

### UTF-8 translation rendering

Translation Markdown files are stored in UTF-8 and are now served with an explicit `charset=utf-8`. Existing translation files do not need to be regenerated; reopening them in the updated web UI should display Cyrillic and punctuation correctly.

### Fast setup и maintenance

Подготовка Fast Translation модели теперь выполняется в отдельном фоне и больше не блокируется сообщением `maintenance is already running`. Во время подготовки текущий фоновый перевод уступает ресурсы на безопасной границе batch, а обычное обслуживание библиотеки остаётся отдельной задачей.

### Исправление зависимостей v0.9.2

Fast Translation использует совместимый стек `CTranslate2 >= 4.7` + `Transformers 5.x`, а semantic search остаётся на актуальной ветке `sentence-transformers 6.x`. Windows CI устанавливает полный набор `.[all]` и выполняет `pip check`, чтобы ловить такие конфликты до обновления пользователя.

Для массового English/Ukrainian → Russian перевода добавлен быстрый backend на CTranslate2. После одноразовой подготовки языковой пары схема выглядит так:

```text
document pages
      ↓
SentencePiece
      ↓
large token batches
      ↓
CTranslate2 INT8 / CPU
beam_size = 1
      ↓
Russian pages
```

Argos Translate сохранён как fallback. Когда Fast-модель подготовлена, режим `auto` предпочитает CTranslate2.

После обновления открой:

```text
System → Fast Translation
```

и нажми **Prepare** для нужной пары:

- English → Russian;
- Ukrainian → Russian.

Первый Prepare скачивает исходную OPUS-MT модель и один раз конвертирует её в локальный INT8-формат. После этого интернет для перевода не требуется.

После подготовки автоматически выполняется короткий benchmark. Он пробует несколько размеров batch и сохраняет лучший вариант для текущего CPU. В `System` показываются приблизительные:

```text
pages/min
100 pages ~ N min
```

Это оценка по текстовому объёму страницы, а не гарантированное время: реальная скорость зависит от CPU, объёма текста на странице и необходимости OCR.

Fast Translation сохраняет checkpoint после каждой завершённой страницы/секции. Если приложение остановить или перевод прервётся, следующий запуск продолжит работу без повторного перевода уже сохранённых частей.

Во время активного `Chat` или `Ask` фоновый перевод ставится на паузу на безопасной границе batch и автоматически продолжается после ответа.

## Автоматическое обслуживание библиотеки

Пока `osint-local serve` запущен, v0.9.1 сам поддерживает библиотеку в актуальном состоянии. Первый цикл начинается через несколько секунд после запуска, затем повторяется с интервалом выбранного performance-профиля:

1. быстро проверяет новые и изменённые файлы;
2. обрабатывает только то, что требует обновления;
3. дополняет semantic index, если Sentence Transformers установлен;
4. переводит English/Ukrainian документы на русский в соответствии с выбранным performance-профилем.

На главной странице кнопка **Process now** запускает такой же полный цикл вручную. Отдельно нажимать Scan и Build index для обычной работы больше не требуется.

Все тяжёлые операции сериализованы: обработка, индексирование и перевод не запускаются одновременно. Ошибочные документы автоматически пробуются снова в следующих циклах.

Пассивный перевод **не скачивает модели сам**. Сначала один раз установи нужную языковую пару ручным переводом, после чего очередь может идти полностью offline.


## Performance profiles

В `Settings` доступны два режима нагрузки:

- **Economy** — режим по умолчанию для слабых и обычных ПК: меньшие batch, более редкий фоновый цикл, до 1 перевода за цикл, Qwen выгружается из памяти после ответа;
- **Balanced** — быстрее обрабатывает библиотеку и следующие вопросы: до 2 переводов за цикл, больше контекста и Ollama остаётся загруженной до 5 минут.

Старые `config.json` без поля `performance` при переходе на v0.9.1 автоматически мигрируют в Economy.

## System Status

В верхнем меню появилась страница `System`. Она показывает:

```text
Documents
Index queue
Translation queue
Errors
Current activity
Semantic search
Ollama / installed models
Argos translation pairs
Tesseract / OCR
Automatic cycle
```

Так можно сразу понять, что система сейчас делает и чего ей не хватает, без чтения логов.

## Hybrid search и reranking

Режим `Auto` теперь использует гибридный поиск, когда semantic index готов:

```text
lexical search
      +
semantic search
      ↓
rank fusion
      ↓
лёгкий exact-match reranking
      ↓
лучшие chunks
```

Это не добавляет новую тяжёлую модель: объединение и reranking выполняются локально и дёшево по CPU. В `Search` также можно явно выбрать `Hybrid`, `Lexical` или `Semantic`.

## Вопросы по всей базе документов

В верхнем меню появился `Ask`. Это локальный RAG-сценарий:

```text
вопрос пользователя
      ↓
поиск релевантных chunks по всей базе
      ↓
локальный LLM
      ↓
ответ + ссылки [1], [2] на документы/страницы
```

Для генерации ответа используется локальный Ollama на `127.0.0.1:11434`. По умолчанию проект настроен на лёгкую модель `qwen3:1.7b`. Для снижения нагрузки reasoning выключен, контекст ограничен 4096 токенами, а модель выгружается из памяти сразу после ответа (`keep_alive: 0`).

Windows:

```powershell
irm https://ollama.com/install.ps1 | iex
ollama pull qwen3:1.7b
```

После установки Ollama и хотя бы одной локальной модели:

```powershell
osint-local ask "Что документы говорят об изменении применения FPV?"
```

или используй страницу `Ask` в Web UI.

В Ask доступны режимы:

- **Быстро** — короткий ответ с минимальной нагрузкой;
- **Глубокий анализ** — больше релевантных фрагментов и более подробный синтез;
- **Сравнить документы** — приоритет источникам из разных документов;
- **Найти противоречия** — ищет несовместимые утверждения и требует ссылки на обе стороны, не называя обычные различия противоречием.

Для глубоких режимов контекст ограничен так, чтобы оставаться практичным для текущей лёгкой модели `qwen3:1.7b` с `num_ctx=4096`.

Для больших архивов в `Ask → Filters` доступны фильтры, которые применяются **до retrieval**, а не после генерации:

- период: последние 7 / 30 / 90 / 365 дней;
- собственные даты From / To;
- категория;
- конкретная папка;
- один или несколько конкретных документов;
- язык оригинала: English / Ukrainian / Russian.

Несколько фильтров объединяются: например, можно задать «Drones + English + папка reports + последние 30 дней». Дата сейчас означает **время изменения исходного файла на диске**, а не дату события, автоматически извлечённую из содержания PDF.

Язык сохраняется в SQLite при обработке. Для старой базы v0.9 автоматически дозаполняет язык из уже извлечённого текста без повторного OCR.

Важно: система не генерирует бесконечные «периодические выводы». Она пассивно поддерживает индекс актуальным, а анализ выполняется в момент вопроса на основе релевантных фрагментов. Это снижает накопление вторичных ошибок и всегда позволяет показать источники.

## Обычный локальный Chat

В v0.9 появилась отдельная страница `Chat`. Она использует тот же локальный Ollama/Qwen, но принципиально не делает retrieval по документам:

```text
Chat
  ↓
локальная история диалога
  ↓
Ollama / Qwen
  ↓
обычный ответ без document sources
```

Это подходит для обычного общения, объяснений, черновиков, простого кода и других задач, которые не требуют библиотеки. В этом режиме модель не получает документы и не имеет доступа к интернету.

История Chat хранится только в памяти текущего запущенного сервера и очищается кнопкой **Clear conversation** или при перезапуске приложения. Economy держит меньший объём истории, Balanced — больший.

## Опциональные зависимости

OCR:

```powershell
pip install -e ".[ocr]"
```

Semantic search:

```powershell
pip install -e ".[search]"
```

Offline translation:

```powershell
pip install -e ".[translate]"
```

Fast Translation:

```powershell
pip install -e ".[fasttranslate]"
```

Всё сразу:

```powershell
pip install -e ".[all]"
```

## Основные команды

```powershell
osint-local serve
osint-local scan
osint-local index
osint-local search "FPV logistics" --mode hybrid
osint-local ask "Что известно о логистике FPV?" --mode quick
osint-local ask "Сравни документы по применению FPV" --mode compare
osint-local translate <SHA256> --from auto
osint-local status
osint-local doctor
```

## Безопасность локального режима

Web UI по умолчанию слушает только `127.0.0.1`. Q&A также ограничен локальным Ollama endpoint (`localhost` / `127.0.0.1` / `::1`). Исходные файлы читаются из выбранной папки, а производные данные хранятся отдельно.

Подробности pipeline: [`README_LOCAL.md`](README_LOCAL.md).


## Обновление без Git

Для ZIP-установок используй:

```text
UPDATE_OSINT.cmd
```

Он запускает `update_local.ps1`, останавливает локальный сервер, загружает свежую ветку и заменяет только файлы приложения. `config.json`, `workspace`, документы и `.venv` сохраняются. Старые VBS-launchers автоматически удаляются.
