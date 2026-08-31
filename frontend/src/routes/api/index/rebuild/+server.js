import { proxyJson } from '$lib/server/backend.js';

export function POST({ request }) {
	return proxyJson('/index/rebuild', request, { method: 'POST', body: '{}' });
}
