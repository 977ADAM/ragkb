<script>
	/** Выбранный диалог. Переписка подгружается по идентификатору из адреса. */
	import { page } from '$app/state';
	import Chat from '$lib/Chat.svelte';
	import { chat, openConversation } from '$lib/chat.svelte.js';

	// $effect, а не onMount: при переходе между диалогами страница
	// переиспользуется, монтирования второй раз не будет.
	$effect(() => {
		const id = page.params.id;
		if (id && id !== chat.conversationId) openConversation(id);
	});
</script>

<Chat />
