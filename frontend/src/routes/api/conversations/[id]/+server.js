import { json } from '@sveltejs/kit';
import { proxyJson } from '$lib/server/backend.js';

function path(url, id) {
	const org = url.searchParams.get('org') ?? '';
	if (!org) return null;
	return `/organization/${encodeURIComponent(org)}/chat_conversations/${encodeURIComponent(id)}`;
}

export function GET({ request, params, url }) {
	const p = path(url, params.id);
	if (!p) return json({ detail: 'Организация не настроена' }, { status: 404 });
	return proxyJson(p, request);
}

export async function PATCH({ request, params, url }) {
	const p = path(url, params.id);
	if (!p) return json({ detail: 'Организация не настроена' }, { status: 404 });
	return proxyJson(p, request, { method: 'PATCH', body: await request.text() });
}

export function DELETE({ request, params, url }) {
	const p = path(url, params.id);
	if (!p) return json({ detail: 'Организация не настроена' }, { status: 404 });
	return proxyJson(p, request, { method: 'DELETE' });
}
