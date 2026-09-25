# OSINT Ukraine Analysis — local-first v0.9.19

Локальная система для обработки, поиска, чтения, перевода и вопросов по коллекции OSINT-документов. Основной сценарий полностью работает с папкой на ПК; Google Drive не нужен.

## Что делает v0.9.19

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

## Adaptive Corpus Taxonomy v0.9.19

Для больших библиотек добавлен отдельный analytical layer **Corpus**. Он не запускает повторный OCR, PDF extraction или перевод: taxonomy строится поверх уже готового semantic index.

После semantic indexing система агрегирует chunk embeddings в document-level vectors, обнаруживает устойчивые semantic clusters и создаёт два уровня:

- **Categories** — более широкие области корпуса;
- **Topics** — более конкретные обнаруженные темы.

Названия и короткие описания новых кластеров генерируются локальным Qwen через Ollama, если он доступен. Если Ollama недоступен или не вернул валидный JSON, система автоматически использует детерминированные keyword labels, поэтому rebuild не зависит от LLM.

Документ может принадлежать сразу нескольким topics/categories. После открытия тем кластеризация используется только для discovery, затем выполняется multi-label assignment по cosine similarity. Порог и максимальное количество тем на документ настраиваются через `taxonomy.topic_assignment_similarity` и `taxonomy.max_topics_per_document`.

На странице **Corpus** показываются adaptive categories, discovered topics, coverage и документы выбранной темы с semantic match score. На странице каждого документа появился блок **Adaptive taxonomy**, а Ask получил фильтры **Adaptive category** и **Topic**.

Taxonomy автоматически перестраивается после обновления semantic index, только если corpus fingerprint изменился. Добавление/изменение документов с тем же количеством chunks тоже обнаруживается через embedding signature. Существующие названия сохраняются для семантически близких кластеров, чтобы категории не переименовывались при каждом небольшом изменении корпуса; Qwen именует только реально новые clusters.

Старые rule-based classifications не удалены и остаются совместимым fallback-слоем. До первого adaptive rebuild главная страница показывает их; после построения taxonomy главная страница предпочитает новые adaptive categories.

Ручной rebuild доступен через **Corpus → Rebuild taxonomy** или CLI:

```powershell
osint-local taxonomy
```

Все новые taxonomy tables живут отдельно от ingestion tables. Новый rebuild записывается транзакционно: если clustering/naming завершились ошибкой, предыдущая рабочая taxonomy остаётся доступной.

## Layout-preserving translated PDF v0.9.18

Quality-перевод PDF теперь использует persistent layout artifact как источник translation units: M2M100 переводит стабильные PDF-блоки с их `block id` и `bbox`, а Markdown/Reader собирается из тех же результатов. Рядом с Markdown сохраняется `*.layout.json`, содержащий source/translated text каждого блока и исходную геометрию.

На странице документа для PDF появился экспорт **PDF · layout**. Renderer открывает исходный PDF, удаляет только исходный text layer внутри переведённых bbox через transparent redactions, при этом не удаляет изображения и vector graphics, и затем вписывает русский текст обратно в исходные области. Размер страницы, линии формы и исходная геометрия сохраняются. Шрифт автоматически уменьшается, если русский текст длиннее исходного; статистика shrink/overflow сохраняется рядом с PDF в `*.layout.pdf.json`.

Layout PDF не строится из Markdown. Для старого перевода без block map нужно заново выполнить Quality-перевод PDF, после чего экспорт станет доступен.

## Quality Translation + protected facts + persistent PDF layout v0.9.17

В дополнение к Fast OPUS появился локальный **Quality Translation** engine на базе `facebook/m2m100_418M`, конвертируемый в CTranslate2 INT8. В System есть отдельная подготовка модели. В режиме Auto OPUS остаётся быстрым основным путём; M2M100 загружается лениво только для фрагментов, которые не прошли quality gate. Для важных документов в ручном Translate есть отдельный режим Quality, который переводит весь документ через M2M100; если Quality-модель подготовлена, он выбран по умолчанию. Если Fast Translation вообще недоступен, уже подготовленный Quality engine может использоваться как основной локальный переводчик.

Для M2M100 используется его нативный multilingual contract: source language prefix (`__uk__` / `__en__`) во входе и target prefix `__ru__` при decoding, beam size 5. После подготовки выполняется небольшой benchmark на реальных UK→RU фрагментах проблемного образовательного PDF и сохраняется сравнение OPUS vs M2M100 по скорости, quality heuristics и reference similarity.

### Protected literals

Критические факты теперь защищаются до передачи модели. В protected set входят даты, числа, URL, длинные SHA-like идентификаторы и нейтральные коды вроде `J3`, `FQ`, `EHEA`, `QF-LLL`, `ECTS/ЕКТС`. Украинские сокращения, которые должны меняться при переводе (например `ЄКТС` → `ЕКТС`), намеренно не замораживаются. Сначала они заменяются collision-resistant placeholders и после перевода восстанавливаются точно. Если модель повредила placeholder, pipeline автоматически переключается на segment-around-literals fallback: переводятся только текстовые промежутки, а исходные literals вставляются обратно без изменений.

