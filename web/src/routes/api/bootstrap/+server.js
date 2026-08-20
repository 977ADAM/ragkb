import { proxyJson } from '$lib/server/backend.js';

/**
 * Стартовые сведения одним запросом.
 *
 * Идентификатор сессии генерирует браузер и присылает параметром — в путь
 * бэкенда он попадает уже здесь, чтобы клиент не знал устройства чужого API.
 */
export function GET({ request, url }) {
	const session = url.searchParams.get('session') ?? '';
	return proxyJson(
		`/bootstrap/${encodeURIComponent(session)}/app_start`,
		request
	);
}
