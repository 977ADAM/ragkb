/**
 * @param {ReadableStream<Uint8Array>} body
 * @param {(event: any) => void} accept
 */
export async function readAnswer(body, accept) {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let terminated = false;
    /** @param {string} line */
    function consume(line) {
        if (!line.trim() || terminated) return;
        const event = JSON.parse(line);
        accept(event);
        if (event.type === 'done') terminated = true;
    }
    try {
        for (;;) {
            const {value, done} = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, {stream: true});
            const lines = buffer.split('\n');
            buffer = lines.pop() ?? '';
            for (const line of lines) consume(line);
        }
        consume(buffer + decoder.decode());
        if (!terminated) throw new Error('Поток оборвался, ответ неполный');
    } finally {
        reader.releaseLock();
    }
}
