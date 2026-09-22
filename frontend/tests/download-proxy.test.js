import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDownloadLimiter } from '../src/lib/server/download-limiter.js';
import { proxyDownload } from '../src/lib/server/download-proxy.js';

/** @typedef {import('../src/lib/server/download-limiter.js').DownloadLimiter} DownloadLimiter */
/** @typedef {import('../src/lib/server/download-limiter.js').DownloadLimits} DownloadLimits */
/** @typedef {import('../src/lib/server/download-proxy.js').DownloadEvent} DownloadEvent */
/** @typedef {(path: string, init: RequestInit) => Response | Promise<Response>} Upstream */

const DOCUMENT_ID = '11111111-1111-4111-8111-111111111111';
const DOWNLOAD_PATH = `/documents/${DOCUMENT_ID}/download`;

/**
 * @param {Partial<DownloadLimits>} [overrides]
 * @returns {DownloadLimiter}
 */
function limiter(overrides = {}) {
	return createDownloadLimiter({
		ratePerMinute: 10,
		burst: 3,
		maxConcurrent: 2,
		maxKeys: 100,
		now: () => 0,
		...overrides
	});
}

/**
 * Поток upstream с наблюдаемыми чтениями: видно, есть ли обратное давление.
 *
 * @param {Uint8Array[]} chunks
 * @param {() => void} [onPull]
 * @returns {ReadableStream<Uint8Array>}
 */
function body(chunks, onPull) {
	let index = 0;
	return new ReadableStream(
		{
			pull(controller) {
				onPull?.();
				if (index < chunks.length) controller.enqueue(chunks[index++]);
				else controller.close();
			}
		},
		// Нулевая очередь: поток не заполняется сам, чтения видны по счётчику.
		{ highWaterMark: 0 }
	);
}

/**
 * @param {{ method?: string, headers?: Record<string, string>, signal?: AbortSignal }} [options]
 * @returns {Request}
 */
function request({ method = 'GET', headers = {}, signal } = {}) {
	return new Request(`http://bff.test/api/documents/${DOCUMENT_ID}/download`, {
		method,
		headers,
		signal
	});
}

/**
 * Один вызов proxyDownload с подставным upstream и собираемым журналом.
 *
 * @param {{ upstream: Upstream, request?: Request, guard?: DownloadLimiter }} options
 */
function harness({ upstream, request: incoming = request(), guard = limiter() }) {
	/** @type {{ path: string, init: RequestInit }[]} */
	const calls = [];
	/** @type {DownloadEvent[]} */
	const events = [];
	return {
		events,
		calls,
		run: () =>
			proxyDownload({
				request: incoming,
				documentId: DOCUMENT_ID,
				clientAddress: '192.0.2.1',
				requestId: 'req-1',
				limiter: guard,
				upstreamFetch: async (path, init) => {
					calls.push({ path, init });
					return upstream(path, init);
				},
				log: (event) => events.push(event)
			})
	};
}

/**
 * @param {{ calls: { path: string, init: RequestInit }[] }} h
 * @returns {Record<string, string>}
 */
function sentHeaders(h) {
	return /** @type {Record<string, string>} */ (h.calls[0].init.headers ?? {});
}

/**
 * @param {DownloadEvent[]} events
 * @returns {DownloadEvent}
 */
function lastEvent(events) {
	const event = events.at(-1);
	if (!event) throw new Error('журнал пуст');
	return event;
}

/**
 * @param {Response} response
 * @returns {ReadableStreamDefaultReader<Uint8Array>}
 */
function readerOf(response) {
	if (!response.body) throw new Error('у ответа нет тела');
	return response.body.getReader();
}

/**
 * @param {Response} response
 * @returns {Promise<Uint8Array>}
 */
async function readAll(response) {
	const reader = readerOf(response);
	/** @type {Uint8Array[]} */
	const parts = [];
	for (;;) {
		const { value, done } = await reader.read();
		if (done) break;
		parts.push(value);
	}
	return new Uint8Array(parts.flatMap((part) => Array.from(part)));
}

test('rate limit answers 429 without touching upstream', async () => {
	const guard = limiter({ burst: 1 });
	const first = harness({ upstream: () => okResponse(['a']), guard });
	await readAll(await first.run());

	const second = harness({ upstream: () => okResponse(['b']), guard });
	const response = await second.run();

	assert.equal(response.status, 429);
	assert.ok(Number(response.headers.get('retry-after')) >= 1);
	assert.equal(response.headers.get('cache-control'), 'no-store');
	assert.equal(second.calls.length, 0, 'отказ не должен ходить в backend');
	assert.equal((await response.json()).detail.includes('Повторите'), true);
	assert.deepEqual(
		second.events.map((event) => event.result),
		['refused']
	);
});

