import { redirect } from '@sveltejs/kit';
import { backend } from '$lib/server/backend.js';

const PUBLIC = new Set(['/login', '/register']);

export async function handle({ event, resolve }) {
	const path = event.url.pathname;
	if (path.startsWith('/api/') || path === '/health') {
		return resolve(event);
	}
	let me = 401;
	try {
		const res = await backend('/auth/me', event.request);
		me = res.status;
	} catch {
		me = 502;
	}
	if (PUBLIC.has(path)) {
		if (me === 200) redirect(303, '/new');
		return resolve(event);
	}
	if (me !== 200) redirect(303, '/login');
	return resolve(event);
}
