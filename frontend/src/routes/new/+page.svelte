<script>
	/** Чистый чат. Как только сервер заведёт диалог, адрес меняется на /chat/{id}. */
	import { replaceState } from '$app/navigation';
	import Chat from '$lib/Chat.svelte';
	import { reset } from '$lib/chat.svelte.js';

	// Вход на /new всегда означает пустую переписку, даже если только что
	// смотрели чужой диалог.
	reset();

	/** @param {string} id */
	function onCreated(id) {
		// replaceState, а не goto: переход на свежесозданный диалог — не новый
		// шаг в истории браузера, «назад» должно вести туда, откуда пришли.
		replaceState(`/chat/${id}`, {});
	}
</script>

<Chat {onCreated} />
