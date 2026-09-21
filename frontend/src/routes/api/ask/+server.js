import { json } from '@sveltejs/kit';
import { backend, failureText, unreachable } from '$lib/server/backend.js';

export async function POST({ request }) {
    let payload;
    try { payload = await request.json(); }
    catch { return json({detail: 'Некорректный JSON'}, {status: 400}); }
    let upstream;
    try {
        upstream = await backend('/ask', request, {method: 'POST', body: JSON.stringify(payload)});
    } catch (error) {
        return json({detail: unreachable(error)}, {status: 502});
    }
    if (!upstream.ok) return json({detail: await failureText(upstream)}, {status: upstream.status});
    return new Response(upstream.body, {headers: {
        'content-type': 'application/x-ndjson; charset=utf-8', 'cache-control': 'no-store'
    }});
}
