<script>
	import { onMount } from 'svelte';

	/** @type {{ name?: string, id?: string, description?: string, links?: { users?: string, reports?: string } } | null} */
	let org = $state(null);
	let error = $state('');

	onMount(async () => {
		try {
			const response = await fetch('/api/admin/organization', { credentials: 'include' });
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось загрузить организацию';
				return;
			}
			org = body;
		} catch (err) {
			error = String(err);
		}
	});
</script>

<h1 class="mb-4 text-xl font-semibold">{org?.name || 'Организация'}</h1>
{#if error}
	<p class="text-red-600 dark:text-red-400">{error}</p>
{:else if org}
	{#if org.description}
		<p>{org.description}</p>
	{/if}
	{#if org.id}
		<p class="text-stone-500 dark:text-stone-400">Идентификатор: {org.id}</p>
	{/if}
	<p>
		<a class="no-underline hover:underline" href="/admin/users">Пользователи</a>
		·
		<a class="no-underline hover:underline" href="/admin/documents">Документы</a>
		·
		<a class="no-underline hover:underline" href="/admin/feedback">Оценки ответов</a>
		·
		<a class="no-underline hover:underline" href="/admin/reports">Отчёты</a>
	</p>
{:else}
	<p class="text-stone-500 dark:text-stone-400">Загрузка…</p>
{/if}
