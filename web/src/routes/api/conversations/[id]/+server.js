import { proxyJson } from '$lib/server/backend.js';

/** Сообщения одного диалога. */
export function GET({ request, params }) {
	return proxyJson(`/conversations/${encodeURIComponent(params.id)}`, request);
}

/** Переименование диалога. */
export async function PATCH({ request, params }) {
	return proxyJson(`/conversations/${encodeURIComponent(params.id)}`, request, {
		method: 'PATCH',
		body: await request.text()
	});
}

/** Удаление диалога. */
export function DELETE({ request, params }) {
	return proxyJson(`/conversations/${encodeURIComponent(params.id)}`, request, {
		method: 'DELETE'
	});
}
