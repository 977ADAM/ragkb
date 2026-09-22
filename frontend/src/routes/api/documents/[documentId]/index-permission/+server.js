import { json } from '@sveltejs/kit';
import { backend, failureText, unreachable } from '$lib/server/backend.js';
import { createRequestId } from '$lib/server/request-context.js';

const NO_STORE = { 'cache-control': 'no-store' };

/** @param {import('@sveltejs/kit').RequestEvent} event */
export async function PATCH({ request, params }) {
	/** @type {unknown} */
	let payload;
	try {
		payload = await request.json();
	} catch {
		return json({ detail: 'Некорректный JSON' }, { status: 400, headers: NO_STORE });
	}

	const requestId = createRequestId();
	let upstream;
	try {
		upstream = await backend(
			`/documents/${encodeURIComponent(params.documentId ?? '')}/index-permission`,
			request,
			{
				method: 'PATCH',
				headers: { 'x-request-id': requestId },
				body: JSON.stringify(payload)
			}
		);
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502, headers: NO_STORE });
	}
	if (!upstream.ok) {
		return json(
			{ detail: await failureText(upstream) },
			{ status: upstream.status, headers: NO_STORE }
		);
	}
	return json(await upstream.json(), {
		headers: { ...NO_STORE, 'x-request-id': requestId }
	});
}
