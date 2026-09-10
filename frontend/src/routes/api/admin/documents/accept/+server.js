import { json } from '@sveltejs/kit';
import { backend, failureText, unreachable } from '$lib/server/backend.js';

/** Принятие в корпус файлов, положенных в каталог мимо интерфейса. */
export async function POST({ request }) {
	let upstream;
	try {
		upstream = await backend('/admin/documents/accept', request, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: await request.text()
		});
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502 });
	}
	if (!upstream.ok) {
		return json({ detail: await failureText(upstream) }, { status: upstream.status });
	}
	return json(await upstream.json());
}
