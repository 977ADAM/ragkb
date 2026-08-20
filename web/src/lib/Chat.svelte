<script>
	/**
	 * Переписка и поле ввода. Одинаковы на /new и на /chat/{id} — отличается
	 * только то, что страницы делают при входе.
	 */
	import { chat, ask } from '$lib/chat.svelte.js';

	/** @type {{ onCreated?: (id: string) => void }} */
	let { onCreated } = $props();

	/** @type {HTMLElement | undefined} */
	let feed = $state();

	// Держит ленту у нижнего края, пока ответ дописывается.
	$effect(() => {
		// Читаем длину и текст последней реплики, чтобы эффект срабатывал
		// на каждый пришедший кусок потока.
		chat.messages.length;
		chat.messages[chat.messages.length - 1]?.text;
		if (feed) feed.scrollTop = feed.scrollHeight;
	});

	/** @param {KeyboardEvent} event */
	function onKey(event) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			ask(onCreated);
		}
	}
</script>

{#if chat.fatal}
	<p class="fatal">{chat.fatal}</p>
{/if}

<section class="feed" bind:this={feed} aria-live="polite">
	{#each chat.messages as message, i (i)}
		<article class={message.role}>
			<p class="text">{message.text}{#if message.role === 'assistant' && chat.busy && i === chat.messages.length - 1}<span class="caret"></span>{/if}</p>
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
		</article>
	{/each}
	{#if chat.messages.length === 0}
		<p class="empty">Задайте вопрос по документам базы знаний.</p>
	{/if}
</section>

<form
	onsubmit={(e) => {
		e.preventDefault();
		ask(onCreated);
	}}
>
	<textarea
		bind:value={chat.question}
		onkeydown={onKey}
		rows="3"
		placeholder="Вопрос (Enter — отправить, Shift+Enter — перенос строки)"
		disabled={chat.busy}
	></textarea>
	<button type="submit" disabled={chat.busy || !chat.question.trim()}>
		{chat.busy ? 'Отвечает…' : 'Спросить'}
	</button>
</form>

<style>
	.feed {
		flex: 1;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 1rem 0;
	}
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
	.error,
	.fatal {
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
	.empty {
		color: var(--muted);
	}
	form {
		display: flex;
		gap: 0.5rem;
		align-items: flex-end;
	}
	textarea {
		flex: 1;
		font: inherit;
		padding: 0.5rem;
		border: 1px solid var(--line);
		border-radius: 0.5rem;
		resize: vertical;
		background: var(--bg);
		color: inherit;
	}
	button {
		font: inherit;
		padding: 0.5rem 0.9rem;
		border: 1px solid var(--line);
		border-radius: 0.5rem;
		background: var(--panel);
		color: inherit;
		cursor: pointer;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
