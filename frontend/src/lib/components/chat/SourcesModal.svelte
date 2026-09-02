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
	class="overlay"
	role="presentation"
	onmousedown={(e) => {
		if (e.target === e.currentTarget) onclose();
	}}
>
	<div class="dialog" role="dialog" aria-modal="true" aria-label="Источник" tabindex="-1">
		<header>
			<h2>{source.citation || source.source || 'Источник'}</h2>
			<button class="close" type="button" onclick={onclose} aria-label="Закрыть">×</button>
		</header>
		<dl class="facts">
			{#if source.source}
				<dt>Файл</dt>
				<dd>{source.source}</dd>
			{/if}
			{#if source.page}
				<dt>Страница</dt>
				<dd>{source.page}</dd>
			{/if}
			{#if source.available === false}
				<dt>Статус</dt>
				<dd class="missing">документа больше нет в базе</dd>
			{/if}
		</dl>
		{#if source.text}
			<p class="snippet">{source.text}</p>
		{:else}
			<p class="muted">Фрагмент не сохранён — ответ получен до этой версии.</p>
		{/if}
	</div>
</div>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.45);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 50;
		padding: 1rem;
	}
	.dialog {
		background: var(--panel, #fff);
		color: var(--fg, #111);
		border-radius: 0.6rem;
		max-width: 42rem;
		width: 100%;
		max-height: 80vh;
		overflow: auto;
		padding: 1rem 1.15rem;
		box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 0.75rem;
		margin-bottom: 0.6rem;
	}
	h2 {
		margin: 0;
		font-size: 1.05rem;
		line-height: 1.3;
	}
	.close {
		border: none;
		background: transparent;
		font-size: 1.4rem;
		line-height: 1;
		cursor: pointer;
		color: var(--muted, #6b7280);
	}
	.facts {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.15rem 0.75rem;
		margin: 0 0 0.75rem;
		font-size: 0.8rem;
	}
	dt {
		color: var(--muted, #6b7280);
	}
	dd {
		margin: 0;
	}
	dd.missing {
		color: var(--warning);
	}
	.snippet {
		margin: 0;
		white-space: pre-wrap;
		background: var(--mine);
		border-radius: 0.4rem;
		padding: 0.6rem 0.75rem;
		font-size: 0.9rem;
	}
	.muted {
		color: var(--muted, #6b7280);
	}
</style>
