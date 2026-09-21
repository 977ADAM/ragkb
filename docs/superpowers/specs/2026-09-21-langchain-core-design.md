# Ядро на LangChain

## Требование

Владелец решил перевести ядро ragkb на LangChain: загрузка и нарезка
документов, эмбеддинги, векторное хранилище, гибридный поиск и генерация
ответа. Старое ядро не сохраняется — это замена, а не второй путь рядом.

Публичный контракт при этом не меняется: браузер по-прежнему получает
NDJSON `token` → `done` с `sources`, `/health`, `/api/v1/status`,
`/api/v1/bootstrap` и страница документов сохраняют свои поля. Фронтенд и BFF
не тронуты.

## Что на что заменено

| Было | Стало |
|---|---|
| свои разборщики в `core/loaders.py` → `Document`/`Block` | те же разборщики отдают `langchain_core.documents.Document` (`core/documents.py`) |
| `core/chunking.py`: свой чанкер с breadcrumb и склейкой мелочи | `RecursiveCharacterTextSplitter` из `langchain-text-splitters`, breadcrumb дописывается после нарезки |
| `core/embeddings.py`: свой HTTP-клиент Ollama | `langchain_ollama.OllamaEmbeddings`, `DeterministicFakeEmbedding` для тестов |
| `core/store.py`: `NumpyStore` + `ChromaStore` со своим манифестом | `langchain_chroma.Chroma` и `InMemoryVectorStore` (`core/vectorstore.py`); манифест остался своим — на нём стоят `/health`, `/status` и страница документов |
| `core/retrieval.py`: свои BM25, RRF, MMR, реранк | `EnsembleRetriever` (RRF) и MMR из `langchain-chroma`; лексическая половина — свой `LexicalRetriever` на `rank-bm25` |
| `core/llm.py`: свои клиенты OpenAI/Ollama/extractive | `langchain_openai.ChatOpenAI` (генерация — OpenAI-совместимый HTTP) |
| `core/pipeline.py`: `RAGPipeline` со своими склейками промпта | `RagChain` на LCEL: `prompt \| ChatOpenAI \| StrOutputParser` со `stream` |

Слои и порты сохранились: `core/ports.py` описывает `AnswerEngine` и
`IndexEngine`, прикладной слой (`api/`, `services/`) LangChain не видит.
`backend/tests/test_architecture.py` это проверяет отдельным тестом.

## Решения и почему

- **Зависимости.** `langchain-core`, `langchain-classic`,
  `langchain-text-splitters`, `langchain-ollama`, `langchain-chroma`,
  `langchain-openai`, `rank-bm25`. Без `langchain-community` (объявлен
  устаревшим и тянет `langsmith` дополнительно) и без метапакета `langchain`
  (в 1.4 это агенты и LangGraph, ретриверов и цепочек в нём нет).
  `langsmith` всё равно приходит транзитивно с `langchain-core` — трассировка
  выключена по умолчанию и никуда не отправляется, но зависимость в образе есть.
- **BM25 свой.** `langchain_classic.retrievers.BM25Retriever` — шим на
  устаревший community. Вместо него `LexicalRetriever(BaseRetriever)` на
  `rank_bm25` с русской токенизацией из `core.text` — это точка расширения
  LangChain, а не самодельный поиск мимо фреймворка.
- **Слияние — RRF из LangChain.** `EnsembleRetriever` с весами
  `retrieval.bm25_weight`/`dense_weight` и `c = retrieval.rrf_k`.
- **Разбор форматов свой.** Загрузчики LangChain для docx/pdf требуют
  `docx2txt` и `unstructured`, тянут community и теряют структуру таблиц и
  страниц; наши разборщики уже работают с pypdf/python-docx/bs4 и отдают
  блоки со страницами и заголовками. Они лишь превращают результат в
  `Document`.
- **Реранкер только HTTP.** Локальный cross-encoder требует torch, которого
  в образе нет. `HttpReranker` — `BaseDocumentCompressor`, который ходит в
  Jina/Cohere-совместимый `/rerank`.
- **Порог `min_score`** считается по близости плотного поиска: у LangChain
  порядок задаёт RRF, а близость берётся из `similarity_search_with_relevance_scores`
  (у `InMemoryVectorStore` такого метода нет — считаем косинус по векторам).

## Что исчезло

- Экстрактивный ответ: генерация обязательна. Если адрес модели не задан,
  `POST /api/v1/ask` отвечает 503 **до** открытия потока, а не отдаёт текст
  из найденных фрагментов. Сбой модели посреди потока по-прежнему даёт
  `truncated` и предупреждение.
- Два хранилища (`numpy` и `chroma`) свелись к `chroma` и `memory` (память —
  для тестов).
- Дедупликация чанков по тексту: RRF в LangChain схлопывает находки по
  `chunk_id`, а одинаковый абзац из двух файлов снова может занять две позиции.
- Инкрементальное обновление (`update_documents`) и `fallback_text` из порта.
- Настройки `chunking.min_size`, `chunking.respect_structure`,
  `retrieval.dedupe_text`, `embedding.tfidf_dim`, `store.upsert_batch`.

## Проверка результата

- `pytest` — 164 теста, все зелёные; `ruff` и `mypy` не добавили замечаний
  (4 и 2 находки — прежние, в файлах вне этой правки).
- Сквозной прогон на живом Ollama (`qwen3-embedding:0.6b`) и реальном
  документе (FAQ, 146 чанков): пересборка 7.1 с, ответ потоком 8.1 с,
  источники с путём раздела, `warnings: []`. То же — через BFF SvelteKit
  (`/api/index/rebuild`, `/api/ask`, `/api/admin/documents`).
- Сравнение качества на одном наборе (27 вопросов, собранных из заголовков и
  числовых фраз FAQ; набор синтетический и небольшой): старое ядро Hit@5
  81.5%, MRR 0.651; новое — Hit@5 85.2%, MRR 0.725. Разница в один вопрос
  попадает в шум приближённого поиска Chroma, поэтому вывод осторожный:
  регрессии не видно, выигрыша тоже.
- Ablation на новом ядре (Hit@1 / Hit@3 / Hit@5 / MRR): только BM25
  48.1 / 81.5 / 88.9 / 0.659; только векторы 51.9 / 63.0 / 70.4 / 0.586;
  гибрид 59.3 / 77.8 / 88.9 / 0.703; гибрид + MMR 59.3 / 77.8 / 81.5 / 0.688.
  Гибрид выигрывает по MRR, MMR на этом корпусе слегка снижает Hit@5 —
  выключается через `retrieval.use_mmr`.

## Ограничения

- Номер источника (`[N]`) берётся из текста ответа: если модель не ставит
  ссылки, `sources` пуст, а в `warnings` приходит предупреждение.
- `EnsembleRetriever` не отдаёт оценки ног: `matched_by` собирается по
  метаданным находок (`dense`, `lexical`, `rerank`), а не по вкладу в RRF.
- Chroma в режиме HNSW — приближённый поиск: на одном и том же вопросе
  выдача может отличаться на позицию.
