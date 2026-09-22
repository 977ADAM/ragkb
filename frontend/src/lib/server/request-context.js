/**
 * Контекст внешнего запроса: метка запроса и адрес клиента.
 *
 * Метку запроса создаёт BFF: она связывает строки журнала frontend и backend.
 * Входящий заголовок клиента доверенным не считается — иначе посетитель
 * подписывал бы чужие записи своим идентификатором.
 *
 * Адрес берётся только у соединения (`getClientAddress`). Заголовки вида
 * `X-Forwarded-For` здесь не читаются вовсе: их подставляет кто угодно, а
 * ограничитель скачиваний считает по этому значению. За доверенным прокси
 * адрес даёт сам адаптер, если задан `ADDRESS_HEADER` и прямой доступ к BFF
 * закрыт.
 */

/** Адрес, когда соединение не сообщило его: общий ключ вместо обхода лимита. */
export const UNKNOWN_ADDRESS = 'unknown';

/**
 * @returns {string} новая метка запроса
 */
export function createRequestId() {
	const uuid = globalThis.crypto?.randomUUID?.();
	if (typeof uuid === 'string' && uuid) return uuid;
	return `req-${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`;
}

/**
 * @param {{ getClientAddress?: () => string }} event
 * @returns {string}
 */
export function clientAddress(event) {
	try {
		const address = event.getClientAddress?.();
		return typeof address === 'string' && address ? address : UNKNOWN_ADDRESS;
	} catch {
		// Адаптер не смог определить адрес: общий ключ честнее, чем отсутствие
		// ограничения.
		return UNKNOWN_ADDRESS;
	}
}
