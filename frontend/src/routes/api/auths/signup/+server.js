import { proxyAuth } from '$lib/server/backend.js';

export async function POST({ request }) {
	return proxyAuth('/auths/signup', request, { method: 'POST', body: await request.text() });
}
