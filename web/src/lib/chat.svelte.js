/**
 * Состояние чата, общее для всех страниц.
 *
 * Живёт отдельным модулем, потому что панель диалогов рисует раскладка,
 * а переписку — страница: обе части смотрят в одни и те же данные.
 * Все запросы идут в собственные роуты /api/* — адрес FastAPI и заголовки
 * идентификации браузеру неизвестны.
 */

/**
 * @typedef {{source?: string, title?: string, available?: boolean}} Source
 * @typedef {{role: 'user' | 'assistant', text: string, sources?: Source[],
 *   warnings?: string[], elapsed?: number | null, model?: string, error?: string}} Message
 * @typedef {{id: string, title: string, updated_at?: string}} Conversation
 */

import { initEvents, track } from '$lib/events.svelte.js';

export const chat = $state({
	/** @type {Message[]} */
	messages: [],
	question: '',
	/** @type {{id: string, display_name?: string, is_default?: boolean}[]} */
	models: [],
	model: '',
	/** @type {Conversation[]} */
	conversations: [],
	/** Сколько всего диалогов у пользователя — для кнопки «Показать ещё». */
	conversationsTotal: 0,
	/** Идентификатор открытого диалога. null — новый, ещё не заведённый. */
	/** @type {string | null} */
	conversationId: null,
	// История может быть выключена на бэкенде — тогда панель диалогов
	// не показываем вовсе: пустой список соврал бы, что диалогов нет,
	// хотя их просто негде хранить.
	historyEnabled: true,
	/** @type {{name: string, is_admin?: boolean} | null} */
	user: null,
	/** @type {{id: string, name: string, description?: string} | null} */
	organization: null,
	busy: false,
	fatal: '',
	/** Стартовый запрос уже выполнен — при переходах между страницами не повторяем. */
	started: false
});

/**
 * Один запрос при запуске вместо трёх: пользователь, организация, модели,
 * диалоги и признаки возможностей приходят вместе.
 *
 * Идентификатор сессии придумывает браузер и присылает серверу — тот
 * возвращает его эхом и пишет в лог, поэтому старт конкретной вкладки
 * можно проследить в журнале.
 */
export async function start() {
	if (chat.started) return;
	chat.started = true;
	const session = crypto.randomUUID();
	initEvents(session);
	try {
		const response = await fetch(`/api/bootstrap?session=${session}`);
		const body = await response.json();
		if (!response.ok) {
			chat.fatal = body.detail || 'Не удалось получить стартовые сведения';
			return;
		}
		chat.user = body.user ?? null;
		chat.organization = body.organization ?? null;
		chat.models = body.models ?? [];
		chat.model = (chat.models.find((m) => m.is_default) ?? chat.models[0])?.id ?? '';
		chat.historyEnabled = body.capabilities?.history !== false;
		chat.conversations = body.conversations ?? [];
		chat.conversationsTotal = body.conversations_total ?? chat.conversations.length;
		if (body.index?.status === 'no_index') {
			chat.fatal = 'Индекс не построен — ответы пока невозможны.';
		}
		track('app_start', { index: body.index?.status, models: chat.models.length });
	} catch (error) {
		chat.fatal = String(error);
	}
}

/** Сколько диалогов запрашиваем за раз. Наружу не нужно — размер страницы
 * дело самого модуля. */
const PAGE = 50;

/**
 * Список диалогов страницами.
 *
 * @param {{offset?: number, append?: boolean, consistency?: 'strong' | 'eventual'}} [options]
 *   append — дописать к уже загруженным («Показать ещё»), иначе заменить;
 *   consistency=eventual разрешает серверу ответить из кеша: годится для
 *   фонового обновления, но не после только что заданного вопроса.
 */
export async function loadConversations(options = {}) {
	if (!chat.historyEnabled) return;
	const { offset = 0, append = false, consistency = 'strong' } = options;
	const query = new URLSearchParams({
		limit: String(PAGE),
		offset: String(offset),
		consistency
	});
	if (chat.organization?.id) query.set('org', chat.organization.id);
	try {
		const response = await fetch(`/api/conversations?${query}`);
		if (response.status === 404) {
			chat.historyEnabled = false;
			return;
		}
		const body = await response.json();
		if (!response.ok) {
			chat.fatal = body.detail || 'Не удалось получить список диалогов';
			return;
		}
		const page = body.conversations ?? [];
		chat.conversations = append ? [...chat.conversations, ...page] : page;
		chat.conversationsTotal = body.total ?? chat.conversations.length;
	} catch (error) {
		chat.fatal = String(error);
	}
}

/** Догружает следующую страницу списка. */
export function loadMoreConversations() {
	return loadConversations({ offset: chat.conversations.length, append: true });
}

/**
 * Открывает диалог по идентификатору из адреса.
 *
 * @param {string} id
 * @returns {Promise<boolean>} false — диалога нет или он чужой
 */
