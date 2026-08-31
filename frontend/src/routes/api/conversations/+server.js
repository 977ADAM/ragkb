import { json } from '@sveltejs/kit';
import { proxyJson } from '$lib/server/backend.js';

export function GET({ request, url }) {
	const org = url.searchParams.get('org') ?? '';
	if (!org) {
		return json({ detail: 'Организация не настроена' }, { status: 404 });
	}
	const query = new URLSearchParams({
		limit: url.searchParams.get('limit') ?? '50',
		offset: url.searchParams.get('offset') ?? '0',
		consistency: url.searchParams.get('consistency') ?? 'strong'
	});
	return proxyJson(
		`/organization/${encodeURIComponent(org)}/chat_conversations?${query}`,
		request
	);
}

export function POST({ request, url }) {
	const org = url.searchParams.get('org') ?? '';
	if (!org) {
		return json({ detail: 'Организация не настроена' }, { status: 404 });
	}
	return proxyJson(`/organization/${encodeURIComponent(org)}/chat_conversations`, request, {
		method: 'POST',
		body: '{}'
	});
}
