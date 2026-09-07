<script>
	/**
	 * Модалка источника: фрагмент текста, на который опирался ответ.
	 *
	 * @type {{ source: { n?: number, citation?: string, source?: string,
	 *   page?: number | null, text?: string, available?: boolean | undefined },
	 *   onclose: () => void }}
	 */
	let { source, onclose } = $props();

	/** @param {KeyboardEvent} event */
	function onKey(event) {
		if (event.key === 'Escape') onclose();
	}
</script>

<svelte:window onkeydown={onKey} />

<div
	class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4"
	role="presentation"
	onmousedown={(e) => {
		if (e.target === e.currentTarget) onclose();
	}}
>
	<div
		class="max-h-[80vh] w-full max-w-[42rem] overflow-auto rounded-lg border border-stone-300 bg-white p-4 text-stone-900 shadow-[0_10px_30px_rgba(0,0,0,0.25)] dark:border-stone-700 dark:bg-stone-900 dark:text-stone-100"
		role="dialog"
		aria-modal="true"
		aria-label="Источник"
		tabindex="-1"
	>
		<header class="mb-2 flex items-start justify-between gap-3">
			<h2 class="m-0 text-base leading-snug">
				{source.citation || source.source || 'Источник'}
			</h2>
			<button
				class="cursor-pointer border-none bg-transparent text-xl leading-none text-stone-500 hover:text-red-600 dark:text-stone-400 dark:hover:text-red-400"
				type="button"
				onclick={onclose}
				aria-label="Закрыть"
			>×</button>
		</header>
		<dl class="mb-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
			{#if source.source}
				<dt class="text-stone-500 dark:text-stone-400">Файл</dt>
				<dd class="m-0">{source.source}</dd>
			{/if}
			{#if source.page}
				<dt class="text-stone-500 dark:text-stone-400">Страница</dt>
				<dd class="m-0">{source.page}</dd>
			{/if}
			{#if source.available === false}
				<dt class="text-stone-500 dark:text-stone-400">Статус</dt>
				<dd class="m-0 text-amber-600 dark:text-amber-400">документа больше нет в базе</dd>
			{/if}
		</dl>
		{#if source.text}
			<p class="m-0 whitespace-pre-wrap rounded-md bg-red-100 p-3 text-sm dark:bg-red-950">
				{source.text}
			</p>
		{:else}
			<p class="m-0 text-stone-500 dark:text-stone-400">
				Фрагмент не сохранён — ответ получен до этой версии.
			</p>
		{/if}
	</div>
</div>
