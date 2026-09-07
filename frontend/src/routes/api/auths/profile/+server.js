import { proxyAuth } from '$lib/server/backend.js';

export function GET({ request }) {
	return proxyAuth('/auth/profile', request, { method: 'GET' });
}
