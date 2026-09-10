import { proxyJson } from '$lib/server/backend.js';

export function GET({ request }) {
	return proxyJson('/admin/users', request, { method: 'GET' });
}

export async function POST({ request }) {
	return proxyJson('/admin/users', request, {
		method: 'POST',
		body: await request.text()
	});
}
