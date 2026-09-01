/**
 * Клиентская телеметрия.
 *
 * События копятся в очереди и уходят пачкой: на каждое действие отдельный
 * запрос — это лишняя нагрузка на сеть ради данных, которые никто не читает
 * в реальном времени.
 *
 * Телеметрия не должна мешать работе: любая ошибка отправки проглатывается,
 * очередь при этом очищается — копить события бесконечно хуже, чем потерять.
 */

/** @type {{name: string, ts: string, props: Record<string, unknown>}[]} */
let queue = [];
/** @type {ReturnType<typeof setTimeout> | undefined} */
let timer;
let session = '';

// Верхняя граница батча на сервере — 100 событий; отправляем заметно раньше.
const BATCH = 20;
const DELAY = 5000;

/** @param {string} sessionId идентификатор сессии, тот же, что у bootstrap */
export function initEvents(sessionId) {
	session = sessionId;
	if (typeof document === 'undefined') return;
	// Вкладку закрывают или прячут — отправляем накопленное, пока можем.
	document.addEventListener('visibilitychange', () => {
		if (document.visibilityState === 'hidden') flush();
	});
}

/**
 * @param {string} name
 * @param {Record<string, unknown>} [props]
 */
export function track(name, props = {}) {
	if (!session) return;
	queue.push({ name, ts: new Date().toISOString(), props });
	if (queue.length >= BATCH) {
		flush();
		return;
	}
	clearTimeout(timer);
	timer = setTimeout(flush, DELAY);
}

export function flush() {
	clearTimeout(timer);
	if (!session || queue.length === 0) return;
	const events = queue;
	queue = [];
	fetch('/api/events', {
		method: 'POST',
		credentials: 'include',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ session_id: session, events }),
		keepalive: true
	}).catch(() => {
		/* телеметрия не повод показывать пользователю ошибку */
	});
}
