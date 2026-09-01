import { proxyAuth } from '$lib/server/backend.js';

export async function POST({ request }) {
	return proxyAuth('/auth/register', request, { method: 'POST', body: await request.text() });
}
