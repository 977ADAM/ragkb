<script>
	import { chat, ask } from '$lib/chat.svelte.js';

	const CHAR_LIMIT = 4000;

	const canSend = $derived(!chat.busy && chat.question.trim().length >= 2);

	function send() {
		if (!canSend) return;
		ask();
	}

	/** @param {KeyboardEvent} event */
	function onKey(event) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			send();
		}
	}

</script>

<form
	class="w-full"
	onsubmit={(e) => {
		e.preventDefault();
		send();
	}}
>
	<fieldset
		class="m-0 box-border w-full min-w-0 rounded-lg border border-stone-300 bg-white p-2 pb-2.5 dark:border-stone-700 dark:bg-stone-900"
		disabled={chat.busy}
	>
		<legend class="sr-only">Вопрос к базе знаний</legend>
		<textarea
			class="block box-border w-full resize-y border-none bg-transparent px-1 pb-2 pt-1.5 text-stone-900 outline-none placeholder:text-stone-400 focus:outline-none dark:text-stone-100 dark:placeholder:text-stone-500"
			bind:value={chat.question}
			onkeydown={onKey}
			rows="3"
			maxlength={CHAR_LIMIT}
			placeholder="Вопрос (Enter — отправить, Shift+Enter — перенос строки)"
		></textarea>
		<div class="flex flex-wrap items-center gap-2">
			<div class="mr-auto flex items-center gap-1.5 text-sm text-stone-500 dark:text-stone-400">
				<span
					class="size-2 rounded-full {chat.busy
						? 'animate-blink bg-amber-600 dark:bg-amber-500'
						: 'bg-red-600 dark:bg-red-500'}"
				></span>
				<span>{chat.busy ? 'Отвечает…' : 'Готов'}</span>
			</div>
			{#if chat.models.length > 0}
				<label class="max-w-56">
					<span class="sr-only">Модель</span>
					<select
						class="max-w-56 cursor-pointer rounded-md border border-stone-300 bg-white px-2 py-1.5 text-sm text-stone-900 outline-none disabled:cursor-default disabled:opacity-60 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-100"
						bind:value={chat.model}
						disabled={chat.busy || chat.models.length === 0}
					>
						{#each chat.models as item (item.id)}
							<option value={item.id}>{item.display_name || item.id}</option>
						{/each}
					</select>
				</label>
			{/if}
			<span class="text-xs tabular-nums text-stone-500 dark:text-stone-400" aria-live="polite">
				{chat.question.length} / {CHAR_LIMIT}
			</span>
			<button type="submit" class="btn-accent" disabled={!canSend}>
				{chat.busy ? 'Отвечает…' : 'Спросить'}
			</button>
		</div>
	</fieldset>
</form>