export async function openConversation(id) {
	try {
		const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`);
		const body = await response.json();
		if (!response.ok) {
			chat.fatal = response.status === 404 ? 'Диалог не найден' : body.detail || 'Ошибка';
			return false;
		}
		chat.conversationId = id;
		chat.fatal = '';
		// Предупреждения и время ответа не хранятся — они относились к тому
		// разу, когда ответ рождался. Источники и модель хранятся и нужны.
		chat.messages = (body.messages ?? []).map(
			/** @param {any} m */ (m) => ({
				role: m.role,
				text: m.text,
				sources: m.sources ?? [],
				warnings: [],
				elapsed: null,
				model: m.model
			})
		);
		return true;
	} catch (error) {
		chat.fatal = String(error);
		return false;
	}
}

/** Пустая переписка — страница /new. */
export function reset() {
	chat.messages = [];
	chat.conversationId = null;
	chat.fatal = '';
}

/**
 * Переименование диалога.
 *
 * @param {string} id
 * @param {string} title
 */
export async function renameConversation(id, title) {
	try {
		const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
			method: 'PATCH',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ title })
		});
		const body = await response.json().catch(() => ({}));
		if (!response.ok) {
			chat.fatal = body.detail || 'Не удалось переименовать диалог';
			return;
		}
		// Ответ несёт заголовок после нормализации на сервере — берём его,
		// а не то, что набрали в поле.
		chat.conversations = chat.conversations.map((c) =>
			c.id === id ? { ...c, title: body.title ?? title } : c
		);
	} catch (error) {
		chat.fatal = String(error);
	}
}

/**
 * Удаление диалога. Возвращает true, если удалили открытый — тогда странице
 * нужно уйти на /new, иначе она осталась бы на несуществующем адресе.
 *
 * @param {string} id
 */
export async function removeConversation(id) {
	try {
		const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
			method: 'DELETE'
		});
		if (!response.ok) {
			const body = await response.json().catch(() => ({}));
			chat.fatal = body.detail || 'Не удалось удалить диалог';
			return false;
		}
		chat.conversations = chat.conversations.filter((c) => c.id !== id);
		chat.conversationsTotal = Math.max(0, chat.conversationsTotal - 1);
		return chat.conversationId === id;
	} catch (error) {
		chat.fatal = String(error);
		return false;
	}
}

/**
 * Задаёт вопрос и вычитывает потоковый ответ.
 *
 * @param {(id: string) => void} [onCreated] вызывается, когда сервер завёл
 *   новый диалог: страница /new должна сменить адрес на /chat/{id}.
 */
export async function ask(onCreated) {
	const text = chat.question.trim();
	if (!text || chat.busy) return;
	chat.question = '';
	chat.busy = true;
	chat.fatal = '';
	const before = chat.conversationId;
	chat.messages = [...chat.messages, { role: 'user', text }];
	// Пустой ответ добавляем сразу: в него дописываются токены потока.
	chat.messages = [
		...chat.messages,
		{ role: 'assistant', text: '', sources: [], warnings: [], elapsed: null, model: chat.model }
	];
	const index = chat.messages.length - 1;

	try {
		const response = await fetch('/api/ask', {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({
				question: text,
				model: chat.model || null,
				conversation_id: chat.conversationId
			})
		});
		if (!response.ok) {
			const body = await response.json().catch(() => ({}));
			chat.messages[index].error = body.detail || `Ошибка ${response.status}`;
			return;
		}
		if (!response.body) throw new Error('Пустой ответ от сервера');
		await consume(response.body, index);
	} catch (error) {
		chat.messages[index].error = String(error);
	} finally {
		chat.busy = false;
		const answer = chat.messages[index];
		track('ask', {
			model: answer.model,
			elapsed_sec: answer.elapsed,
			sources: answer.sources?.length ?? 0,
			warnings: answer.warnings?.length ?? 0,
			failed: Boolean(answer.error)
		});
		// Список обновляем после ответа: заголовок новому диалогу даёт
		// сервер по первому вопросу, а порядок — по времени последней реплики.
		await loadConversations();
		if (!before && chat.conversationId) onCreated?.(chat.conversationId);
	}
}

/**
 * Читает NDJSON: по объекту на строку, последняя строка может быть неполной.
 *
 * @param {ReadableStream<Uint8Array>} body
 * @param {number} index
 */
async function consume(body, index) {
	const reader = body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';
	let terminated = false;
	for (;;) {
		const { value, done } = await reader.read();
		if (done) break;
		buffer += decoder.decode(value, { stream: true });
		const lines = buffer.split('\n');
		buffer = lines.pop() ?? '';
		for (const line of lines) {
			if (!line.trim()) continue;
			let event;
			try {
				event = JSON.parse(line);
			} catch {
				continue;
			}
			if (event.type === 'token') {
				chat.messages[index].text += event.text;
			} else if (event.type === 'done') {
				terminated = true;
				chat.conversationId = event.conversation_id ?? chat.conversationId;
				chat.messages[index].sources = event.sources ?? [];
				chat.messages[index].warnings = event.warnings ?? [];
				chat.messages[index].elapsed = event.elapsed_sec ?? null;
				chat.messages[index].model = event.model ?? chat.messages[index].model;
			} else if (event.type === 'error') {
				terminated = true;
				chat.messages[index].error = event.detail || 'Генерация прервалась';
			}
		}
	}
	if (!terminated) {
		// Молчаливый обрыв выглядит как зависший ответ — говорим прямо.
		chat.messages[index].error = 'Поток оборвался, ответ неполный';
	}
}
