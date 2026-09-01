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
	onsubmit={(e) => {
		e.preventDefault();
		send();
	}}
>
	<div role="presentation">
		<fieldset class="composer" data-status={chat.busy ? 'busy' : 'idle'} disabled={chat.busy}>
			<legend class="sr-only">Вопрос к базе знаний</legend>
			<textarea
				bind:value={chat.question}
				onkeydown={onKey}
				rows="3"
				maxlength={CHAR_LIMIT}
				placeholder="Вопрос (Enter — отправить, Shift+Enter — перенос строки)"
			></textarea>
			<div class="composer-bar">
				<div class="status">
					<span class="status-dot"></span>
					<span class="status-text">{chat.busy ? 'Отвечает…' : 'Готов'}</span>
				</div>
				<span class="char-counter" aria-live="polite">
					{chat.question.length} / {CHAR_LIMIT}
				</span>
				<div class="history">
					<button
						type="button"
						class="history-btn"
						aria-label="История вопросов"
						aria-expanded={historyOpen}
						disabled={pastQuestions.length === 0}
						onclick={toggleHistory}
					>
						↑
					</button>
					{#if historyOpen}
						<ul class="history-list" role="listbox" aria-label="Прошлые вопросы">
							{#each [...pastQuestions].reverse() as text, i (i)}
								<li>
									<button type="button" onclick={() => useQuestion(text)}>{text}</button>
								</li>
							{/each}
						</ul>
					{/if}
				</div>
				<button type="submit" disabled={!canSend}>
					{chat.busy ? 'Отвечает…' : 'Спросить'}
				</button>
			</div>
		</fieldset>
	</div>
</form>

<style>
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}
	form {
		width: 100%;
	}
	.composer {
		margin: 0;
		min-width: 0;
		width: 100%;
		box-sizing: border-box;
		padding: 0.5rem 0.6rem 0.6rem;
		border: 1px solid var(--line);
		border-radius: 0.6rem;
		background: var(--bg);
	}
	.composer textarea {
		display: block;
		width: 100%;
		box-sizing: border-box;
		font: inherit;
		padding: 0.35rem 0.15rem 0.5rem;
		border: none;
		resize: vertical;
		background: transparent;
		color: inherit;
	}
	.composer textarea:focus {
		outline: none;
	}
	.composer-bar {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.status {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.8rem;
		color: var(--muted);
		margin-right: auto;
	}
	.status-dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 50%;
		background: #22c55e;
	}
	.composer[data-status='busy'] .status-dot {
		background: #f59e0b;
		animation: blink 1s steps(2) infinite;
	}
	@keyframes blink {
		50% {
			opacity: 0;
		}
	}
	.char-counter {
		font-size: 0.75rem;
		color: var(--muted);
		font-variant-numeric: tabular-nums;
	}
	.history {
		position: relative;
	}
	.history-btn {
		font: inherit;
		padding: 0.35rem 0.55rem;
		border: 1px solid var(--line);
		border-radius: 0.45rem;
		background: var(--panel);
		color: inherit;
		cursor: pointer;
		line-height: 1;
	}
	.history-list {
		position: absolute;
		right: 0;
		bottom: calc(100% + 0.35rem);
		z-index: 2;
		margin: 0;
		padding: 0.25rem;
		list-style: none;
		min-width: 16rem;
		max-width: min(24rem, 70vw);
		max-height: 12rem;
		overflow-y: auto;
		border: 1px solid var(--line);
		border-radius: 0.5rem;
		background: var(--bg);
		box-shadow: 0 0.4rem 1rem rgb(0 0 0 / 0.12);
	}
	.history-list button {
		display: block;
		width: 100%;
		font: inherit;
		text-align: left;
		padding: 0.4rem 0.5rem;
		border: none;
		border-radius: 0.35rem;
		background: none;
		color: inherit;
		cursor: pointer;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.history-list button:hover {
		background: var(--panel);
	}
	.composer-bar > button[type='submit'] {
		font: inherit;
		padding: 0.5rem 0.9rem;
		border: 1px solid var(--line);
		border-radius: 0.5rem;
		background: var(--panel);
		color: inherit;
		cursor: pointer;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
