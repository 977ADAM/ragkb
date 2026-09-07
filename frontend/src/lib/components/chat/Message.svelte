<script>
	import { chat, copyText, rateMessage, regenerateMessage } from '$lib/chat.svelte.js';
	import SourcesModal from './SourcesModal.svelte';

	/**
	 * Одна реплика: текст, ошибка потока, предупреждения, источники, мета.
	 *
	 * @type {{ message: { id?: number, role: 'user' | 'assistant', text: string,
	 *   sources?: Array<{n?: number, citation?: string, source?: string, page?: number | null,
	 *   text?: string, available?: boolean | undefined}>,
	 *   warnings?: string[], elapsed?: number | null,
	 *   model?: string, error?: string, feedback?: 'up' | 'down' | null },
	 *   isLast?: boolean, streaming?: boolean }}
	 */
	let { message, isLast = false, streaming = false } = $props();

	/** @type {{ n?: number, citation?: string, source?: string, page?: number | null,
	 *   text?: string, available?: boolean | undefined } | null} */
	let openSource = $state(null);

	/**
	 * Разбивает текст ответа на сегменты: обычный текст и маркеры [N].
	 *
	 * @returns {Array<{ kind: 'text', text: string } | { kind: 'cite', n: number, text: string }>}
	 */
	function segments() {
		const parts = (message.text ?? '').split(/(\[\d+\])/g);
		/** @type {Array<{ kind: 'text', text: string } | { kind: 'cite', n: number, text: string }>} */
		const out = [];
		for (const part of parts) {
			if (!part) continue;
			const m = part.match(/^\[(\d+)\]$/);
			if (m && message.sources?.some((s) => s.n === Number(m[1]))) {
				out.push({ kind: 'cite', n: Number(m[1]), text: part });
			} else {
				out.push({ kind: 'text', text: part });
			}
		}
		return out.length ? out : [{ kind: 'text', text: message.text ?? '' }];
	}

	/** @param {number} n */
	function openByN(n) {
		openSource = message.sources?.find((s) => s.n === n) ?? null;
	}

	let copied = $state(false);
	/** @param {MouseEvent} event */
	async function copy(event) {
		event.preventDefault();
		if (await copyText(message.text ?? '')) {
			copied = true;
			setTimeout(() => (copied = false), 1500);
		}
	}

	let regenBusy = $state(false);
	/** @param {MouseEvent} event */
	async function regenerate(event) {
		event.preventDefault();
		if (regenBusy || message.id === undefined || streaming) return;
		regenBusy = true;
		const ok = await regenerateMessage(message.id);
		regenBusy = false;
		if (ok && message.error) delete message.error;
	}

	let ratingBusy = $state(false);
	let ratingError = $state('');

	/** @param {'up' | 'down'} rating */
	async function rate(rating) {
		if (ratingBusy || message.id === undefined || streaming) return;
		ratingBusy = true;
		ratingError = '';
		const ok = await rateMessage(message.id, rating);
		if (!ok) ratingError = 'Не удалось сохранить оценку';
		ratingBusy = false;
	}

	/** Действия нужны, когда у сообщения есть что скопировать или показать. */
	const hasActions = $derived(Boolean(message.text) || Boolean(message.error));
</script>

{#if openSource}
	<SourcesModal source={openSource} onclose={() => (openSource = null)} />
{/if}

<article
	class="w-fit max-w-[85%] rounded-lg border border-stone-300 bg-white p-3 dark:border-stone-700 dark:bg-stone-900 {message.role ===
	'user'
		? 'self-end border-red-200 bg-red-100 dark:border-red-900 dark:bg-red-950'
		: ''}"
>
	{#if streaming || message.role === 'user'}
		<p class="m-0 whitespace-pre-wrap">
			{message.text}{#if streaming}<span class="animate-blink inline-block w-0.5 h-[1em] translate-y-[0.15em] bg-stone-500 dark:bg-stone-400"></span>{/if}
		</p>
	{:else}
		<p class="m-0 whitespace-pre-wrap">
			{#each segments() as segment, i (i)}
				{#if segment.kind === 'cite'}
					<button
						type="button"
						class="cursor-pointer border-none bg-transparent p-0 text-red-600 underline decoration-red-600 underline-offset-2 hover:decoration-[3px] dark:text-red-400 dark:decoration-red-400"
						onclick={() => openByN(segment.n)}
						aria-label={`Источник ${segment.n}`}
					>{segment.text}</button
					>
				{:else}
					{segment.text}
				{/if}
			{/each}
		</p>
	{/if}
	{#if message.error}
		<p class="mt-1 text-sm text-red-600 dark:text-red-400">{message.error}</p>
	{/if}
	{#each message.warnings ?? [] as warning, w (w)}
		<p class="mt-1 text-sm text-amber-600 dark:text-amber-400">{warning}</p>
	{/each}
	{#if message.sources?.length}
		<ol class="mt-2 list-decimal space-y-0.5 pl-5 text-sm">
			{#each message.sources as source, s (s)}
				<li
					class={source.available === false
						? 'text-stone-500 dark:text-stone-400'
						: ''}
				>
					<button
						type="button"
						class="cursor-pointer border-none bg-transparent p-0 text-left text-inherit underline underline-offset-2 hover:text-red-600 dark:hover:text-red-400"
						onclick={() => (openSource = source)}
					>
						{source.citation || source.source}
					</button>
					{#if source.available === false}
						<span class="text-stone-500 dark:text-stone-400"> — документа больше нет в базе</span>
					{/if}
				</li>
			{/each}
		</ol>
	{/if}
	{#if message.elapsed !== null && message.elapsed !== undefined}
		<p class="mt-1 text-xs text-stone-500 dark:text-stone-400">
			{message.model} · {message.elapsed} с
		</p>
	{/if}
	{#if hasActions && !streaming}
		<div class="mt-2 flex items-center gap-1" role="group" aria-label="Действия над сообщением">
			<button
				type="button"
				class="btn-icon rounded text-base opacity-70 hover:opacity-100 {copied ? 'opacity-100' : ''}"
				onclick={copy}
				title="Скопировать текст"
			>
				{copied ? '✓' : '⧉'}
			</button>
			{#if message.role === 'assistant' && message.id !== undefined && isLast}
				<button
					type="button"
					class="btn-icon rounded text-base opacity-70 hover:opacity-100"
					disabled={regenBusy || chat.busy}
					onclick={regenerate}
					title="Перегенерировать ответ"
				>↻</button>
			{/if}
			{#if message.role === 'assistant' && message.id !== undefined}
				<button
					class="btn-icon rounded text-base opacity-70 {message.feedback === 'up' ? 'opacity-100 ring-1 ring-current' : ''}"
					disabled={ratingBusy}
					onclick={() => rate('up')}
					title="Полезный ответ"
				>👍</button>
				<button
					class="btn-icon rounded text-base opacity-70 {message.feedback === 'down' ? 'opacity-100 ring-1 ring-current' : ''}"
					disabled={ratingBusy}
					onclick={() => rate('down')}
					title="Ответ не помог"
				>👎</button>
			{/if}
			{#if ratingError}
				<span class="text-xs text-red-600 dark:text-red-400">{ratingError}</span>
			{/if}
		</div>
	{/if}
</article>
