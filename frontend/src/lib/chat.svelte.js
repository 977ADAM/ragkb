/** Текущая лента живёт только в памяти страницы. */
import { initEvents, track } from '$lib/events.svelte.js';
import { readAnswer } from '$lib/answer-stream.js';

/**
 * @typedef {{n?: number, citation?: string, source?: string, page?: number | null,
 * text?: string, available?: boolean}} Source
 * @typedef {{role: 'user' | 'assistant', text: string, sources?: Source[],
 * warnings?: string[], elapsed?: number | null, model?: string, error?: string}} Message
 */
export const chat = $state({
    /** @type {Message[]} */
    messages: [], question: '',
    /** @type {{id: string, display_name?: string, is_default?: boolean}[]} */
    models: [], model: '',
    /** @type {{id: string, name: string, description?: string} | null} */
    organization: null,
    version: '', busy: false, fatal: '', started: false
});

export async function start() {
    if (chat.started) return;
    chat.started = true;
    const session = globalThis.crypto?.randomUUID?.() ??
        `00000000-0000-4000-8000-${Date.now().toString(16).padStart(12, '0').slice(-12)}`;
    initEvents(session);
    try {
        const response = await fetch(`/api/bootstrap?session_id=${session}`);
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || 'Не удалось загрузить базу знаний');
        chat.organization = body.organization ?? null;
        chat.version = body.version ?? '';
        chat.models = body.models ?? [];
        chat.model = (chat.models.find(m => m.is_default) ?? chat.models[0])?.id ?? '';
        if (body.index?.status === 'no_index') {
            chat.fatal = 'Индекс не построен — примите документы и перестройте индекс.';
        }
    } catch (error) {
        chat.fatal = String(error);
        chat.started = false;
    }
}

export function reset() {
    if (chat.busy) return;
    chat.messages = [];
    chat.question = '';
    chat.fatal = '';
}

export async function ask() {
    const question = chat.question.trim();
    if (question.length < 2 || chat.busy) return;
    chat.question = '';
    chat.messages.push({role: 'user', text: question});
    await answer(question);
}

/** @param {string} question */
async function answer(question) {
    chat.busy = true;
    chat.fatal = '';
    chat.messages.push({role: 'assistant', text: '', sources: [], warnings: [], model: chat.model});
    const index = chat.messages.length - 1;
    try {
        const response = await fetch('/api/ask', {
            method: 'POST', headers: {'content-type': 'application/json'},
            body: JSON.stringify({question, model: chat.model || null})
        });
        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            throw new Error(body.detail || `Ошибка ${response.status}`);
        }
        if (!response.body) throw new Error('Пустой ответ от сервера');
        await readAnswer(response.body, event => {
            const message = chat.messages[index];
            if (event.type === 'token') message.text += event.text;
            if (event.type === 'done') {
                message.sources = event.sources ?? [];
                message.warnings = event.warnings ?? [];
                message.elapsed = event.elapsed_sec ?? null;
                message.model = event.model ?? message.model;
                if (event.truncated && !message.warnings?.length) {
                    message.warnings = ['Ответ оборвался до завершения'];
                }
            }
        });
    } catch (error) {
        chat.messages[index].error = String(error);
    } finally {
        chat.busy = false;
        const message = chat.messages[index];
        track('ask', {model: message.model, failed: Boolean(message.error)});
    }
}

export async function regenerateMessage() {
    if (chat.busy || chat.messages.at(-1)?.role !== 'assistant') return false;
    const question = chat.messages.at(-2);
    if (question?.role !== 'user') return false;
    chat.messages.pop();
    await answer(question.text);
    return !chat.messages.at(-1)?.error;
}

export async function rebuildIndex() {
    if (chat.busy) return;
    chat.busy = true;
    try {
        const response = await fetch('/api/index/rebuild', {method: 'POST'});
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || 'Не удалось перестроить индекс');
        chat.fatal = '';
    } catch (error) {
        chat.fatal = String(error);
    } finally {
        chat.busy = false;
    }
}

/** @param {string} text @returns {Promise<boolean>} */
export async function copyText(text) {
	if (navigator.clipboard?.writeText) {
		try {
			await navigator.clipboard.writeText(text);
			return true;
		} catch {
			// небезопасный контекст — ниже фолбэк
		}
	}
	try {
		const area = document.createElement('textarea');
		area.value = text;
		area.style.position = 'fixed';
		area.style.opacity = '0';
		document.body.appendChild(area);
		area.select();
		const ok = document.execCommand('copy');
		document.body.removeChild(area);
		return ok;
	} catch {
		return false;
	}
}