test('streams body, releases the slot and logs start and completion', async () => {
	const guard = limiter({ maxConcurrent: 1 });
	const h = harness({
		upstream: () => okResponse(['первая ', 'часть']),
		guard
	});

	const response = await h.run();
	assert.equal(response.status, 200);
	assert.equal(await new TextDecoder().decode(await readAll(response)), 'первая часть');

	// Слот свободен: следующий запрос проходит.
	assert.equal(guard.acquire('192.0.2.1').ok, true);
	assert.deepEqual(
		h.events.map((event) => [event.result, event.bytes]),
		[
			['started', 0],
			['completed', 23]
		]
	);
	assert.equal(h.events[0].request_id, 'req-1');
	assert.equal(h.events[0].ip, '192.0.2.1');
	assert.equal(h.events[0].document_id, DOCUMENT_ID);
});

test('only allowed headers travel to the client, and only the request id upstream', async () => {
	const h = harness({
		request: request({ headers: { cookie: 'session=secret', 'x-forwarded-for': '203.0.113.9' } }),
		upstream: () =>
			new Response('тело', {
				status: 200,
				headers: {
					'content-type': 'application/pdf',
					'content-disposition': 'attachment; filename="spec.pdf"',
					'content-length': '8',
					'set-cookie': 'tracking=1',
					'x-internal': 'internal-only'
				}
			})
	});

	const response = await h.run();

	assert.equal(response.headers.get('content-type'), 'application/pdf');
	assert.equal(response.headers.get('content-disposition'), 'attachment; filename="spec.pdf"');
	assert.equal(response.headers.get('content-length'), '8');
	assert.equal(response.headers.get('cache-control'), 'no-store');
	assert.equal(response.headers.get('set-cookie'), null);
	assert.equal(response.headers.get('x-internal'), null);
	assert.equal(response.headers.get('x-request-id'), 'req-1');

	const sent = sentHeaders(h);
	assert.equal(sent['x-request-id'], 'req-1');
	assert.equal(sent.cookie, undefined);
	assert.equal(sent['x-forwarded-for'], undefined);
	assert.equal(h.calls[0].path, DOWNLOAD_PATH);
	await readAll(response);
});

test('client address comes from the connection, not from the forwarded header', async () => {
	const guard = limiter({ burst: 1 });
	const first = harness({
		guard,
		request: request({ headers: { 'x-forwarded-for': '203.0.113.9' } }),
		upstream: () => okResponse(['a'])
	});
	await readAll(await first.run());

	const second = harness({
		guard,
		request: request({ headers: { 'x-forwarded-for': '203.0.113.10' } }),
		upstream: () => okResponse(['b'])
	});
	const response = await second.run();

	assert.equal(response.status, 429, 'подложенный заголовок не меняет ключ лимита');
	assert.equal(second.calls.length, 0, 'отказ не должен ходить в backend');
});

test('HEAD returns headers only and frees the slot at once', async () => {
	const guard = limiter({ maxConcurrent: 1 });
	const h = harness({ upstream: () => okResponse([], { 'content-length': '8' }), guard, request: request({ method: 'HEAD' }) });

	const response = await h.run();
	const held = guard.acquire('192.0.2.1');

	assert.equal(response.status, 200);
	assert.equal(response.body, null);
	assert.equal(response.headers.get('content-length'), '8');
	assert.equal(held.ok, true, 'слот должен освободиться сразу после заголовков');
	assert.deepEqual(
		h.events.map((event) => event.method),
		['HEAD']
	);
	assert.ok(h.events.some((event) => event.result === 'completed'));
});

test('upstream refusal keeps the protocol and frees the slot', async () => {
	const guard = limiter({ maxConcurrent: 1 });
	const h = harness({
		upstream: () => new Response(JSON.stringify({ detail: 'Документ недоступен' }), { status: 404 }),
		guard
	});

	const response = await h.run();

	assert.equal(response.status, 404);
	assert.equal((await response.json()).detail, 'Документ недоступен');
	assert.equal(response.headers.get('cache-control'), 'no-store');
	assert.equal(guard.acquire('192.0.2.1').ok, true);
	assert.equal(lastEvent(h.events).result, 'refused');
	assert.equal(lastEvent(h.events).status, 404);
});

