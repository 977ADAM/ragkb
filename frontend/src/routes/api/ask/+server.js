import { json } from '@sveltejs/kit';
import { backend, failureText, unreachable } from '$lib/server/backend.js';

export async function POST({ request }) {
	const payload = await request.json();
	const org = payload.organization_id;
	if (!org) {
		return json({ detail: 'Организация не настроена' }, { status: 404 });
	}
	let cid = payload.conversation_id;
	if (!cid) {
		let created;
		try {
			created = await backend(`/organization/${encodeURIComponent(org)}/chat_conversations`, request, {
				method: 'POST',
				body: '{}'
			});
		} catch (error) {
			return json({ detail: unreachable(error) }, { status: 502 });
		}
		if (!created.ok) {
			return json({ detail: await failureText(created) }, { status: created.status });
		}
		const body = await created.json();
		cid = body.conversation_id;
	}
	const path = `/organization/${encodeURIComponent(org)}/chat_conversations/${encodeURIComponent(cid)}/messages`;
	let upstream;
	try {
		upstream = await backend(path, request, {
			method: 'POST',
			body: JSON.stringify({
				question: payload.question,
				model: payload.model ?? null,
				top_k: payload.top_k ?? null,
				expand: payload.expand ?? false
			})
		});
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502 });
	}
	if (!upstream.ok) {
		return json({ detail: await failureText(upstream) }, { status: upstream.status });
	}
	return new Response(upstream.body, {
		headers: {
			'content-type': 'application/x-ndjson; charset=utf-8',
			'cache-control': 'no-store',
			'x-conversation-id': cid
		}
	});
}
