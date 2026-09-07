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

<h1 class="mb-4 text-xl font-semibold">Отчёты</h1>
<p>Отчёты появятся позже. Сейчас аналитики в системе нет.</p>
{#if error}
	<p class="text-red-600 dark:text-red-400">{error}</p>
{:else if status === 'unavailable'}
	<p class="text-stone-500 dark:text-stone-400">Сервис отчётов недоступен.</p>
{/if}
