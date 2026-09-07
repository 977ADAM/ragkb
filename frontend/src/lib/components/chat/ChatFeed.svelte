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

<section class="flex flex-1 flex-col gap-3 overflow-y-auto py-4" bind:this={feed} aria-live="polite">
	{#each chat.messages as message, i (i)}
		<Message
			{message}
			isLast={i === chat.messages.length - 1}
			streaming={message.role === 'assistant' && chat.busy && i === chat.messages.length - 1}
		/>
	{/each}
	{#if chat.messages.length === 0}
		<p class="text-stone-500 dark:text-stone-400">
			Задайте вопрос по документам базы знаний.
		</p>
	{/if}
</section>
