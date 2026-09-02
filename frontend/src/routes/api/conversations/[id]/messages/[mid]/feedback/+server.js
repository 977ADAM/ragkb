import { json } from '@sveltejs/kit';
import { proxyJson } from '$lib/server/backend.js';

/** Оценка ответа: 👍/👎 + необязательный комментарий. */
export async function PATCH({ request, params, url }) {
	const org = url.searchParams.get('org') ?? '';
	if (!org) {
		return json({ detail: 'Организация не настроена' }, { status: 404 });
	}
	const p = `/organization/${encodeURIComponent(org)}/chat_conversations/${encodeURIComponent(params.id)}/messages/${params.mid}/feedback`;
	return proxyJson(p, request, { method: 'PATCH', body: await request.text() });
}
