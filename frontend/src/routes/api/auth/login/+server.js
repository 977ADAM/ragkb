import { proxyAuth } from '$lib/server/backend.js';

export async function POST({ request }) {
	return proxyAuth('/auth/login', request, { method: 'POST', body: await request.text() });
}
