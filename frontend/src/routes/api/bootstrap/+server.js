import { proxyJson } from '$lib/server/backend.js';

export function GET({ request, url }) {
	const session = url.searchParams.get('session_id') ?? '';
	return proxyJson(`/bootstrap?session_id=${encodeURIComponent(session)}`, request);
}