Quality gate рассматривает потерю protected literal как hard failure, а не как небольшой soft penalty. Это закрывает класс ошибок, где `01.09.2026` исчезала из перевода.

### Hybrid engine provenance

Для подозрительного сегмента Auto может сравнить Fast retry, M2M100 и уже установленный Argos. Сохраняются счётчики candidate/selected для Quality и Argos, protected-literal fallbacks и тип hybrid engine. Если M2M100 реально заменил часть OPUS-результата, translation record больше не выглядит как чистый `ctranslate2-int8`.

### Persistent PDF layout artifact

PDF extraction теперь сохраняет отдельный geometry artifact:

`workspace/layout/<sha256>.json`

Для каждой страницы сохраняются width/height/rotation, стабильные block/line/span IDs, bbox, text, font, size, flags, color, origin и line direction. Этот artifact не заменяет semantic extracted text — он является отдельным слоем для следующего layout-preserving PDF renderer. Pipeline version повышена до 5, поэтому старые PDF один раз переизвлекаются и получают layout artifact; TXT/DOCX из-за этого не переобрабатываются.

Fast Translation checkpoint pipeline повышен до version 6, чтобы старые незавершённые результаты не смешивались с protected-literal логикой.

## Layout-aware PDF + Translation Quality Gate v0.9.16

Этот релиз объединяет следующий этап качества в один pipeline. PDF теперь дополнительно извлекается через позиционные line/span данные PyMuPDF: строки группируются по вертикальному положению, а соседние поля одной строки восстанавливаются слева направо. Layout-вариант используется только если по объёму и quality score он согласуется с обычным native text; OCR остаётся третьим кандидатом и побеждает только при реальном улучшении.

Fast Translation теперь проверяет каждый смысловой фрагмент после генерации: runaway/repetition, подозрительное соотношение длины, потерянные числа и даты, потерянные Latin codes вроде J3 / FQ / EHEA, mixed-script слова и слишком низкую долю кириллицы для русского результата. Подозрительный фрагмент сначала автоматически повторяется меньшими окнами и более строгим decoding. Если результат всё ещё плохой, режим Auto может сравнить его с уже установленным Argos и выбрать fallback только когда его quality score лучше. Автоматическая установка Argos для этого fallback по умолчанию выключена.

Строки PDF-форм больше не склеиваются обратно в одну длинную страницу перед quality gate: номера протоколов, подписи, URL, numbered fields и короткие form rows остаются отдельными translation units, а обычные переносы связного абзаца снова собираются вместе.

Extraction pipeline повышена до version 4, Fast Translation checkpoint pipeline — до version 5. Старые extraction/checkpoint результаты не смешиваются с новым алгоритмом.

## PDF extraction quality layer v0.9.15

PDF extraction больше не решает вопрос OCR только по количеству символов. Native PyMuPDF text извлекается с восстановлением reading order (`sort=True`) и получает quality score по читаемости, replacement/control characters, повторяющемуся шуму и общему составу текста. OCR запускается для коротких или подозрительных страниц и заменяет native text только когда его quality score лучше с безопасным запасом.

При извлечении также удаляются невидимые Unicode artifacts (NBSP, zero-width characters, soft hyphen), но содержательные символы, подчёркивания и исходный текст не уничтожаются. В metadata каждой PDF-страницы сохраняются native/OCR/selected quality scores и факт OCR probe.

Pipeline version повышена до 3, поэтому после обновления неизменённые ранее обработанные документы будут один раз автоматически переизвлечены при Scan. Fast Translation checkpoints теперь также имеют собственную pipeline version, чтобы незавершённый перевод со старым алгоритмом не мог пережить обновление и смешаться с новым результатом.

## Structured PDF translation quality v0.9.14

Fast Translation теперь ближе следует native Marian generation profile: обычный перевод использует beam size 6, как в официальном generation config модели OPUS-MT uk→ru. Агрессивные repetition/no-repeat ограничения больше не применяются к каждому нормальному фрагменту; они остаются только для quality retry подозрительного вывода.

PDF-формы обрабатываются отдельно: короткие строки, номера протоколов, URL и строки с подчёркиваниями переводятся как самостоятельные поля, длинные технические заполнители удаляются до токенизации, а URL после перевода восстанавливаются из оригинала без изменений. Default semantic segment снижен со 160 до 120 source tokens в пользу качества.

## Translation quality pipeline v0.9.13

Fast Translation теперь не режет длинный PDF-текст только по жёсткому token limit. Сначала восстанавливаются смысловые границы по большим пробелам из PDF-форм, пунктуации и нумерованным пунктам, затем соседние фрагменты собираются в умеренные сегменты до 160 source tokens. Это уменьшает разрывы предложений и смешивание соседних полей/колонок.

После перевода выполняется лёгкая проверка на runaway output: чрезмерную длину, длинные повторы символов/слов и утечку token-like fragments вида `url_` / `name_`. Подозрительный фрагмент автоматически переводится ещё раз меньшими сегментами и с beam size 4; повторный вариант принимается только если его anomaly score ниже. Обычные фрагменты не платят эту дополнительную стоимость.

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
