<script>
	/**
	 * Общая рамка: панель диалогов слева, шапка с выбором модели сверху.
	 *
	 * Живёт в раскладке, а не на страницах, потому что при переходе между
	 * /new и /chat/{id} панель не должна перерисовываться и терять прокрутку.
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import favicon from '$lib/assets/favicon.svg';
	import {
		chat,
		start,
		reset,
		renameConversation,
		removeConversation,
		loadConversations,
		loadMoreConversations,
		rebuildIndex
	} from '$lib/chat.svelte.js';

	let { children } = $props();

	// onMount, а не $effect: start() читает состояние, которое сам же
	// присваивает, и эффект перезапускался бы от собственной работы.
	onMount(() => {
		let cancelled = false;
		const refresh = () => {
			if (document.visibilityState === 'visible' && !chat.busy) {
				loadConversations({ consistency: 'eventual' });
			}
		};
		start().then(() => {
			if (cancelled) return;
			document.addEventListener('visibilitychange', refresh);
		});
		return () => {
			cancelled = true;
			document.removeEventListener('visibilitychange', refresh);
		};
	});

	/** @type {string | null} */
	let renaming = $state(null);
	let renameTitle = $state('');

	/** @param {{id: string, title: string}} item */
	function startRename(item) {
		if (chat.busy) return;
		renaming = item.id;
		renameTitle = item.title;
	}

	function commitRename() {
		const id = renaming;
		const title = renameTitle.trim();
		const item = chat.conversations.find((c) => c.id === id);
		renaming = null;
		if (!id || !title || title === item?.title) return;
		renameConversation(id, title);
	}

	/** @param {KeyboardEvent} event */
	function onRenameKey(event) {
		if (event.key === 'Enter') {
			event.preventDefault();
			commitRename();
		} else if (event.key === 'Escape') {
			renaming = null;
		}
	}

	/** @param {{id: string, title: string}} item */
	async function remove(item) {
		if (chat.busy) return;
		// Удаление безвозвратно — ни в интерфейсе, ни в API восстановления нет.
		if (!confirm(`Удалить диалог «${item.title}»? Это необратимо.`)) return;
		const wasOpen = await removeConversation(item.id);
		// Остались бы на адресе удалённого диалога — страница показала бы
		// «диалог не найден» на пустом месте.
		if (wasOpen) goto('/new');
	}

	function newChat() {
		reset();
		goto('/new');
	}
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>База знаний</title>
</svelte:head>

