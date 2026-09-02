/**
 * Состояние чата, общее для всех страниц.
 *
 * Живёт отдельным модулем, потому что панель диалогов рисует раскладка,
 * а переписку — страница: обе части смотрят в одни и те же данные.
 * Все запросы идут в собственные роуты /api/* — адрес FastAPI и заголовки
 * идентификации браузеру неизвестны.
 */

/**
 * @typedef {{n?: number, citation?: string, source?: string, page?: number | null,
 *   text?: string, available?: boolean | undefined}} Source
 * @typedef {{id?: number, role: 'user' | 'assistant', text: string,
 *   sources?: Source[], warnings?: string[], elapsed?: number | null,
 *   model?: string, error?: string, feedback?: 'up' | 'down' | null}} Message
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
	canReindex: false,
	/** Ссылка «Админ» в шапке: роль из bootstrap (`is_admin` или `role`). */
	isAdmin: false,
	/** @type {{name: string, is_admin?: boolean, role?: string} | null} */
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
function sessionId() {
	if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
		return crypto.randomUUID();
	}
	return `00000000-0000-4000-8000-${Date.now().toString(16).padStart(12, '0').slice(-12)}`;
}

export async function start() {
	if (chat.started) return;
	chat.started = true;
	const session = sessionId();
	initEvents(session);
	try {
		const response = await fetch(`/api/bootstrap?session_id=${session}`, {
			credentials: 'include'
		});
		const body = await response.json();
		if (!response.ok) {
			chat.fatal = body.detail || 'Не удалось получить стартовые сведения';
			return;
		}
		chat.user = body.user ?? null;
		chat.isAdmin = Boolean(body.user?.is_admin) || body.user?.role === 'admin';
		chat.organization = body.organization ?? null;
		chat.models = body.models ?? [];
		chat.model = (chat.models.find((m) => m.is_default) ?? chat.models[0])?.id ?? '';
		chat.historyEnabled = body.capabilities?.history !== false;
		chat.canReindex = Boolean(body.capabilities?.reindex);
		chat.conversations = body.conversations ?? [];
		chat.conversationsTotal = body.conversations_total ?? chat.conversations.length;
		if (!chat.organization?.id) {
			chat.fatal = 'Организация не задана — укажите RAGKB_ORG_NAME на сервере.';
		} else if (body.index?.status === 'no_index') {
			chat.fatal = 'Индекс не построен — нажмите «Перестроить индекс».';
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
	if (!chat.historyEnabled || !chat.organization?.id) return;
	const { offset = 0, append = false, consistency = 'strong' } = options;
	const query = new URLSearchParams({
		limit: String(PAGE),
		offset: String(offset),
		consistency
	});
	if (chat.organization?.id) query.set('org', chat.organization.id);
	try {
		const response = await fetch(`/api/conversations?${query}`, { credentials: 'include' });
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
	if (!chat.organization?.id) {
		chat.fatal = 'Организация не задана — укажите RAGKB_ORG_NAME на сервере.';
		return false;
	}
	try {
		const response = await fetch(
			`/api/conversations/${encodeURIComponent(id)}?org=${encodeURIComponent(chat.organization.id)}`,
			{ credentials: 'include' }
		);
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
				id: m.id ?? undefined,
				role: m.role,
				text: m.text,
				sources: m.sources ?? [],
				warnings: [],
				elapsed: null,
				model: m.model,
				feedback: null
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
	if (!chat.organization?.id) return;
	try {
		const response = await fetch(
			`/api/conversations/${encodeURIComponent(id)}?org=${encodeURIComponent(chat.organization.id)}`,
			{
				method: 'PATCH',
				credentials: 'include',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ title })
			}
		);
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
	if (!chat.organization?.id) return false;
	try {
		const response = await fetch(
			`/api/conversations/${encodeURIComponent(id)}?org=${encodeURIComponent(chat.organization.id)}`,
			{
				method: 'DELETE',
				credentials: 'include'
			}
		);
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
	if (!chat.organization?.id) {
		chat.fatal = 'Организация не задана — укажите RAGKB_ORG_NAME на сервере.';
		return;
	}
	chat.question = '';
	chat.busy = true;
	chat.fatal = '';
	const before = chat.conversationId;
	chat.messages = [...chat.messages, { role: 'user', text, feedback: null }];
	// Пустой ответ добавляем сразу: в него дописываются токены потока.
	chat.messages = [
		...chat.messages,
		{
			role: 'assistant',
			text: '',
			sources: [],
			warnings: [],
			elapsed: null,
			model: chat.model,
			feedback: null
		}
	];
	const index = chat.messages.length - 1;

	try {
		const response = await fetch('/api/ask', {
			method: 'POST',
			credentials: 'include',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({
				question: text,
				model: chat.model || null,
				conversation_id: chat.conversationId,
				organization_id: chat.organization?.id ?? ''
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
				chat.messages[index].id = event.message_id ?? chat.messages[index].id;
				if (event.truncated) {
					chat.messages[index].warnings = [
						...(chat.messages[index].warnings ?? []),
						'Ответ оборвался и сохранён неполностью'
					];
				}
			}
		}
	}
	if (!terminated) {
		chat.messages[index].error = 'Поток оборвался, ответ неполный';
	}
}

export async function rebuildIndex() {
	try {
		const response = await fetch('/api/index/rebuild', { method: 'POST', credentials: 'include' });
		const body = await response.json().catch(() => ({}));
		if (!response.ok) {
			chat.fatal = body.detail || 'Не удалось перестроить индекс';
			return;
		}
		chat.fatal = '';
	} catch (error) {
		chat.fatal = String(error);
	}
}

/**
 * Оценивает ответ: 👍 / 👎, повторный вызов меняет оценку.
 *
 * @param {number} messageId
 * @param {'up' | 'down'} rating
 * @param {string} [comment]
 * @returns {Promise<boolean>}
 */
export async function rateMessage(messageId, rating, comment = '') {
	if (!chat.organization?.id || !chat.conversationId) return false;
	try {
		const response = await fetch(
			`/api/conversations/${encodeURIComponent(chat.conversationId)}/messages/${messageId}/feedback?org=${encodeURIComponent(chat.organization.id)}`,
			{
				method: 'PATCH',
				credentials: 'include',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ rating, comment })
			}
		);
		if (!response.ok) return false;
		const message = chat.messages.find((m) => m.id === messageId);
		if (message) message.feedback = rating;
		return true;
	} catch {
		return false;
	}
}
