<script>
	/**
	 * Общая рамка: панель диалогов слева, шапка с выбором модели сверху.
	 *
	 * Живёт в раскладке, а не на страницах, потому что при переходе между
	 * /new и /chat/{id} панель не должна перерисовываться и терять прокрутку.
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
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

	const authPage = $derived(page.url.pathname === '/login' || page.url.pathname === '/register');
	const adminPage = $derived(
		page.url.pathname === '/admin' || page.url.pathname.startsWith('/admin/')
	);

	// start() не зовём на /login и /register. После goto('/new') раскладка
	// не перемонтируется — поэтому следим за путём, а не только onMount.
	// chat.started не даёт эффекту зациклиться от собственного присвоения.
	$effect(() => {
		if (authPage || adminPage) return;
		start();
	});

	onMount(() => {
		const refresh = () => {
			if (document.visibilityState === 'visible' && !chat.busy && !authPage && !adminPage) {
				loadConversations({ consistency: 'eventual' });
			}
		};
		document.addEventListener('visibilitychange', refresh);
		return () => {
			document.removeEventListener('visibilitychange', refresh);
		};
	});

	async function logout() {
		await fetch('/api/auth/signout', { method: 'POST', credentials: 'include' });
		location.href = '/login';
	}

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
	<link rel="icon" href="/logo.png" />
	<title>База знаний</title>
</svelte:head>

{#if authPage || adminPage}
	{@render children()}
{:else}
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
			{#if chat.user?.name}
				<div class="me">
					<a href="/profile" class="username" title="Профиль">{chat.user.name}</a>
					<button type="button" class="logout" onclick={logout}>Выйти</button>
				</div>
			{/if}
		</aside>
	{/if}

	<main>
		<header>
			<img class="logo" src="/logo.png" alt="" width="28" height="28" />
			<h1>
				{chat.organization?.name
					? `База знаний — ${chat.organization.name}`
					: 'База знаний'}
			</h1>
			{#if chat.isAdmin}
				<a href="/admin">Админ</a>
			{/if}
			{#if !chat.historyEnabled && chat.user?.name}
				<a href="/profile" class="username" title="Профиль">{chat.user.name}</a>
				<button type="button" onclick={logout}>Выйти</button>
			{/if}
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
{/if}

<style>
	/* Собственные цвета и тема: без них страница берёт фон браузера,
	   и в тёмной теме чёрный текст ложится на чёрный фон. */
	:global(html) {
		color-scheme: light dark;
		/* Дружелюбная красная палитра: тёплый фон, «клубничные» акценты,
		   без агрессивно-сигнальных заливок. */
		--bg: #fff8f6;
		--fg: #411414;
		--muted: #a66a63;
		--panel: #fdeae5;
		--mine: #ffd9d2;
		--line: #eec4bb;
		--accent: #d64541;
		--accent-soft: #fbe3e0;
		--error: #c0392b;
		--warning: #a9741e;
		--accent-contrast: #fff;
	}
	@media (prefers-color-scheme: dark) {
		:global(html) {
			--bg: #221313;
			--fg: #f3e3e0;
			--muted: #c2958d;
			--panel: #35211e;
			--mine: #5e2621;
			--line: #5a342e;
			--accent: #f07770;
			--accent-soft: #4c2a26;
			--error: #f0807a;
			--warning: #e0a94a;
			--accent-contrast: #3a1512;
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
	/* Профиль прижат к низу колонки: список диалогов может быть коротким. */
	.me {
		margin-top: auto;
		padding-top: 0.5rem;
		border-top: 1px solid var(--line);
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.9rem;
	}
	.me .username {
		flex: 1;
		min-width: 0;
		color: inherit;
		font-weight: 600;
		text-decoration: none;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.me .username:hover {
		color: var(--accent);
	}
	.me .logout {
		font: inherit;
		padding: 0.3rem 0.6rem;
		border: 1px solid var(--line);
		border-radius: 0.45rem;
		background: var(--panel);
		color: inherit;
		cursor: pointer;
	}
	.me .logout:hover {
		border-color: var(--accent);
		color: var(--accent);
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
		gap: 0.6rem;
		flex-wrap: wrap;
	}
	.logo {
		flex: none;
		border-radius: 0.4rem;
		display: block;
	}
	h1 {
		font-size: 1.25rem;
		margin: 0 auto 0 0;
	}
	header a {
		color: var(--accent);
		font-size: 0.9rem;
	}
	header a.username {
		color: inherit;
		font-weight: 600;
		text-decoration: none;
		border-bottom: 1px dashed var(--line);
	}
	header a.username:hover {
		color: var(--accent);
		border-bottom-color: var(--accent);
	}
	header button {
		font: inherit;
		padding: 0.4rem 0.8rem;
		border: 1px solid var(--line);
		border-radius: 0.5rem;
		background: var(--panel);
		color: inherit;
		cursor: pointer;
	}
	header button:not(:disabled):hover {
		border-color: var(--accent);
		color: var(--accent);
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
