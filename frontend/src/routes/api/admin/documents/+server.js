import { json } from '@sveltejs/kit';
import { backend, failureText, unreachable } from '$lib/server/backend.js';

export function GET({ request }) {
	return proxyDocuments(request, { method: 'GET' });
}

export async function POST({ request }) {
	// Передаём multipart как есть: тело + исходный content-type (с boundary).
	const contentType = request.headers.get('content-type') ?? 'application/octet-stream';
	return proxyDocuments(request, {
		method: 'POST',
		headers: { 'content-type': contentType },
		body: await request.arrayBuffer()
	});
}

/**
 * @param {Request} request
 * @param {RequestInit} init
 */
async function proxyDocuments(request, init) {
	let upstream;
	try {
		upstream = await backend('/admin/documents', request, init);
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502 });
	}
	if (!upstream.ok) {
		return json({ detail: await failureText(upstream) }, { status: upstream.status });
	}
	return json(await upstream.json());
}
