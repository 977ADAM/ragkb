import { json } from '@sveltejs/kit';
import { backend, failureText, unreachable } from '$lib/server/backend.js';

/** Настройки: чтение списка полей и применение правок. */
export function GET({ request }) {
	return proxy('/admin/settings', request, { method: 'GET' });
}

export async function PUT({ request }) {
	return proxy('/admin/settings', request, {
		method: 'PUT',
		headers: { 'content-type': 'application/json' },
		body: await request.text()
	});
}

/**
 * @param {string} path
 * @param {Request} request
 * @param {RequestInit} init
 */
async function proxy(path, request, init) {
	let upstream;
	try {
		upstream = await backend(path, request, init);
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502 });
	}
	if (!upstream.ok) {
		return json({ detail: await failureText(upstream) }, { status: upstream.status });
	}
	return json(await upstream.json());
}
