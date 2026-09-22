/**
 * Потоковая выдача оригинала через BFF.
 *
 * Тело не буферизуется: порции читаются по требованию потребителя, поэтому
 * медленный клиент создаёт обратное давление, а не растущую память. Слот
 * ограничителя освобождается ровно один раз — при завершении, отмене или
 * ошибке, и всегда до того, как ответ уйдёт дальше.
 *
 * Проверка лимита идёт до обращения к backend: отклонённый запрос не должен
 * стоить ни файла, ни его чтения.
 *
 * Журнал ведёт вызывающая сторона: сюда передаётся `log`, а формат строки
 * собирает `downloadLogLine`. События различают отказ, начало передачи,
 * завершение и обрыв — окончание передачи не доказывает, что файл сохранён у
 * клиента.
 */

/** Заголовки, которые видит клиент: остальные заголовки backend не пробрасываются. */
const ALLOWED_HEADERS = ['content-type', 'content-disposition', 'content-length'];

const NO_STORE = 'no-store';

const RATE_LIMIT_DETAIL = 'Слишком много запросов на скачивание. Повторите позже.';

/**
 * @typedef {object} DownloadEvent
 * @property {string} result
 * @property {string} ip
 * @property {string} request_id
 * @property {string} document_id
 * @property {string} method
 * @property {number} [status]
 * @property {number} [bytes]
 * @property {string} [reason]
 * @property {number} [duration_ms]
 *
 * @typedef {object} ProxyDownloadOptions
 * @property {Request} request
 * @property {string} documentId
 * @property {string} clientAddress
 * @property {string} requestId
 * @property {{ acquire: (key: string) => { ok: true, release: () => void } | { ok: false, retryAfter: number } }} limiter
 * @property {(path: string, init: RequestInit) => Promise<Response>} upstreamFetch
 * @property {(event: DownloadEvent) => void} [log]
 */

/**
 * @param {ProxyDownloadOptions} options
 * @returns {Promise<Response>}
 */
export async function proxyDownload({
	request,
	documentId,
	clientAddress,
	requestId,
	limiter,
	upstreamFetch,
	log
}) {
	const startedAt = Date.now();
	const method = request.method === 'HEAD' ? 'HEAD' : 'GET';

	/**
	 * @param {string} result
	 * @param {Partial<DownloadEvent>} [extra]
	 */
	const emit = (result, extra = {}) =>
		log?.({
			result,
			ip: clientAddress,
			request_id: requestId,
			document_id: documentId,
			method,
			...extra
		});

	const slot = limiter.acquire(clientAddress);
	if (!slot.ok) {
		emit('refused', { reason: 'limit', status: 429 });
		return refusal(requestId, 429, RATE_LIMIT_DETAIL, slot.retryAfter);
	}

	let finished = false;
	// Состояние живёт в объекте: значение меняют и обработчики потока, и
	// сигнал отмены, а сравнение с ним должно видеть актуальное значение, а не
	// сужение типа по присваиванию.
	const transfer = { result: /** @type {'aborted' | 'failed' | 'completed'} */ ('failed') };

	/**
	 * @param {string} result
	 * @param {Partial<DownloadEvent>} [extra]
	 */
	const finish = (result, extra = {}) => {
		if (finished) return;
		finished = true;
		request.signal?.removeEventListener?.('abort', onAbort);
		slot.release();
		emit(result, { duration_ms: Date.now() - startedAt, ...extra });
	};

	// Отмена запроса клиентом останавливает чтение upstream: соединение к
	// backend не должно жить дольше, чем нужно посетителю.
	const upstreamAbort = new AbortController();
	/** @type {ReadableStreamDefaultReader<Uint8Array> | null} */
	let activeReader = null;
	const onAbort = () => {
		transfer.result = 'aborted';
		const reason = request.signal?.reason ?? 'клиент отменил запрос';
		upstreamAbort.abort(reason);
		activeReader?.cancel(reason).catch(() => {});
	};
	if (request.signal?.aborted) onAbort();
	else request.signal?.addEventListener?.('abort', onAbort, { once: true });

	let upstream;
	try {
		upstream = await upstreamFetch(`/documents/${encodeURIComponent(documentId)}/download`, {
			method,
			headers: { 'x-request-id': requestId },
			signal: upstreamAbort.signal
		});
	} catch (error) {
		finish(transfer.result === 'aborted' ? 'aborted' : 'failed', {
			reason: 'upstream_unreachable'
		});
		const reason = error instanceof Error ? error.message : String(error);
		return refusal(requestId, 502, `Бэкенд недоступен: ${reason}`, null);
	}

	if (!upstream.ok) {
		const detail = await failureDetail(upstream);
		await upstream.body?.cancel?.().catch(() => {});
		finish('refused', { status: upstream.status });
		return refusal(requestId, upstream.status, detail, retryAfterOf(upstream));
	}

	const headers = clientHeaders(upstream.headers, requestId);
	if (method === 'HEAD' || upstream.body === null) {
		// Слот освобождается сразу: тела нет, держать передачу нечем.
		finish('completed', { status: upstream.status, bytes: 0 });
		return new Response(null, { status: upstream.status, headers });
	}

	const reader = upstream.body.getReader();
	activeReader = reader;
	let bytes = 0;
	const body = new ReadableStream({
		async pull(controller) {
			try {
				const chunk = await reader.read();
				if (chunk.done) {
					// После отмены чтение закрывается, а не обрывается — но
					// передача всё равно прервана, и в журнале это обрыв.
					const aborted = transfer.result === 'aborted';
					finish(aborted ? 'aborted' : 'completed', {
						status: upstream.status,
						bytes,
						...(aborted ? { reason: 'client_abort' } : {})
					});
					controller.close();
					return;
				}
				bytes += chunk.value.byteLength;
				controller.enqueue(chunk.value);
			} catch (error) {
				const aborted = transfer.result === 'aborted';
				finish(aborted ? 'aborted' : 'failed', {
					status: upstream.status,
					bytes,
					reason: aborted ? 'client_abort' : 'stream_error'
				});
				controller.error(error);
			}
		},
		async cancel(reason) {
			transfer.result = 'aborted';
			upstreamAbort.abort(reason);
			try {
				await reader.cancel(reason);
			} finally {
				finish('aborted', { status: upstream.status, bytes, reason: 'client_cancel' });
			}
		}
	});

	emit('started', { status: upstream.status, bytes: 0 });
	return new Response(body, { status: upstream.status, headers });
}

