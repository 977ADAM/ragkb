import { json } from '@sveltejs/kit';
import { backend, failureText, unreachable } from '$lib/server/backend.js';

export async function DELETE({ request, params }) {
	const path = `/admin/documents/${encodeURIComponent(params.name)}`;
	let upstream;
	try {
		upstream = await backend(path, request, { method: 'DELETE' });
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502 });
	}
	if (!upstream.ok) {
		return json({ detail: await failureText(upstream) }, { status: upstream.status });
	}
	return new Response(null, { status: 204 });
}
