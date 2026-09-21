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
