# Оценки ответов (feedback)

| | |
|---|---|
| Дата | 2026-09-02 |
| Версия | 1 |
| Статус | готово |
| Автор | deepseek-harness |

## Зачем

ragkb отвечает с обязательными ссылками на источники, но не знает, полезен ли
ответ. Без обратной связи нельзя понять, где RAG-пайплайн ошибается. Оценка —
простое состояние на ответ: 👍 / 👎 и необязательный комментарий. Админу —
сводка оценок без аналитики и графиков.

## Границы

**В работе:** идентификатор сообщения (`Message.id`, из `messages.id`);
таблица `message_feedback` (одна оценка на сообщение, повтор меняет её);
ручка оценки от владельца диалога; админ-сводка; кнопки 👍/👎 в UI у ответа;
страница `/admin/feedback`; тесты; правки README/AGENTS при необходимости.

**Вне работы:** аналитика, графики, leaderboard, ELO, оценка «полезности
источника» по отдельности; агрегация по моделям; экспорт оценок; право
пользователя видеть чужие оценки; оценка при выключенной истории
(`history.enabled = false` — диалог не хранится, ручка вернёт 404).

## Ключевое решение: адрес сообщения

Сегодня `Message` не имеет публичного id: `GET .../chat_conversations/{cid}`
отдаёт список без идентификаторов, и оценить конкретный ответ нельзя.

- `MessageRow.id` (BigInt, автоинкремент) уже существует в Postgres.
- `Message` получает поле `id: int | None = None`; `to_dict()` включает `id`
  только когда он известен. Для эфемерной истории id пуст.
- Событие `done` потока начинает нести `message_id` сохранённого ответа —
  кнопка оценки доступна сразу после генерации.

## Контракт

### Оценка (владелец диалога)

`PATCH /organization/{org}/chat_conversations/{cid}/messages/{message_id}/feedback`

Тело:

```json
{ "rating": "up", "comment": "" }
```

- `rating`: `"up" | "down"`. Повторный запрос на то же сообщение меняет оценку.
- `comment`: строка, необязательна, до 500 символов; пустая строка = нет.
- Ошибки: 401 без сессии; 404, если диалог не принадлежит пользователю или
  сообщение не в этом диалоге (не раскрываем существование чужих данных);
  400 на неверный `rating` или длинный комментарий.
- Успех: `204` (без тела).

### Сводка для админа

`GET /admin/feedback`

```json
{
  "counts": { "up": 12, "down": 3 },
  "items": [
    {
      "username": "ada",
      "conversation_id": "…",
      "rating": "down",
      "comment": "ответил не по делу",
      "answer": "Для сдачи отчёта…",
      "created_at": "…"
    }
  ]
}
```

- Владелец: роль `admin` (тот же `require_admin`, что у `/admin/users`).
- `answer` — текст оценённого ответа, бэкенд обрезает до 200 символов;
  полный диалог админ открывает по `conversation_id` в обычном чате.
  Порядок: свежие сверху. `items` — до 200.

## Хранение

Таблица `message_feedback` (Alembic `0007_message_feedback`):

| колонка | тип | примечание |
|---|---|---|
| `id` | BigInteger PK | автоинкремент |
| `message_id` | BigInteger, FK `messages.id` ON DELETE CASCADE, unique | оцениваемый ответ |
| `rating` | Text | `up` / `down` |
| `comment` | Text | `""` по умолчанию |
| `created_at` / `updated_at` | DateTime(timezone=True) | обновляется при повторной оценке |

Каскад: удаление диалога удаляет сообщения и их оценки. Повторная оценка —
UPSERT по `message_id` (или UPDATE после проверки владения).

## Раскладка по слоям

- `domain/entities.py`: `Message.id`; константы `RATING_UP = "up"`,
  `RATING_DOWN = "down"`.
- `domain/ports.py`: новый порт `FeedbackStore` (`set`, `counts`,
  `list_feedback`).
- `db/models.py`: `MessageFeedbackRow`.
- `db/repos/feedback.py`: `PostgresFeedback`.
- `db/repos/postgres_history.py`: `get_messages` заполняет `Message.id`.
- `services/feedback.py`: `FeedbackService` — проверка владения диалогом,
  принадлежности сообщения диалогу, UPSERT, сводка.
- `api/routes/chat_conversations.py`: ручка оценки.
- `api/routes/admin.py`: ручка сводки (+ ссылка `feedback` в хабе).
- `frontend`: BFF `PATCH /api/conversations/[id]/messages/[mid]/feedback`,
  `GET /api/admin/feedback`; кнопки 👍/👎 под ответом (`Message.svelte`);
  страница `/admin/feedback`; ссылка в админ-хабе.

## Тесты

- `test_feedback.py`: оценка своего ответа → 204; повтор меняет оценку
  (одна строка в БД); чужой диалог → 404; несуществующее сообщение → 404;
  неверный rating → 400; длинный комментарий → 400; сводка админа
  содержит counts и свежие items; не-админ на `/admin/feedback` → 403;
  архитектурный тест (новые порты не тянут HTTP/ORM).
