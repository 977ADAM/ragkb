import { proxyAuth } from '$lib/server/backend.js';

export function GET({ request }) {
	return proxyAuth('/auths/profile', request, { method: 'GET' });
}
