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

<h1>Пользователи</h1>
{#if error}
	<p class="error">{error}</p>
{/if}
<table>
	<thead>
		<tr>
			<th>Имя</th>
			<th>Роль</th>
			<th>Создан</th>
			<th></th>
		</tr>
	</thead>
	<tbody>
		{#each users as user (user.username)}
			<tr>
				<td>{user.username}</td>
				<td>{user.role}</td>
				<td>{user.created_at ?? ''}</td>
				<td>
					{#if user.role === 'admin'}
						<button
							type="button"
							disabled={pending === user.username}
							onclick={() => setRole(user.username, 'user')}>Снять админа</button
						>
					{:else}
						<button
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
	<p class="muted">Никого нет.</p>
{/if}

<style>
	h1 {
		font-size: 1.25rem;
		margin: 0 0 1rem;
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th,
	td {
		text-align: left;
		padding: 0.4rem 0.5rem;
		border-bottom: 1px solid var(--line, #d1d5db);
	}
	.error {
		color: var(--error);
	}
	.muted {
		color: var(--muted, #6b7280);
	}
	button {
		font: inherit;
		padding: 0.35rem 0.7rem;
		border: 1px solid var(--line, #d1d5db);
		border-radius: 0.4rem;
		background: var(--panel, #f3f4f6);
		color: inherit;
		cursor: pointer;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