<div class="app">
	{#if chat.historyEnabled}
		<aside>
			<button class="new" onclick={newChat} disabled={chat.busy}>Новый диалог</button>
			<nav>
				{#each chat.conversations as item (item.id)}
					<div class="item" class:active={item.id === chat.conversationId}>
						{#if renaming === item.id}
							<!-- svelte-ignore a11y_autofocus -->
							<input
								class="rename"
								bind:value={renameTitle}
								onkeydown={onRenameKey}
								onblur={commitRename}
								onfocus={(e) => e.currentTarget.select()}
								maxlength="60"
								autofocus
								aria-label="Новый заголовок диалога"
							/>
						{:else}
							<a
								class="open"
								href="/chat/{item.id}"
								ondblclick={(e) => {
									e.preventDefault();
									startRename(item);
								}}
							>
								{item.title}
							</a>
							<button
								class="icon"
								title="Переименовать диалог"
								aria-label="Переименовать диалог «{item.title}»"
								onclick={() => startRename(item)}
								disabled={chat.busy}>✎</button
							>
							<button
								class="icon"
								title="Удалить диалог"
								aria-label="Удалить диалог «{item.title}»"
								onclick={() => remove(item)}
								disabled={chat.busy}>×</button
							>
						{/if}
					</div>
				{/each}
				{#if chat.conversations.length === 0}
					<p class="empty">Диалогов пока нет.</p>
				{/if}
				{#if chat.conversations.length < chat.conversationsTotal}
					<button class="more" onclick={loadMoreConversations} disabled={chat.busy}>
						Показать ещё ({chat.conversationsTotal - chat.conversations.length})
					</button>
				{/if}
			</nav>
		</aside>
	{/if}

	<main>
		<header>
			<h1>
				{chat.organization?.name
					? `База знаний — ${chat.organization.name}`
					: 'База знаний'}
			</h1>
			<label>
				Модель
				<select bind:value={chat.model} disabled={chat.busy || chat.models.length === 0}>
					{#each chat.models as item (item.id)}
						<option value={item.id}>{item.display_name || item.id}</option>
					{/each}
				</select>
			</label>
			{#if chat.canReindex}
				<button onclick={rebuildIndex} disabled={chat.busy}>Перестроить индекс</button>
			{/if}
			{#if !chat.historyEnabled}
				<button onclick={newChat} disabled={chat.busy || chat.messages.length === 0}>
					Новый диалог
				</button>
			{/if}
		</header>

		{@render children()}
	</main>
</div>

<style>
	/* Собственные цвета и тема: без них страница берёт фон браузера,
	   и в тёмной теме чёрный текст ложится на чёрный фон. */
	:global(html) {
		color-scheme: light dark;
		--bg: #ffffff;
		--fg: #111827;
		--muted: #6b7280;
		--panel: #f3f4f6;
		--mine: #dbeafe;
		--line: #d1d5db;
	}
	@media (prefers-color-scheme: dark) {
		:global(html) {
			--bg: #111315;
			--fg: #e5e7eb;
			--muted: #9ca3af;
			--panel: #1f2226;
			--mine: #1e3a5f;
			--line: #374151;
		}
	}
	:global(body) {
		margin: 0;
		background: var(--bg);
		color: var(--fg);
	}
	.app {
		display: flex;
		/* Высота окна, а не min-height: иначе поле ввода уезжает за нижний
		   край и страница целиком ползает под курсором при каждом ответе. */
		height: 100dvh;
		font: 16px/1.5 system-ui, sans-serif;
	}
	aside {
		width: 15rem;
		flex: none;
		box-sizing: border-box;
		border-right: 1px solid var(--line);
		padding: 1rem 0.75rem;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		overflow-y: auto;
	}
	nav {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	/* На узком экране колонка диалогов съедала половину ширины и переписку
	   читать становилось нечем — там она превращается в полосу сверху. */
	@media (max-width: 40rem) {
		.app {
			flex-direction: column;
		}
		aside {
			width: auto;
			max-height: 30vh;
			border-right: none;
			border-bottom: 1px solid var(--line);
		}
	}
	.item {
		display: flex;
		align-items: center;
		border-radius: 0.4rem;
	}
	.item.active {
		background: var(--panel);
	}
	.item .open {
		flex: 1;
		min-width: 0;
		padding: 0.4rem 0.5rem;
		color: inherit;
		text-decoration: none;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.item .icon {
		border: none;
		background: none;
		color: var(--muted);
		padding: 0.2rem 0.4rem;
		cursor: pointer;
	}
	.item .rename {
		flex: 1;
		min-width: 0;
		font: inherit;
		padding: 0.35rem 0.45rem;
		border: 1px solid var(--line);
		border-radius: 0.4rem;
		background: var(--bg);
		color: inherit;
	}
	main {
		flex: 1;
		min-width: 0;
		max-width: 46rem;
		margin: 0 auto;
		padding: 1.5rem 1rem 2rem;
		display: flex;
		flex-direction: column;
		box-sizing: border-box;
	}
	header {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
	}
	h1 {
		font-size: 1.25rem;
		margin: 0 auto 0 0;
	}
	label {
		font-size: 0.85rem;
		color: var(--muted);
	}
	.empty {
		color: var(--muted);
	}
	.more {
		font: inherit;
		margin-top: 0.25rem;
		padding: 0.35rem 0.5rem;
		border: none;
		background: none;
		color: var(--muted);
		cursor: pointer;
		text-align: left;
	}
	.new {
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
