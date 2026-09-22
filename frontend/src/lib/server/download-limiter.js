/**
 * Ограничение скачиваний оригинала: частота и одновременные передачи на адрес.
 *
 * Ограничитель живёт в процессе frontend и считает по адресу клиента, а не по
 * учётной записи: аккаунтов в приложении нет, и адрес означает источник
 * запроса, а не личность. Несколько посетителей за общим NAT попадают в один
 * счётчик — это осознанное свойство, а не ошибка; при нескольких репликах
 * frontend нужен общий ограничитель (см. README).
 *
 * Модуль намеренно не знает ни про SvelteKit, ни про сеть: время и значения
 * приходят снаружи, поэтому лимиты проверяются без ожидания реальных секунд.
 */

const MINUTE_MS = 60_000;

/** Простой без обращений: полностью восстановленная запись бесполезна. */
const IDLE_MS = 10 * 60 * 1000;

/** Сколько записей просматривается на один запрос: работа ограничена. */
const PRUNE_PER_ACQUIRE = 64;

/** Подсказка для отказа «хранилище заполнено», секунды. */
const FULL_STORAGE_RETRY_AFTER = 60;

/** Подсказка для отказа по одновременным передачам, секунды. */
const BUSY_RETRY_AFTER = 1;

export const DEFAULT_DOWNLOAD_LIMITS = {
	ratePerMinute: 10,
	burst: 3,
	maxConcurrent: 2,
	maxKeys: 10000
};

const ENV_KEY = {
	ratePerMinute: 'RAGKB_DOWNLOAD_RATE_PER_MINUTE',
	burst: 'RAGKB_DOWNLOAD_BURST',
	maxConcurrent: 'RAGKB_DOWNLOAD_MAX_CONCURRENT',
	maxKeys: 'RAGKB_DOWNLOAD_MAX_KEYS'
};

/**
 * @typedef {object} DownloadLimits
 * @property {number} ratePerMinute
 * @property {number} burst
 * @property {number} maxConcurrent
 * @property {number} maxKeys
 *
 * @typedef {{ ok: true, release: () => void } | { ok: false, retryAfter: number }} AcquireResult
 *
 * @typedef {object} DownloadLimiter
 * @property {(key: string) => AcquireResult} acquire
 * @property {() => number} size
 */

/**
 * Читает настройки лимитов из окружения. Пустое значение — ошибка
 * конфигурации: молча подставить умолчание значило бы выдать незаданный
 * лимит за настроенный.
 *
 * @param {Record<string, string | undefined>} [env]
 * @returns {DownloadLimits}
 */
export function readLimiterConfig(env = {}) {
	/** @type {DownloadLimits} */
	const limits = { ...DEFAULT_DOWNLOAD_LIMITS };
	for (const [name, key] of Object.entries(ENV_KEY)) {
		const raw = env[key];
		if (raw === undefined || raw === null) continue;
		const value = Number(raw);
		if (!Number.isInteger(value) || value < 1) {
			throw new Error(`${key}: ожидается целое число больше нуля, получено «${raw}»`);
		}
		// @ts-expect-error ключи ENV_KEY совпадают с полями DownloadLimits
		limits[name] = value;
	}
	return limits;
}

/**
 * @param {DownloadLimits & { now?: () => number }} options
 * @returns {DownloadLimiter}
 */
export function createDownloadLimiter(options) {
	const ratePerMinute = positive(options.ratePerMinute, 'ratePerMinute');
	const burst = positive(options.burst, 'burst');
	const maxConcurrent = positive(options.maxConcurrent, 'maxConcurrent');
	const maxKeys = positive(options.maxKeys, 'maxKeys');
	const now = options.now ?? Date.now;
	const refillPerMs = ratePerMinute / MINUTE_MS;

	/** @type {Map<string, { tokens: number, refilledAt: number, active: number, lastSeen: number }>} */
	const keys = new Map();

	/** Текущее место обхода: продолжается между вызовами, а не начинается заново. */
	let sweep = keys.entries();

	/**
	 * Доливает токены по прошедшему времени.
	 * @param {{ tokens: number, refilledAt: number }} state
	 * @param {number} at
	 */
	function refill(state, at) {
		const elapsed = Math.max(0, at - state.refilledAt);
		if (elapsed > 0) {
			state.tokens = Math.min(burst, state.tokens + elapsed * refillPerMs);
			state.refilledAt = at;
		}
	}

	/**
	 * Убирает бесполезные записи: без активных передач, полностью
	 * восстановленные и простаивающие дольше десяти минут. Просматривается не
	 * больше PRUNE_PER_ACQUIRE записей, чтобы запрос не зависел от размера
	 * хранилища.
	 *
	 * Обход продолжается с того места, где остановился прошлый: иначе при
	 * первых занятых записях просроченные дальше не проверялись бы никогда.
	 * Активные передачи не вытесняются, лимиты существующих адресов не
	 * сбрасываются — удаляется только то, что уже полностью восстановилось.
	 *
	 * @param {number} at
	 */
	function prune(at) {
		let checked = 0;
		while (checked < PRUNE_PER_ACQUIRE) {
			const step = sweep.next();
			if (step.done) {
				// Круг пройден: следующий вызов начнёт его заново.
				sweep = keys.entries();
				return;
			}
			checked += 1;
			const [key, state] = step.value;
			if (state.active > 0) continue;
			refill(state, at);
			if (at - state.lastSeen >= IDLE_MS && state.tokens >= burst - 1e-9) keys.delete(key);
		}
	}

	/**
	 * @param {string} key
	 * @returns {AcquireResult}
	 */
	function acquire(key) {
		const at = now();
		prune(at);

		let state = keys.get(key);
		if (state === undefined) {
			if (keys.size >= maxKeys) {
				// Новый ключ не вытесняет существующие: иначе один посетитель
				// сбрасывал бы лимиты остальных, просто меняя адрес.
				return { ok: false, retryAfter: FULL_STORAGE_RETRY_AFTER };
			}
			state = { tokens: burst, refilledAt: at, active: 0, lastSeen: at };
			keys.set(key, state);
		}
		refill(state, at);
		state.lastSeen = at;

		if (state.tokens < 1) {
			// Отказ по частоте: токен не списывается, передача не начинается.
			const waitMs = (1 - state.tokens) / refillPerMs;
			return { ok: false, retryAfter: Math.max(1, Math.ceil(waitMs / 1000)) };
		}
		if (state.active >= maxConcurrent) {
			// Отказ по параллелизму: токен тоже остаётся целым.
			return { ok: false, retryAfter: BUSY_RETRY_AFTER };
		}

		state.tokens -= 1;
		state.active += 1;
		let released = false;
		return {
			ok: true,
			release: () => {
				if (released) return;
				released = true;
				state.active -= 1;
				state.lastSeen = now();
			}
		};
	}

	return {
		acquire,
		size: () => keys.size
	};
}

/**
 * @param {number} value
 * @param {string} name
 * @returns {number}
 */
function positive(value, name) {
	if (!Number.isInteger(value) || value < 1) {
		throw new Error(`${name}: ожидается целое число больше нуля, получено «${value}»`);
	}
	return value;
}
