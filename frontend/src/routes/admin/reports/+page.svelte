<script>
	import { onMount } from 'svelte';

	let status = $state('');
	let error = $state('');

	onMount(async () => {
		try {
			const response = await fetch('/api/admin/reports', { credentials: 'include' });
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось проверить отчёты';
				return;
			}
			status = typeof body.status === 'string' ? body.status : '';
		} catch (err) {
			error = String(err);
		}
	});
</script>

<h1>Отчёты</h1>
<p>Отчёты появятся позже. Сейчас аналитики в системе нет.</p>
{#if error}
	<p class="error">{error}</p>
{:else if status === 'unavailable'}
	<p class="muted">Сервис отчётов недоступен.</p>
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
</style>
