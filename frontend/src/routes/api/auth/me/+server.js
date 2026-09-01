import { proxyAuth } from '$lib/server/backend.js';

export async function GET({ request }) {
	return proxyAuth('/auth/me', request, { method: 'GET' });
}
