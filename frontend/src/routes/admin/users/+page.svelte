<script>
	import { onMount } from 'svelte';

	/** @typedef {{ username: string, role: string, created_at?: string }} AdminUser */

	/** @type {AdminUser[]} */
	let users = $state([]);
	let error = $state('');
	/** @type {string | null} */
	let pending = $state(null);

	onMount(load);

	async function load() {
		error = '';
		try {
			const response = await fetch('/api/admin/users', { credentials: 'include' });
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось загрузить пользователей';
				return;
			}
			users = body.users ?? [];
		} catch (err) {
			error = String(err);
		}
	}

	/**
	 * @param {string} username
	 * @param {string} role
	 */
	async function setRole(username, role) {
		if (pending) return;
		pending = username;
		error = '';
		try {
			const response = await fetch(`/api/admin/users/${encodeURIComponent(username)}`, {
				method: 'PATCH',
				credentials: 'include',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ role })
			});
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось сменить роль';
				return;
			}
			users = users.map((u) => (u.username === username ? { ...u, ...body } : u));
		} catch (err) {
			error = String(err);
		} finally {
			pending = null;
		}
	}
</script>

<h1 class="mb-4 text-xl font-semibold">Пользователи</h1>
{#if error}
	<p class="text-red-600 dark:text-red-400">{error}</p>
{/if}
<table class="w-full border-collapse text-left">
	<thead>
		<tr>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Имя</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Роль</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Создан</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700"></th>
		</tr>
	</thead>
	<tbody>
		{#each users as user (user.username)}
			<tr>
				<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">{user.username}</td>
				<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">{user.role}</td>
				<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">{user.created_at ?? ''}</td>
				<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">
					{#if user.role === 'admin'}
						<button
							class="btn"
							type="button"
							disabled={pending === user.username}
							onclick={() => setRole(user.username, 'user')}>Снять админа</button
						>
					{:else}
						<button
							class="btn"
							type="button"
							disabled={pending === user.username}
							onclick={() => setRole(user.username, 'admin')}>Выдать админа</button
						>
					{/if}
				</td>
			</tr>
		{/each}
	</tbody>
</table>
{#if users.length === 0 && !error}
	<p class="text-stone-500 dark:text-stone-400">Никого нет.</p>
{/if}
