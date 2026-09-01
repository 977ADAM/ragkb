import { proxyAuth } from '$lib/server/backend.js';

export async function POST({ request }) {
	return proxyAuth('/auth/logout', request, { method: 'POST' });
}
