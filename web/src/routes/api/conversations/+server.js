import { proxyJson } from '$lib/server/backend.js';

/**
 * Список диалогов страницами.
 *
 * Куда идти, решает сервер: у настроенной организации диалоги берутся
 * из её ручки, иначе — из общей. Браузеру устройство чужого API не нужно,
 * он присылает только идентификатор организации из стартового ответа.
 */
export function GET({ request, url }) {
	const org = url.searchParams.get('org') ?? '';
	const query = new URLSearchParams({
		limit: url.searchParams.get('limit') ?? '50',
		offset: url.searchParams.get('offset') ?? '0'
	});
	if (!org) {
		// Организация не настроена — постраничная ручка вернула бы 404.
		return proxyJson(`/conversations?${query}`, request);
	}
	query.set('consistency', url.searchParams.get('consistency') ?? 'strong');
	return proxyJson(
		`/organizations/${encodeURIComponent(org)}/chat_conversations?${query}`,
		request
	);
}
