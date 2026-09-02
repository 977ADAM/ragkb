import { proxyAuth, proxyJson } from '$lib/server/backend.js';

/** @param {string} username */
function path(username) {
	return `/admin/users/${encodeURIComponent(username)}`;
}

export async function PATCH({ request, params }) {
	return proxyJson(path(params.username), request, {
		method: 'PATCH',
		body: await request.text()
	});
}

export function DELETE({ request, params }) {
	return proxyAuth(path(params.username), request, { method: 'DELETE' });
}
