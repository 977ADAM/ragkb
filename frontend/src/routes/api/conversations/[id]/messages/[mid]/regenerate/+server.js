import { backend, failureText, unreachable } from '$lib/server/backend.js';

/** Перегенерация последнего ответа: поток NDJSON, как у обычного вопроса. */
export async function POST({ request, params, url }) {
	const org = url.searchParams.get('org') ?? '';
	if (!org) {
		return new Response(JSON.stringify({ detail: 'Организация не настроена' }), {
			status: 404,
			headers: { 'content-type': 'application/json' }
		});
	}
	const path = `/organization/${encodeURIComponent(org)}/chat_conversations/${encodeURIComponent(params.id)}/messages/${params.mid}/regenerate`;
	const payload = await request.json().catch(() => ({}));
	let upstream;
	try {
		upstream = await backend(path, request, {
			method: 'POST',
			body: JSON.stringify({
				top_k: payload.top_k ?? null,
				expand: payload.expand ?? false,
				model: payload.model ?? null
			})
		});
	} catch (error) {
		return new Response(JSON.stringify({ detail: unreachable(error) }), {
			status: 502,
			headers: { 'content-type': 'application/json' }
		});
	}
	if (!upstream.ok) {
		return new Response(JSON.stringify({ detail: await failureText(upstream) }), {
			status: upstream.status,
			headers: { 'content-type': 'application/json' }
		});
	}
	return new Response(upstream.body, {
		headers: {
			'content-type': 'application/x-ndjson; charset=utf-8',
			'cache-control': 'no-store'
		}
	});
}
