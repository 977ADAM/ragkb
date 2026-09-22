import { json } from '@sveltejs/kit';
import { backend, failureText, unreachable } from '$lib/server/backend.js';
import { createRequestId } from '$lib/server/request-context.js';

/** @param {import('@sveltejs/kit').RequestEvent} event */
export function GET({ request, url }) {
	return proxyDocuments(request, url, { method: 'GET' });
}

/** @param {import('@sveltejs/kit').RequestEvent} event */
export async function POST({ request, url }) {
	// Передаём multipart как есть: тело + исходный content-type (с boundary).
	const contentType = request.headers.get('content-type') ?? 'application/octet-stream';
	// Метка запроса связывает запись об изменении разрешения в журнале backend
	// с этим запросом: без неё событие не сопоставить с действием посетителя.
	const requestId = createRequestId();
	return proxyDocuments(
		request,
		url,
		{
			method: 'POST',
			headers: { 'content-type': contentType, 'x-request-id': requestId },
			body: await request.arrayBuffer()
		},
		requestId
	);
}

/**
 * Параметр `index=false` позволяет загрузить пачку файлов и пересобрать
 * индекс один раз в конце, а не после каждого файла.
 *
 * @param {Request} request
 * @param {URL} url
 * @param {RequestInit} init
 * @param {string} [requestId]
 */
async function proxyDocuments(request, url, init, requestId) {
	/** @type {Record<string, string>} */
	const headers = requestId ? { 'x-request-id': requestId } : {};
	let upstream;
	try {
		upstream = await backend(`/admin/documents${url.search}`, request, init);
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502, headers });
	}
	if (!upstream.ok) {
		return json({ detail: await failureText(upstream) }, { status: upstream.status, headers });
	}
	return json(await upstream.json(), { headers });
}
