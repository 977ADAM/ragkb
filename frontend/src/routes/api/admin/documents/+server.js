import { json } from '@sveltejs/kit';
import { backend, failureText, unreachable } from '$lib/server/backend.js';

export function GET({ request, url }) {
	return proxyDocuments(request, url, { method: 'GET' });
}

export async function POST({ request, url }) {
	// Передаём multipart как есть: тело + исходный content-type (с boundary).
	const contentType = request.headers.get('content-type') ?? 'application/octet-stream';
	return proxyDocuments(request, url, {
		method: 'POST',
		headers: { 'content-type': contentType },
		body: await request.arrayBuffer()
	});
}

/**
 * Параметр `index=false` позволяет загрузить пачку файлов и пересобрать
 * индекс один раз в конце, а не после каждого файла.
 *
 * @param {Request} request
 * @param {URL} url
 * @param {RequestInit} init
 */
async function proxyDocuments(request, url, init) {
	let upstream;
	try {
		upstream = await backend(`/admin/documents${url.search}`, request, init);
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502 });
	}
	if (!upstream.ok) {
		return json({ detail: await failureText(upstream) }, { status: upstream.status });
	}
	return json(await upstream.json());
}
