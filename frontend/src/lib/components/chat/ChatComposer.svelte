<script>
	import { chat, ask } from '$lib/chat.svelte.js';

	const CHAR_LIMIT = 4000;

	/** @type {{ onCreated?: (id: string) => void }} */
	let { onCreated } = $props();

	let historyOpen = $state(false);

	const pastQuestions = $derived(
		chat.messages.filter((m) => m.role === 'user').map((m) => m.text).filter(Boolean)
	);
	const canSend = $derived(!chat.busy && Boolean(chat.question.trim()));

	function send() {
		if (!canSend) return;
		historyOpen = false;
		ask(onCreated);
	}

	/** @param {KeyboardEvent} event */
	function onKey(event) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			send();
		} else if (event.key === 'Escape') {
			historyOpen = false;
		}
	}

	function toggleHistory() {
		if (pastQuestions.length === 0 || chat.busy) return;
		historyOpen = !historyOpen;
	}

	/** @param {string} text */
	function useQuestion(text) {
		chat.question = text;
		historyOpen = false;
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
			<div class="relative">
				<button
					type="button"
					class="btn px-2.5 leading-none"
					aria-label="История вопросов"
					aria-expanded={historyOpen}
					disabled={pastQuestions.length === 0}
					onclick={toggleHistory}
				>
					↑
				</button>
				{#if historyOpen}
					<ul
						class="absolute right-0 bottom-full z-20 mb-1.5 min-w-64 max-w-(--history-max) max-h-48 list-none overflow-y-auto rounded-lg border border-stone-300 bg-white p-1 shadow-lg dark:border-stone-700 dark:bg-stone-900"
						style="--history-max: min(24rem, 70vw)"
						role="listbox"
						aria-label="Прошлые вопросы"
					>
						{#each [...pastQuestions].reverse() as text, i (i)}
							<li>
								<button
									class="block w-full cursor-pointer truncate rounded-md px-2 py-1.5 text-left text-stone-900 hover:bg-stone-100 dark:text-stone-100 dark:hover:bg-stone-800"
									type="button"
									onclick={() => useQuestion(text)}
								>
									{text}
								</button>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
			<button type="submit" class="btn-accent" disabled={!canSend}>
				{chat.busy ? 'Отвечает…' : 'Спросить'}
			</button>
		</div>
	</fieldset>
</form>
