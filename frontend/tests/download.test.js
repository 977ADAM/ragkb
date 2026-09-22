import { test } from 'node:test';
import assert from 'node:assert/strict';
import { downloadAttachment } from '../src/lib/download.js';

const DOCUMENT_ID = '11111111-1111-4111-8111-111111111111';
/** @type {{document_id: string, filename: string, url: string, media_type: string, size: number}} */
const ATTACHMENT = {
	document_id: DOCUMENT_ID,
	filename: 'spec.pdf',
	url: `/api/documents/${DOCUMENT_ID}/download`,
	media_type: 'application/pdf',
	size: 10
};

/**
 * @param {string} body
 * @param {{status?: number, headers?: Record<string, string>}} [options]
 * @returns {Response}
 */
function response(body, { status = 200, headers = {} } = {}) {
	return new Response(body, { status, headers });
}

test('downloaded body is saved under the attachment name', async () => {
	/** @type {{blob?: Blob, filename?: string}} */
	const saved = {};
	/** @type {string[]} */
	const calls = [];

	await downloadAttachment(ATTACHMENT, {
		fetchImpl: async (url, init) => {
			calls.push(`${init?.method ?? 'GET'} ${url}`);
			return response('байты файла', {
				headers: { 'content-type': 'application/pdf' }
			});
		},
		saveBlob: (blob, filename) => {
			saved.blob = blob;
			saved.filename = filename;
		}
	});

	assert.deepEqual(calls, [`GET /api/documents/${DOCUMENT_ID}/download`]);
	assert.equal(saved.filename, 'spec.pdf');
	assert.equal(await saved.blob?.text(), 'байты файла');
});

test('revoked file does not save an error body', async () => {
	let saved = false;

	await assert.rejects(
		downloadAttachment(ATTACHMENT, {
			fetchImpl: async () => response('{"detail":"Недоступен"}', { status: 404 }),
			saveBlob: () => {
				saved = true;
			}
		}),
		/недоступен/i
	);

	assert.equal(saved, false);
});

test('rate limit suggests retrying after the given time', async () => {
	await assert.rejects(
		downloadAttachment(ATTACHMENT, {
			fetchImpl: async () =>
				response('{"detail":"Слишком много запросов"}', {
					status: 429,
					headers: { 'retry-after': '30' }
				}),
			saveBlob: () => {}
		}),
		/повторите через 30/i
	);
});

test('rate limit without a header still tells to retry later', async () => {
	await assert.rejects(
		downloadAttachment(ATTACHMENT, {
			fetchImpl: async () => response('{}', { status: 429 }),
			saveBlob: () => {}
		}),
		/повторите позже/i
	);
});

test('other refusals keep the server explanation', async () => {
	await assert.rejects(
		downloadAttachment(ATTACHMENT, {
			fetchImpl: async () => response('{"detail":"Внутренняя ошибка сервера"}', { status: 500 }),
			saveBlob: () => {}
		}),
		/внутренняя ошибка сервера/i
	);
});

test('foreign url is refused without fetching anything', async () => {
	let fetched = false;

	for (const url of [
		'https://evil.test/api/documents/' + DOCUMENT_ID + '/download',
		'/api/admin/documents',
		`/api/documents/${DOCUMENT_ID}/download?x=1`,
		'/api/documents/22222222-2222-4222-8222-222222222222/download'
	]) {
		await assert.rejects(
			downloadAttachment(
				{ ...ATTACHMENT, url },
				{
					fetchImpl: async () => {
						fetched = true;
						return response('данные');
					},
					saveBlob: () => {}
				}
			),
			/некорректная ссылка/i
		);
	}

	assert.equal(fetched, false);
});

test('url must belong to the same document as the attachment', async () => {
	await assert.rejects(
		downloadAttachment(
			{ ...ATTACHMENT, url: '/api/documents/22222222-2222-4222-8222-222222222222/download' },
			{ fetchImpl: async () => response('данные'), saveBlob: () => {} }
		),
		/некорректная ссылка/i
	);
});
