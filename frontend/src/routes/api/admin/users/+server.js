import { proxyJson } from '$lib/server/backend.js';

export function GET({ request }) {
	return proxyJson('/admin/users', request, { method: 'GET' });
}
