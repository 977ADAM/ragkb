<script>
    import { onMount } from 'svelte';
    import { page } from '$app/state';
    import { chat, start, reset, rebuildIndex } from '$lib/chat.svelte.js';
    import '../app.css';
    let { children } = $props();
    const management = $derived(page.url.pathname.startsWith('/admin'));
    onMount(() => { start(); });
</script>

<svelte:head>
    <link rel="icon" href="/logo.png" />
</svelte:head>

{#if management}
    {@render children()}
{:else}
    <main class="mx-auto flex h-dvh w-full max-w-[46rem] flex-col px-4 py-6 pb-8">
        <header class="flex flex-wrap items-center gap-x-2.5 gap-y-2">
            <img class="block shrink-0 rounded-md" src="/logo.png" alt="" width="28" height="28" />
            <h1 class="mr-auto text-xl font-semibold">
                {chat.organization?.name ? `${chat.organization.id} - ${chat.organization.name}` : 'База знаний'}
            </h1>
            <a class="text-sm no-underline hover:underline" href="/admin">Управление</a>
            <a class="text-sm no-underline hover:underline" href="/admin/documents">Документы</a>
            <button class="btn" onclick={rebuildIndex} disabled={chat.busy}>Перестроить индекс</button>
            <button class="btn" onclick={reset} disabled={chat.busy || !chat.messages.length}>Очистить чат</button>
        </header>
        {@render children()}
        <footer class="text-center text-xs text-stone-400 dark:text-stone-500">
            Переписка не сохраняется. Каждый вопрос обрабатывается отдельно.
            {#if chat.version}<span> · версия {chat.version}</span>{/if}
        </footer>
    </main>
{/if}
