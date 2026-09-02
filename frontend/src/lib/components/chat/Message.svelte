<script>
	import { rateMessage } from '$lib/chat.svelte.js';

	/**
	 * Одна реплика: текст, ошибка потока, предупреждения, источники, мета.
	 *
	 * @typedef {{source?: string, title?: string, available?: boolean}} Source
	 * @typedef {{id?: number, role: 'user' | 'assistant', text: string,
	 *   sources?: Source[], warnings?: string[], elapsed?: number | null,
	 *   model?: string, error?: string, feedback?: 'up' | 'down' | null}} Message
	 * @type {{ message: Message, streaming?: boolean }}
	 */
	let { message, streaming = false } = $props();

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

<article class={message.role}>
	<p class="text">
		{message.text}{#if streaming}<span class="caret"></span>{/if}
	</p>
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
					{source.title || source.source}
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
