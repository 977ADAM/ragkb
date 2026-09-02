<script>
	/**
	 * Переписка и поле ввода. Одинаковы на /new и на /chat/{id} — отличается
	 * только то, что страницы делают при входе.
	 */
	import { chat } from '$lib/chat.svelte.js';
	import ChatFeed from '$lib/components/chat/ChatFeed.svelte';
	import ChatComposer from '$lib/components/chat/ChatComposer.svelte';

	/** @type {{ onCreated?: (id: string) => void }} */
	let { onCreated } = $props();

	const isEmpty = $derived(chat.messages.length === 0);
</script>

{#if chat.fatal}
	<p class="fatal">{chat.fatal}</p>
{/if}

{#if isEmpty}
	<!-- Пустой диалог (/new): поле вопроса по центру экрана, лента не нужна. -->
	<div class="start">
		<p class="hint">Задайте вопрос по документам базы знаний.</p>
		<ChatComposer {onCreated} />
	</div>
{:else}
	<ChatFeed />
	<ChatComposer {onCreated} />
{/if}

<style>
	.fatal {
		color: var(--error);
		margin: 0.4rem 0 0;
		font-size: 0.9rem;
	}
	.start {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.75rem;
	}
	.hint {
		color: var(--muted);
		font-size: 1.05rem;
	}
	/* Поле ввода в центре шире обычного — ему не тесно под лентой. */
	.start :global(.composer) {
		width: min(42rem, 100%);
	}
</style>
