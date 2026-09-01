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
</script>

{#if chat.fatal}
	<p class="fatal">{chat.fatal}</p>
{/if}

<ChatFeed />
<ChatComposer {onCreated} />

<style>
	.fatal {
		color: #ef4444;
		margin: 0.4rem 0 0;
		font-size: 0.9rem;
	}
</style>
