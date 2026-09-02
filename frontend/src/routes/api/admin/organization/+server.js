import { proxyJson } from '$lib/server/backend.js';

export function GET({ request }) {
	return proxyJson('/admin/organization', request, { method: 'GET' });
}
