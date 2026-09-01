<script>
	import { chat } from '$lib/chat.svelte.js';
	import Message from './Message.svelte';

	/** @type {HTMLElement | undefined} */
	let feed = $state();

	// Держит ленту у нижнего края, пока ответ дописывается.
	$effect(() => {
		chat.messages.length;
		chat.messages[chat.messages.length - 1]?.text;
		if (feed) feed.scrollTop = feed.scrollHeight;
	});
</script>

<section class="feed" bind:this={feed} aria-live="polite">
	{#each chat.messages as message, i (i)}
		<Message
			{message}
			streaming={message.role === 'assistant' && chat.busy && i === chat.messages.length - 1}
		/>
	{/each}
	{#if chat.messages.length === 0}
		<p class="empty">Задайте вопрос по документам базы знаний.</p>
	{/if}
</section>

<style>
	.feed {
		flex: 1;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 1rem 0;
	}
	.empty {
		color: var(--muted);
	}
</style>
