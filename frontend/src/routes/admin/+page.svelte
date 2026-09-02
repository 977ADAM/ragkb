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

<h1>{org?.name || 'Организация'}</h1>
{#if error}
	<p class="error">{error}</p>
{:else if org}
	{#if org.description}
		<p>{org.description}</p>
	{/if}
	{#if org.id}
		<p class="muted">Идентификатор: {org.id}</p>
	{/if}
	<p>
		<a href="/admin/users">Пользователи</a>
		·
		<a href="/admin/reports">Отчёты</a>
	</p>
{:else}
	<p class="muted">Загрузка…</p>
{/if}

<style>
	h1 {
		font-size: 1.25rem;
		margin: 0 0 1rem;
	}
	.muted {
		color: var(--muted, #6b7280);
	}
	.error {
		color: #b91c1c;
	}
	a {
		color: inherit;
	}
</style>
