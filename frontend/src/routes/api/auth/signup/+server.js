import { proxyAuth } from '$lib/server/backend.js';

export async function POST({ request }) {
	return proxyAuth('/auth/signup', request, { method: 'POST', body: await request.text() });
}
