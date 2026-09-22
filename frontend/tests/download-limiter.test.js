import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
	createDownloadLimiter,
	readLimiterConfig
} from '../src/lib/server/download-limiter.js';

/** @typedef {import('../src/lib/server/download-limiter.js').DownloadLimiter} DownloadLimiter */
/** @typedef {import('../src/lib/server/download-limiter.js').DownloadLimits} DownloadLimits */

/**
 * Управляемое время: лимиты проверяются без ожидания реальных секунд.
 *
 * @param {number} [start]
 * @returns {{ now: () => number, advance: (ms: number) => number }}
 */
function clock(start = 0) {
	let value = start;
	return {
		now: () => value,
		advance: (ms) => (value += ms)
	};
}

/**
 * @param {Partial<DownloadLimits>} [overrides]
 * @param {() => number} [now]
 * @returns {DownloadLimiter}
 */
function limiter(overrides = {}, now = () => 0) {
	return createDownloadLimiter({
		ratePerMinute: 10,
		burst: 3,
		maxConcurrent: 2,
		maxKeys: 100,
		now,
		...overrides
	});
}

/**
 * Берёт слот или роняет тест: так дальше видно `release` без проверки `ok`.
 *
 * @param {DownloadLimiter} guard
 * @param {string} key
 * @returns {{ release: () => void }}
 */
function take(guard, key) {
	const slot = guard.acquire(key);
	assert.equal(slot.ok, true, `слот не выдан: ${key}`);
	if (!slot.ok) throw new Error('слот не выдан');
	return slot;
}

test('cancel releases a concurrency slot', () => {
	const guard = limiter();
	const a = take(guard, '192.0.2.1');
	const b = take(guard, '192.0.2.1');
	assert.equal(guard.acquire('192.0.2.1').ok, false);
	a.release();
	a.release();
	assert.equal(guard.acquire('192.0.2.1').ok, true);
	b.release();
});

test('burst tokens are spent and refilled by the minute rate', () => {
	const time = clock();
	// Параллелизм здесь не ограничивает: проверяется именно частота.
	const guard = limiter({ maxConcurrent: 10 }, time.now);
	assert.equal(guard.acquire('192.0.2.1').ok, true);
	assert.equal(guard.acquire('192.0.2.1').ok, true);
	assert.equal(guard.acquire('192.0.2.1').ok, true);

	const refused = guard.acquire('192.0.2.1');
	assert.equal(refused.ok, false);
	assert.ok(refused.ok === false && refused.retryAfter >= 1, 'нужен Retry-After');

	// 10 в минуту — это один токен за 6 секунд.
	time.advance(6000);
	assert.equal(guard.acquire('192.0.2.1').ok, true);
});

test('refused requests spend neither tokens nor transfer slots', () => {
	const time = clock();
	const guard = limiter({ burst: 2, maxConcurrent: 1 }, time.now);
	const first = take(guard, '192.0.2.1');

	// Отказ по параллелизму не тратит токен: их осталось два из двух.
	for (let i = 0; i < 5; i += 1) assert.equal(guard.acquire('192.0.2.1').ok, false);
	first.release();

	const second = take(guard, '192.0.2.1');
	second.release();

	// Теперь токены кончились: отказ по частоте не должен занимать слот.
	assert.equal(guard.acquire('192.0.2.1').ok, false);
	time.advance(6000); // 10 в минуту — это один токен за 6 секунд
	const third = take(guard, '192.0.2.1');
	third.release();
});

test('concurrency limit rejects before the rate limit and frees on release', () => {
	const guard = limiter({ burst: 10, maxConcurrent: 2 });
	const a = take(guard, '192.0.2.1');
	const b = take(guard, '192.0.2.1');
	assert.equal(guard.acquire('192.0.2.1').ok, false);

	a.release();
	const c = take(guard, '192.0.2.1');
	// Потрачено три токена из десяти: отказы по параллелизму их не съели.
	assert.equal(guard.acquire('192.0.2.1').ok, false, 'слот всё ещё занят');
	b.release();
	c.release();
});

test('keys are independent', () => {
	const guard = limiter({ burst: 1, maxConcurrent: 1 });
	const first = take(guard, '192.0.2.1');
	assert.equal(guard.acquire('192.0.2.1').ok, false);
	assert.equal(guard.acquire('192.0.2.2').ok, true);
	first.release();
});

test('full storage rejects a new key without resetting existing ones', () => {
	const time = clock();
	const guard = limiter({ burst: 1, maxConcurrent: 1, maxKeys: 2 }, time.now);
	const kept = take(guard, '192.0.2.1');
	take(guard, '192.0.2.2').release();

	const stranger = guard.acquire('192.0.2.3');
	assert.equal(stranger.ok, false);
	assert.ok(stranger.ok === false && stranger.retryAfter >= 1);

	// Лимит существующего ключа не сброшен: второй запрос всё ещё отклоняется.
	assert.equal(guard.acquire('192.0.2.1').ok, false);
	kept.release();
});

test('idle refilled keys are pruned so storage stays bounded', () => {
	const time = clock();
	const guard = limiter({ burst: 1, maxConcurrent: 1, maxKeys: 2 }, time.now);
	take(guard, '192.0.2.1').release();
	take(guard, '192.0.2.2').release();
	assert.equal(guard.size(), 2);

	// Через десять минут простоя записи бесполезны: токены и так полны.
	time.advance(10 * 60 * 1000 + 1);
	take(guard, '192.0.2.3').release();
	assert.ok(guard.size() <= 2, `хранилище не ограничено: ${guard.size()}`);
});

test('configuration is parsed from the environment and rejected when broken', () => {
	assert.deepEqual(readLimiterConfig({}), {
		ratePerMinute: 10,
		burst: 3,
		maxConcurrent: 2,
		maxKeys: 10000
	});
	assert.deepEqual(
		readLimiterConfig({
			RAGKB_DOWNLOAD_RATE_PER_MINUTE: '20',
			RAGKB_DOWNLOAD_BURST: '5',
			RAGKB_DOWNLOAD_MAX_CONCURRENT: '1',
			RAGKB_DOWNLOAD_MAX_KEYS: '50'
		}),
		{ ratePerMinute: 20, burst: 5, maxConcurrent: 1, maxKeys: 50 }
	);

	for (const broken of [
		{ RAGKB_DOWNLOAD_RATE_PER_MINUTE: 'ноль' },
		{ RAGKB_DOWNLOAD_BURST: '0' },
		{ RAGKB_DOWNLOAD_MAX_CONCURRENT: '-1' },
		{ RAGKB_DOWNLOAD_MAX_KEYS: '' }
	]) {
		assert.throws(() => readLimiterConfig(broken), /RAGKB_DOWNLOAD_/, JSON.stringify(broken));
	}
});
