<script>
	import { downloadAttachment } from '$lib/download.js';

	/**
	 * Карточки приложенных файлов: имя, размер и кнопка скачивания.
	 *
	 * Карточки строятся по данным ответа, а не по ссылкам в тексте модели:
	 * текст может не содержать ничего, а файл при этом выдан. Ошибка
	 * скачивания показывается рядом с файлом и не трогает текст ответа.
	 *
	 * @type {{ attachments?: Array<{document_id: string, filename: string, url: string,
	 *   media_type: string, size: number}> }}
	 */
	let { attachments = [] } = $props();

	/** @type {Record<string, {busy: boolean, error: string}>} */
	let states = $state({});

	/** @param {string} documentId */
	function stateOf(documentId) {
		return states[documentId] ?? { busy: false, error: '' };
	}

	/** @param {{document_id: string, filename: string, url: string, media_type: string, size: number}} attachment */
	async function save(attachment) {
		const current = stateOf(attachment.document_id);
		// Повторные клики во время скачивания ничего не делают.
		if (current.busy) return;
		states[attachment.document_id] = { busy: true, error: '' };
		try {
			await downloadAttachment(attachment);
			states[attachment.document_id] = { busy: false, error: '' };
		} catch (error) {
			states[attachment.document_id] = {
				busy: false,
				error: error instanceof Error ? error.message : String(error)
			};
		}
	}

	/** @param {number} bytes */
	function formatSize(bytes) {
		if (!Number.isFinite(bytes)) return '';
		if (bytes < 1024) return `${bytes} Б`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
	}
</script>

{#if attachments.length}
	<ul class="mt-2 list-none space-y-1 p-0" aria-label="Приложенные файлы">
		{#each attachments as attachment (attachment.document_id)}
			{@const state = stateOf(attachment.document_id)}
			<li
				class="flex flex-wrap items-center gap-2 rounded-md border border-stone-300 px-2 py-1 text-sm dark:border-stone-700"
			>
				<span class="min-w-0 flex-1 truncate" title={attachment.filename}>
					{attachment.filename}
				</span>
				<span class="text-stone-500 dark:text-stone-400">{formatSize(attachment.size)}</span>
				<button
					type="button"
					class="btn"
					disabled={state.busy}
					aria-label={`Скачать ${attachment.filename}`}
					onclick={() => save(attachment)}
				>
					{state.busy ? 'Скачивание…' : 'Скачать'}
				</button>
				{#if state.error}
					<p class="m-0 basis-full text-sm text-red-600 dark:text-red-400">{state.error}</p>
				{/if}
			</li>
		{/each}
	</ul>
{/if}
