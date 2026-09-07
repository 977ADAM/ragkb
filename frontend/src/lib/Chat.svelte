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
	<p class="my-1 text-sm text-red-600 dark:text-red-400">{chat.fatal}</p>
{/if}

{#if isEmpty}
	<!-- Пустой диалог (/new): поле вопроса по центру экрана, лента не нужна. -->
	<div class="flex flex-1 flex-col items-center justify-center gap-3">
		<p class="text-base text-stone-500 dark:text-stone-400">
			Задайте вопрос по документам базы знаний.
		</p>
		<!-- Поле ввода в центре шире обычного — ему не тесно под лентой. -->
		<div class="w-full max-w-[42rem]">
			<ChatComposer {onCreated} />
		</div>
	</div>
{:else}
	<ChatFeed />
	<ChatComposer {onCreated} />
{/if}
