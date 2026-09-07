import { proxyAuth } from '$lib/server/backend.js';

export async function POST({ request }) {
	return proxyAuth('/auth/signin', request, { method: 'POST', body: await request.text() });
}
