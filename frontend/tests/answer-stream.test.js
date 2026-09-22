import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readAnswer } from '../src/lib/answer-stream.js';

/** @param {Uint8Array[]} chunks */
function stream(chunks) {
    return new ReadableStream({start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk);
        controller.close();
    }});
}

test('UTF-8 chunks and final done without newline', async () => {
    const bytes = new TextEncoder().encode('{"type":"token","text":"Отпуск"}\n{"type":"done","sources":[]}');
    /** @type {any[]} */
    const events = [];
    await readAnswer(stream(Array.from(bytes, byte => Uint8Array.of(byte))), event => events.push(event));
    assert.deepEqual(events, [{type:'token',text:'Отпуск'}, {type:'done',sources:[]}]);
});

test('missing terminal event reports incomplete answer', async () => {
    const bytes = new TextEncoder().encode('{"type":"token","text":"часть"}\n');
    await assert.rejects(readAnswer(stream([bytes]), () => {}), /Поток оборвался/);
});

test('done with attachments is delivered as is', async () => {
	const documentId = '11111111-1111-4111-8111-111111111111';
	const payload = {
		type: 'done',
		sources: [],
		warnings: [],
		elapsed_sec: 0.5,
		model: 'test-model',
		truncated: false,
		attachments: [
			{
				document_id: documentId,
				filename: 'spec.pdf',
				url: `/api/documents/${documentId}/download`,
				media_type: 'application/pdf',
				size: 10
			}
		]
	};
	/** @type {any[]} */
	const events = [];
	const bytes = new TextEncoder().encode(
		`{"type":"token","text":"готово"}\n${JSON.stringify(payload)}`
	);

	await readAnswer(stream([bytes]), (event) => events.push(event));

	assert.equal(events.at(-1).attachments.length, 1);
	assert.equal(events.at(-1).attachments[0].filename, 'spec.pdf');
});

test('old done without attachments is still accepted', async () => {
	// Ответ прежнего сервера: поля вложений нет — карточек просто не будет.
	/** @type {any[]} */
	const events = [];
	const bytes = new TextEncoder().encode('{"type":"done","sources":[],"warnings":[]}');

	await readAnswer(stream([bytes]), (event) => events.push(event));

	assert.equal(events.at(-1).attachments, undefined);
	assert.deepEqual(events.at(-1).attachments ?? [], []);
});