/**
 * Строка журнала: те же поля, что и у событий backend, чтобы записи можно было
 * сопоставить по request_id.
 *
 * @param {DownloadEvent} event
 * @returns {string}
 */
export function downloadLogLine(event) {
	const fields = [
		`result=${event.result}`,
		`method=${event.method}`,
		`ip=${event.ip}`,
		`request_id=${event.request_id}`,
		`document_id=${event.document_id}`,
		event.status === undefined ? null : `status=${event.status}`,
		event.bytes === undefined ? null : `bytes=${event.bytes}`,
		event.reason === undefined ? null : `reason=${event.reason}`,
		event.duration_ms === undefined ? null : `duration_ms=${event.duration_ms}`
	];
	return `выдача оригинала: event=download ${fields.filter(Boolean).join(' ')}`;
}

/**
 * @param {string} requestId
 * @param {number} status
 * @param {string} detail
 * @param {number | null} retryAfter секунды
 * @returns {Response}
 */
function refusal(requestId, status, detail, retryAfter) {
	/** @type {Record<string, string>} */
	const headers = {
		'content-type': 'application/json; charset=utf-8',
		'cache-control': NO_STORE,
		'x-request-id': requestId
	};
	if (retryAfter) headers['retry-after'] = String(Math.max(1, Math.ceil(retryAfter)));
	return new Response(JSON.stringify({ detail }), { status, headers });
}

/**
 * @param {Headers} source
 * @param {string} requestId
 * @returns {Headers}
 */
function clientHeaders(source, requestId) {
	const headers = new Headers();
	for (const name of ALLOWED_HEADERS) {
		const value = source.get(name);
		if (value !== null) headers.set(name, value);
	}
	headers.set('cache-control', NO_STORE);
	headers.set('x-request-id', requestId);
	return headers;
}

/**
 * @param {Response} upstream
 * @returns {Promise<string>}
 */
async function failureDetail(upstream) {
	try {
		const body = await upstream.json();
		if (typeof body?.detail === 'string' && body.detail) return body.detail;
	} catch {
		/* тело не JSON — обойдёмся статусом */
	}
	return `База знаний недоступна (${upstream.status})`;
}

/**
 * @param {Response} upstream
 * @returns {number | null}
 */
function retryAfterOf(upstream) {
	const value = Number(upstream.headers.get('retry-after'));
	return Number.isFinite(value) && value > 0 ? value : null;
}
