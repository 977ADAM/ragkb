import { proxyAuth } from '$lib/server/backend.js';

export async function GET({ request }) {
	return proxyAuth('/auths/me', request, { method: 'GET' });
}
