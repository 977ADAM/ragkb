<script>
	import { rateMessage } from '$lib/chat.svelte.js';
	import SourcesModal from './SourcesModal.svelte';

	/**
	 * Одна реплика: текст, ошибка потока, предупреждения, источники, мета.
	 *
	 * @typedef {{n?: number, citation?: string, source?: string, page?: number | null,
	 *   text?: string, available?: boolean | undefined}} Source
	 * @typedef {{id?: number, role: 'user' | 'assistant', text: string,
	 *   sources?: Source[], warnings?: string[], elapsed?: number | null,
	 *   model?: string, error?: string, feedback?: 'up' | 'down' | null}} Message
	 * @type {{ message: Message, streaming?: boolean }}
	 */
	let { message, streaming = false } = $props();

	/** @type {Source | null} */
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
</script>

{#if openSource}
	<SourcesModal source={openSource} onclose={() => (openSource = null)} />
{/if}

<article class={message.role}>
	{#if streaming || message.role === 'user'}
		<p class="text">
			{message.text}{#if streaming}<span class="caret"></span>{/if}
		</p>
	{:else}
		<p class="text">
			{#each segments() as segment, i (i)}
				{#if segment.kind === 'cite'}
					<button
						type="button"
						class="cite"
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
		<p class="error">{message.error}</p>
	{/if}
	{#each message.warnings ?? [] as warning, w (w)}
		<p class="warning">{warning}</p>
	{/each}
	{#if message.sources?.length}
		<ol class="sources">
			{#each message.sources as source, s (s)}
				<li class:missing={source.available === false}>
					<button type="button" class="source-link" onclick={() => (openSource = source)}>
						{source.citation || source.source}
					</button>
					{#if source.available === false}<span> — документа больше нет в базе</span>{/if}
				</li>
			{/each}
		</ol>
	{/if}
	{#if message.elapsed !== null && message.elapsed !== undefined}
		<p class="meta">{message.model} · {message.elapsed} с</p>
	{/if}
	{#if message.role === 'assistant' && message.id !== undefined && !streaming}
		<div class="rating" role="group" aria-label="Оценить ответ">
			<button
				class:active={message.feedback === 'up'}
				disabled={ratingBusy}
				onclick={() => rate('up')}
				title="Полезный ответ"
			>👍</button>
			<button
				class:active={message.feedback === 'down'}
				disabled={ratingBusy}
				onclick={() => rate('down')}
				title="Ответ не помог"
			>👎</button>
			{#if ratingError}
				<span class="rating-error">{ratingError}</span>
			{/if}
		</div>
	{/if}
</article>

<style>
	article {
		padding: 0.6rem 0.85rem;
		border-radius: 0.6rem;
		background: var(--panel);
	}
	article.user {
		align-self: flex-end;
		background: var(--mine);
		max-width: 80%;
	}
	.text {
		margin: 0;
		white-space: pre-wrap;
	}
	.cite {
		border: none;
		background: transparent;
		padding: 0;
		margin: 0;
		font: inherit;
		color: var(--accent, #1d4ed8);
		cursor: pointer;
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.cite:hover {
		text-decoration-thickness: 2px;
	}
	.caret {
		display: inline-block;
		width: 0.5ch;
		height: 1em;
		background: var(--muted);
		vertical-align: -0.15em;
		animation: blink 1s steps(2) infinite;
	}
	@keyframes blink {
		50% {
			opacity: 0;
		}
	}
	.error {
		color: #ef4444;
		margin: 0.4rem 0 0;
		font-size: 0.9rem;
	}
	.warning {
		color: #d97706;
		margin: 0.4rem 0 0;
		font-size: 0.9rem;
	}
	.sources {
		margin: 0.5rem 0 0;
		padding-left: 1.2rem;
		font-size: 0.85rem;
		color: var(--fg);
	}
	.sources .missing {
		color: var(--muted);
	}
	.source-link {
		border: none;
		background: transparent;
		padding: 0;
		margin: 0;
		font: inherit;
		color: inherit;
		cursor: pointer;
		text-align: left;
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.meta {
		margin: 0.4rem 0 0;
		font-size: 0.75rem;
		color: var(--muted);
	}
	.rating {
		margin-top: 0.5rem;
		display: flex;
		gap: 0.35rem;
		align-items: center;
	}
	.rating button {
		border: 1px solid transparent;
		background: transparent;
		font-size: 0.9rem;
		padding: 0.1rem 0.35rem;
		border-radius: 0.4rem;
		cursor: pointer;
		opacity: 0.65;
	}
	.rating button:hover {
		opacity: 1;
		background: var(--hover, rgba(128, 128, 128, 0.15));
	}
	.rating button:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.rating button.active {
		opacity: 1;
		border-color: currentColor;
	}
	.rating-error {
		color: #ef4444;
		font-size: 0.8rem;
	}
</style>