test('network failure before a response is a 502 and frees the slot', async () => {
	const guard = limiter({ maxConcurrent: 1 });
	const h = harness({
		upstream: () => {
			throw new Error('соединение отклонено');
		},
		guard
	});

	const response = await h.run();

	assert.equal(response.status, 502);
	assert.equal(response.headers.get('cache-control'), 'no-store');
	assert.equal((await response.json()).detail.includes('соединение отклонено'), true);
	assert.equal(guard.acquire('192.0.2.1').ok, true);
	assert.equal(lastEvent(h.events).result, 'failed');
});

test('cancelling the client stream aborts upstream and frees the slot', async () => {
	const guard = limiter({ maxConcurrent: 1 });
	let upstreamCancelled = false;
	const h = harness({
		guard,
		upstream: () =>
			new Response(
				new ReadableStream({
					start(controller) {
						controller.enqueue(new TextEncoder().encode('первая порция'));
					},
					cancel() {
						upstreamCancelled = true;
					}
				}),
				{ status: 200 }
			)
	});

	const response = await h.run();
	const reader = readerOf(response);
	await reader.read();
	await reader.cancel('клиент ушёл');

	assert.equal(upstreamCancelled, true);
	assert.equal(guard.acquire('192.0.2.1').ok, true);
	assert.equal(lastEvent(h.events).result, 'aborted');
});

test('aborting while upstream is not answering frees the slot', async () => {
	const controller = new AbortController();
	const guard = limiter({ maxConcurrent: 1 });
	const h = harness({
		guard,
		request: request({ signal: controller.signal }),
		upstream: (path, init) =>
			new Promise((resolve, reject) => {
				init.signal?.addEventListener('abort', () => reject(new Error('отменено')), {
					once: true
				});
			})
	});

	const pending = h.run();
	controller.abort('клиент ушёл');
	const response = await pending;

	assert.equal(response.status, 502);
	assert.equal(lastEvent(h.events).result, 'aborted');
	assert.equal(guard.acquire('192.0.2.1').ok, true, 'слот должен освободиться');
});

test('aborting the request stops the upstream transfer', async () => {
	const controller = new AbortController();
	let upstreamCancelled = false;
	const guard = limiter({ maxConcurrent: 1 });
	const h = harness({
		guard,
		request: request({ signal: controller.signal }),
		upstream: () =>
			new Response(
				new ReadableStream({
					start(controller) {
						controller.enqueue(new TextEncoder().encode('порция'));
					},
					pull: () => new Promise(() => {}),
					cancel() {
						upstreamCancelled = true;
					}
				}),
				{ status: 200 }
			)
	});

	const response = await h.run();
	const reader = readerOf(response);
	await reader.read();
	controller.abort('клиент ушёл');
	await new Promise((resolve) => setTimeout(resolve, 0));

	assert.equal(upstreamCancelled, true, 'чтение upstream должно прекратиться');
	assert.equal(lastEvent(h.events).result, 'aborted');
	await reader.cancel().catch(() => {});
	assert.equal(guard.acquire('192.0.2.1').ok, true);
});

test('slow reader keeps backpressure: the file is not read ahead', async () => {
	let pulls = 0;
	const h = harness({
		upstream: () =>
			new Response(
				body(
					[new Uint8Array([1]), new Uint8Array([2]), new Uint8Array([3])],
					() => (pulls += 1)
				),
				{ status: 200 }
			)
	});

	const response = await h.run();
	assert.ok(pulls <= 1, `из upstream прочитано вперёд: ${pulls} порций`);

	const reader = readerOf(response);
	await reader.read();
	assert.ok(pulls < 3, `файл прочитан целиком мимо клиента: ${pulls} порций`);
	await reader.cancel();
});

test('completion releases the slot exactly once', async () => {
	const guard = limiter({ maxConcurrent: 2 });
	const h = harness({ upstream: () => okResponse(['a']), guard });
	const response = await h.run();
	await readAll(response);

	// Повторная отмена уже завершённого потока ничего не ломает.
	await response.body?.cancel().catch(() => {});

	const slots = [guard.acquire('192.0.2.1'), guard.acquire('192.0.2.1'), guard.acquire('192.0.2.1')];
	assert.deepEqual(
		slots.map((slot) => slot.ok),
		[true, true, false],
		'слот освобождён ровно один раз'
	);
});

/**
 * @param {string[]} chunks
 * @param {Record<string, string>} [headers]
 * @returns {Response}
 */
function okResponse(chunks, headers = {}) {
	return new Response(
		body(chunks.map((chunk) => new TextEncoder().encode(chunk))),
		{ status: 200, headers: { 'content-type': 'application/pdf', ...headers } }
	);
}
