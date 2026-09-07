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
	import '../app.css';

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
		await fetch('/api/auths/signout', { method: 'POST', credentials: 'include' });
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

	/** Скрыта ли панель диалогов (sidebar). По умолчанию открыта. */
	let sidebarOpen = $state(true);
	function toggleSidebar() {
		sidebarOpen = !sidebarOpen;
	}

	/** Ширина панели диалогов, px. По умолчанию 15rem = 240px. */
	let sidebarWidth = $state(240);
	/** Перетаскивание за правый край панели. */
	let resizeStartX = 0;
	let resizeStartWidth = 0;

	/** @param {PointerEvent} event */
	function startResize(event) {
		resizeStartX = event.clientX;
		resizeStartWidth = sidebarWidth;
		event.preventDefault();
		window.addEventListener('pointermove', onResize);
		window.addEventListener('pointerup', endResize, { once: true });
	}

	/** @param {PointerEvent} event */
	function onResize(event) {
		const next = resizeStartWidth + (event.clientX - resizeStartX);
		sidebarWidth = Math.min(480, Math.max(180, next));
	}

	function endResize() {
		window.removeEventListener('pointermove', onResize);
	}
</script>

<svelte:head>
	<link rel="icon" href="/logo.png" />
	<title>База знаний</title>
</svelte:head>

{#if authPage || adminPage}
	{@render children()}
{:else}
	<!-- Высота окна, а не min-height: иначе поле ввода уезжает за нижний
	     край и страница целиком ползает под курсором при каждом ответе. -->
	<div class="flex h-dvh max-[40rem]:flex-col">
		{#if chat.historyEnabled && sidebarOpen}
			<!-- На узком экране колонка диалогов превращается в полосу сверху:
			     w-auto + ограничение высоты, вертикальная ручка скрыта. -->
			<aside
				class="flex w-(--sidebar-w) shrink-0 flex-col gap-3 overflow-y-auto border-r border-stone-300 bg-white p-4 dark:border-stone-700 dark:bg-stone-900 max-[40rem]:w-auto max-[40rem]:max-h-[30vh] max-[40rem]:border-r-0 max-[40rem]:border-b"
				style="--sidebar-w: {sidebarWidth}px"
			>
				<button class="btn" onclick={newChat} disabled={chat.busy}>Новый диалог</button>
				<nav class="flex flex-col gap-1">
					{#each chat.conversations as item (item.id)}
						<div
							class="flex items-center rounded-md {item.id === chat.conversationId
								? 'bg-red-50 dark:bg-red-950/40'
								: ''}"
						>
							{#if renaming === item.id}
								<!-- svelte-ignore a11y_autofocus -->
								<input
									class="field min-w-0 flex-1"
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
									class="min-w-0 flex-1 truncate rounded-md px-2 py-1.5 no-underline hover:bg-stone-100 dark:hover:bg-stone-800"
									href="/chat/{item.id}"
									ondblclick={(e) => {
										e.preventDefault();
										startRename(item);
									}}
								>
									{item.title}
								</a>
								<button
									class="btn-icon"
									title="Переименовать диалог"
									aria-label="Переименовать диалог «{item.title}»"
									onclick={() => startRename(item)}
									disabled={chat.busy}>✎</button
								>
								<button
									class="btn-icon"
									title="Удалить диалог"
									aria-label="Удалить диалог «{item.title}»"
									onclick={() => remove(item)}
									disabled={chat.busy}>×</button
								>
							{/if}
						</div>
					{/each}
					{#if chat.conversations.length === 0}
						<p class="px-2 py-1 text-sm text-stone-500 dark:text-stone-400">
							Диалогов пока нет.
						</p>
					{/if}
					{#if chat.conversations.length < chat.conversationsTotal}
						<button
							class="cursor-pointer border-none bg-transparent px-2 py-1 text-left text-sm text-stone-500 hover:text-red-600 disabled:opacity-50 dark:text-stone-400 dark:hover:text-red-400"
							onclick={loadMoreConversations}
							disabled={chat.busy}
						>
							Показать ещё ({chat.conversationsTotal - chat.conversations.length})
						</button>
					{/if}
				</nav>
				{#if chat.user?.name}
					<!-- Профиль прижат к низу колонки: список диалогов может быть коротким. -->
					<div
						class="mt-auto flex items-center gap-2 border-t border-stone-300 pt-2 text-sm dark:border-stone-700"
					>
						<a
							class="min-w-0 flex-1 truncate font-semibold no-underline hover:text-red-600 dark:hover:text-red-400"
							href="/profile"
							title="Профиль"
						>{chat.user.name}</a
						>
						<button type="button" class="btn" onclick={logout}>Выйти</button>
					</div>
				{/if}
			</aside>
			<!-- Ручка изменения ширины панели: тонкая полоса на стыке с контентом. -->
			<div
				class="w-1.5 shrink-0 cursor-col-resize bg-transparent transition-colors hover:bg-red-600 dark:hover:bg-red-500 max-[40rem]:hidden"
				role="separator"
				aria-orientation="vertical"
				onpointerdown={startResize}
			></div>
		{/if}

		<main
			class="mx-auto flex min-w-0 max-w-[46rem] flex-1 flex-col px-4 py-6 pb-8 max-[40rem]:w-full"
		>
			<header class="flex flex-wrap items-center gap-x-2.5 gap-y-2">
				{#if chat.historyEnabled}
					<button
						class="btn"
						type="button"
						onclick={toggleSidebar}
						aria-label={sidebarOpen ? 'Скрыть панель диалогов' : 'Показать панель диалогов'}
						title={sidebarOpen ? 'Скрыть панель' : 'Показать панель'}
					>{sidebarOpen ? '◀' : '☰'}</button>
				{/if}
				<img
					class="block shrink-0 rounded-md"
					src="/logo.png"
					alt=""
					width="28"
					height="28"
				/>
				<h1 class="mr-auto text-xl font-semibold">
					{chat.organization?.name
						? `База знаний — ${chat.organization.name}`
						: 'База знаний'}
				</h1>
				{#if chat.isAdmin}
					<a
						class="text-sm text-red-600 no-underline hover:text-red-700 hover:underline dark:text-red-400 dark:hover:text-red-300"
						href="/admin"
					>Админ</a>
				{/if}
				{#if !chat.historyEnabled && chat.user?.name}
					<a
						class="border-b border-dashed border-stone-400 font-semibold no-underline hover:border-red-500 hover:text-red-600 dark:border-stone-600 dark:hover:border-red-400 dark:hover:text-red-400"
						href="/profile"
						title="Профиль"
					>{chat.user.name}</a
					>
					<button type="button" class="btn" onclick={logout}>Выйти</button>
				{/if}
				{#if chat.canReindex}
					<button class="btn" onclick={rebuildIndex} disabled={chat.busy}>
						Перестроить индекс
					</button>
				{/if}
				{#if !chat.historyEnabled}
					<button class="btn" onclick={newChat} disabled={chat.busy || chat.messages.length === 0}>
						Новый диалог
					</button>
				{/if}
			</header>

			{@render children()}

			{#if chat.version}
				<footer class="text-center text-xs text-stone-400 dark:text-stone-500">
					версия {chat.version}
				</footer>
			{/if}
		</main>
	</div>
{/if}
