import { json } from '@sveltejs/kit';
import { backend, failureText, unreachable } from '$lib/server/backend.js';

/**
 * Проксирует POST /ask/stream.
 *
 * Тело отдаётся ровно тем же потоком, что пришёл от бэкенда: буферизация
 * убила бы весь смысл стриминга — ответ идёт от пяти до тринадцати секунд.
 */
export async function POST({ request }) {
	const payload = await request.text();
	let upstream;
	try {
		upstream = await backend('/ask/stream', request, { method: 'POST', body: payload });
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502 });
	}
	if (!upstream.ok) {
		return json({ detail: await failureText(upstream) }, { status: upstream.status });
	}
	return new Response(upstream.body, {
		headers: {
			'content-type': 'application/x-ndjson; charset=utf-8',
			'cache-control': 'no-store'
		}
	});
}
