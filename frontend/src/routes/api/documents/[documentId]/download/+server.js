/**
 * Потоковая выдача оригинала через BFF.
 *
 * Браузер не знает адреса backend: файл идёт через этот маршрут, и здесь же
 * стоят ограничения — иначе прямой доступ к порту BFF обходил бы их.
 * Ограничитель живёт в процессе frontend: при нескольких репликах счётчики
 * окажутся независимыми, и общую защиту должен дать внешний прокси.
 */
import { env } from '$env/dynamic/private';
import { backendUrl } from '$lib/server/backend.js';
import { createDownloadLimiter, readLimiterConfig } from '$lib/server/download-limiter.js';
import { downloadLogLine, proxyDownload } from '$lib/server/download-proxy.js';
import { clientAddress, createRequestId } from '$lib/server/request-context.js';

/** @type {ReturnType<typeof createDownloadLimiter> | null} */
let limiter = null;

/** @param {import('@sveltejs/kit').RequestEvent} event */
function download(event) {
	// Настройки читаются при первом обращении: некорректное значение — ошибка
	// конфигурации, а не молча подставленное умолчание.
	limiter ??= createDownloadLimiter(readLimiterConfig(env));
	return proxyDownload({
		request: event.request,
		documentId: event.params.documentId ?? '',
		// Адрес даёт соединение, а не заголовок браузера.
		clientAddress: clientAddress(event),
		requestId: createRequestId(),
		limiter,
		upstreamFetch: (path, init) => fetch(backendUrl(path), init),
		log: (record) => console.log(downloadLogLine(record))
	});
}

/** @param {import('@sveltejs/kit').RequestEvent} event */
export async function GET(event) {
	return download(event);
}

/** @param {import('@sveltejs/kit').RequestEvent} event */
export async function HEAD(event) {
	return download(event);
}
