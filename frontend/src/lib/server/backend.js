/**
 * Единственное место, где фронт знает про адрес FastAPI.
 *
 * Браузер к бэкенду не ходит: адрес живёт
 * только на сервере SvelteKit. Наружу торчит один BFF.
 */
import { json } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';

const BASE = (env.RAGKB_BACKEND_URL || env.RAGKB_API_URL || 'http://127.0.0.1:8000').replace(
	/\/$/,
	''
);

/** FastAPI, кроме `/health`, живёт под `/api/v1`. */
const API_V1 = '/api/v1';

/**
 * @param {string} path
 * @returns {string}
 */
function backendPath(path) {
	if (path === '/health' || path.startsWith('/health?')) return path;
	if (path === API_V1 || path.startsWith(`${API_V1}/`)) return path;
	return `${API_V1}${path}`;
}

/**
 * Запрос к бэкенду. Возвращает сырой Response — стрим нельзя буферизовать.
 *
 * @param {string} path
 * @param {Request} request
 * @param {RequestInit} [init]
 */
export function backend(path, request, init = {}) {
	return fetch(`${BASE}${backendPath(path)}`, {
		...init,
		headers: { 'content-type': 'application/json', .../** @type {Record<string, string>} */ (init.headers ?? {}) }
	});
}

/**
 * Человекочитаемое сообщение об отказе бэкенда.
 *
 * Коды 401/403/503 пользователь увидит своими глазами, поэтому «Not
 * authenticated» из detail здесь бесполезен — нужен текст про причину.
 */
/** @param {Response} response */
export async function failureText(response) {
	let detail = '';
	try {
		const body = await response.json();
		detail = typeof body?.detail === 'string' ? body.detail : '';
	} catch {
		/* тело не JSON — обойдёмся кодом */
	}
	if (response.status === 403) return detail || 'Недостаточно прав для этой операции.';
	if (response.status === 422) {
		// FastAPI отдаёт для 422 список объектов, а не строку: показывать
		// пользователю его сырьём бессмысленно.
		return 'Значение не подходит — проверьте введённое.';
	}
	if (response.status === 503) return `База знаний недоступна: ${detail || 'индекс не построен'}`;
	return detail || `Ошибка бэкенда (${response.status})`;
}

/** Бэкенд не отвечает вовсе: сеть, не поднятый процесс, неверный адрес. */
/**
 * Проксирует JSON-эндпоинт бэкенда «как есть».
 *
 * Отдельная функция, потому что все роуты /api/* кроме потока ответа
 * отличаются только путём и методом: разбор отказа и недоступность
 * бэкенда обрабатываются одинаково.
 *
 * @param {string} path
 * @param {Request} request
 * @param {RequestInit} [init]
 */
export async function proxyJson(path, request, init = {}) {
	let upstream;
	try {
		upstream = await backend(path, request, init);
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502 });
	}
	if (!upstream.ok) {
		return json({ detail: await failureText(upstream) }, { status: upstream.status });
	}
	return json(await upstream.json(), { status: upstream.status });
}

/** @param {unknown} error */
export function unreachable(error) {
	const reason = error instanceof Error ? error.message : String(error);
	return `Бэкенд недоступен по адресу ${BASE}: ${reason}`;
}
