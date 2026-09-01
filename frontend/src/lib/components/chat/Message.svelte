<script>
	/**
	 * Одна реплика: текст, ошибка потока, предупреждения, источники, мета.
	 *
	 * @typedef {{source?: string, title?: string, available?: boolean}} Source
	 * @typedef {{role: 'user' | 'assistant', text: string, sources?: Source[],
	 *   warnings?: string[], elapsed?: number | null, model?: string, error?: string}} Message
	 * @type {{ message: Message, streaming?: boolean }}
	 */
	let { message, streaming = false } = $props();
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
</style>
