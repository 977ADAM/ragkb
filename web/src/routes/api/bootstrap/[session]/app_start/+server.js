import { proxyJson } from '$lib/server/backend.js';

/**
 * Стартовые сведения одним запросом.
 *
 * Путь повторяет бэкендный: идентификатор сессии — часть адреса, а не
 * параметр запроса. Параметры запроса пробрасываются как есть — клиент
 * вправе просить подробности, о которых BFF знать не обязан.
 */
export function GET({ request, params, url }) {
	return proxyJson(
		`/bootstrap/${encodeURIComponent(params.session)}/app_start${url.search}`,
		request
	);
}
