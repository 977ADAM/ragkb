/**
 * Скачивание оригинала по карточке вложения.
 *
 * Адрес берётся только из самой карточки и проверяется: это должен быть
 * собственный путь BFF `/api/documents/<id>/download`, и идентификатор в пути
 * обязан совпадать с идентификатором вложения. Произвольный адрес из
 * неизвестных данных не скачивается — иначе карточка стала бы способом увести
 * браузер куда угодно.
 *
 * Ошибка не сохраняет тело ответа: отказ — это JSON с объяснением, а не файл.
 */

const DOWNLOAD_URL = /^\/api\/documents\/([0-9a-fA-F-]{36})\/download$/;

/**
 * @typedef {{document_id: string, filename: string, url: string,
 *   media_type: string, size: number}} Attachment
 *
 * @typedef {{fetchImpl?: typeof fetch, saveBlob?: (blob: Blob, filename: string) => void}} DownloadOptions
 */

/**
 * @param {Attachment} attachment
 * @param {DownloadOptions} [options]
 * @returns {Promise<void>}
 */
export async function downloadAttachment(attachment, options = {}) {
	const { fetchImpl = fetch, saveBlob = saveBlobAsFile } = options;
	const url = downloadUrl(attachment);

	const response = await fetchImpl(url, { method: 'GET' });
	if (!response.ok) {
		throw new Error(await refusalText(response));
	}
	const blob = await response.blob();
	saveBlob(blob, attachment.filename || 'document');
}

/**
 * Проверяет адрес карточки и возвращает его.
 *
 * @param {Attachment} attachment
 * @returns {string}
 */
export function downloadUrl(attachment) {
	const url = String(attachment?.url ?? '');
	const documentId = String(attachment?.document_id ?? '');
	const match = DOWNLOAD_URL.exec(url);
	if (!documentId || !match || match[1] !== documentId) {
		throw new Error('Некорректная ссылка на файл');
	}
	return url;
}

/**
 * Понятный текст отказа: 404 и 429 объясняются действием, остальное — ответом
 * сервера, если он его дал.
 *
 * @param {Response} response
 * @returns {Promise<string>}
 */
async function refusalText(response) {
	if (response.status === 404) return 'Файл больше недоступен';
	if (response.status === 429) {
		const retryAfter = Number(response.headers.get('retry-after'));
		return Number.isFinite(retryAfter) && retryAfter > 0
			? `Слишком много запросов на скачивание. Повторите через ${retryAfter} с`
			: 'Слишком много запросов на скачивание. Повторите позже';
	}
	const detail = await detailOf(response);
	return detail || `Не удалось скачать файл (${response.status})`;
}

/**
 * @param {Response} response
 * @returns {Promise<string>}
 */
async function detailOf(response) {
	try {
		const body = await response.json();
		return typeof body?.detail === 'string' ? body.detail : '';
	} catch {
		// Тело не JSON — обойдёмся статусом.
		return '';
	}
}

/**
 * Сохраняет файл через объектный адрес и сразу его освобождает.
 *
 * @param {Blob} blob
 * @param {string} filename
 */
export function saveBlobAsFile(blob, filename) {
	const url = URL.createObjectURL(blob);
	try {
		const link = document.createElement('a');
		link.href = url;
		link.download = filename || 'document';
		link.rel = 'noopener';
		document.body.appendChild(link);
		link.click();
		link.remove();
	} finally {
		// Освобождаем после клика: браузер уже начал сохранять файл.
		setTimeout(() => URL.revokeObjectURL(url), 0);
	}
}
