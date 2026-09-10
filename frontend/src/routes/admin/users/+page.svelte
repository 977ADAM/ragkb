<script>
	import { onMount } from 'svelte';

	/** @typedef {{ username: string, role: string, created_at?: string }} AdminUser */

	/** @type {AdminUser[]} */
	let users = $state([]);
	let error = $state('');
	/** @type {string | null} */
	let pending = $state(null);
	let newName = $state('');
	let newPassword = $state('');
	let newRole = $state('user');

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

	async function create() {
		if (pending) return;
		pending = 'create';
		error = '';
		try {
			const response = await fetch('/api/admin/users', {
				method: 'POST',
				credentials: 'include',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({
					username: newName,
					password: newPassword,
					role: newRole
				})
			});
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось создать пользователя';
				return;
			}
			users = [...users, body];
			newName = '';
			newPassword = '';
			newRole = 'user';
		} catch (err) {
			error = String(err);
		} finally {
			pending = null;
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
<form
	class="mb-4 flex max-w-lg flex-col gap-2"
	onsubmit={(event) => {
		event.preventDefault();
		create();
	}}
>
	<h2 class="text-base font-medium">Создать</h2>
	<label class="flex flex-col gap-1 text-sm text-stone-500 dark:text-stone-400">
		Имя пользователя
		<input class="field" name="username" autocomplete="off" bind:value={newName} required />
	</label>
	<label class="flex flex-col gap-1 text-sm text-stone-500 dark:text-stone-400">
		Пароль
		<input
			class="field"
			name="password"
			type="password"
			autocomplete="new-password"
			bind:value={newPassword}
			required
		/>
	</label>
	<label class="flex flex-col gap-1 text-sm text-stone-500 dark:text-stone-400">
		Роль
		<select class="field" bind:value={newRole}>
			<option value="user">user</option>
			<option value="admin">admin</option>
		</select>
	</label>
	<button class="btn-accent self-start" type="submit" disabled={pending !== null}>Создать</button>
</form>
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
