<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	/** @type {{ username?: string, role?: string, created_at?: string | null } | null} */
	let profile = $state(null);
	let error = $state('');

	onMount(load);

	async function load() {
		error = '';
		try {
			const response = await fetch('/api/auths/profile', { credentials: 'include' });
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось загрузить профиль';
				if (response.status === 401) goto('/login');
				return;
			}
			profile = body;
		} catch (err) {
			error = String(err);
		}
	}

	/** @param {string | undefined} role */
	function roleLabel(role) {
		if (role === 'admin') return 'Администратор';
		if (role === 'user') return 'Пользователь';
		return role ?? '';
	}

	/** @type {{ current: string, next: string, repeat: string }} */
	let form = $state({ current: '', next: '', repeat: '' });
	let busy = $state(false);
	let notice = $state('');
	let formError = $state('');

	/** @param {SubmitEvent} event */
	async function submit(event) {
		event.preventDefault();
		formError = '';
		notice = '';
		if (form.next !== form.repeat) {
			formError = 'Повтор нового пароля не совпадает';
			return;
		}
		busy = true;
		try {
			const response = await fetch('/api/auths/password', {
				method: 'POST',
				credentials: 'include',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({
					current_password: form.current,
					new_password: form.next
				})
			});
			if (response.ok) {
				form = { current: '', next: '', repeat: '' };
				notice = 'Пароль изменён. Остальные сессии закрыты.';
				return;
			}
			const body = await response.json().catch(() => ({}));
			formError = typeof body.detail === 'string' ? body.detail : `Ошибка ${response.status}`;
		} catch (err) {
			formError = String(err);
		} finally {
			busy = false;
		}
	}
</script>

<h1 class="mb-4 text-xl font-semibold">Профиль</h1>

{#if error}
	<p class="text-red-600 dark:text-red-400">{error}</p>
{:else if profile}
	<dl class="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[0.95rem]">
		<dt class="text-stone-500 dark:text-stone-400">Имя пользователя</dt>
		<dd class="m-0">{profile.username}</dd>
		<dt class="text-stone-500 dark:text-stone-400">Роль</dt>
		<dd class="m-0">{roleLabel(profile.role)}</dd>
		{#if profile.created_at}
			<dt class="text-stone-500 dark:text-stone-400">Зарегистрирован</dt>
			<dd class="m-0">{new Date(profile.created_at).toLocaleString()}</dd>
		{/if}
	</dl>

	<h2 class="mt-6 mb-3 text-base font-semibold">Смена пароля</h2>
	<form class="flex max-w-md flex-col gap-3" onsubmit={submit}>
		<label class="flex flex-col gap-1 text-sm text-stone-500 dark:text-stone-400">
			Текущий пароль
			<input
				class="field"
				name="current"
				type="password"
				autocomplete="current-password"
				bind:value={form.current}
				required
			/>
		</label>
		<label class="flex flex-col gap-1 text-sm text-stone-500 dark:text-stone-400">
			Новый пароль
			<input
				class="field"
				name="next"
				type="password"
				autocomplete="new-password"
				minlength="8"
				bind:value={form.next}
				required
			/>
		</label>
		<label class="flex flex-col gap-1 text-sm text-stone-500 dark:text-stone-400">
			Повторите новый пароль
			<input
				class="field"
				name="repeat"
				type="password"
				autocomplete="new-password"
				minlength="8"
				bind:value={form.repeat}
				required
			/>
		</label>
		{#if notice}
			<p class="m-0 text-sm text-red-600 dark:text-red-400">{notice}</p>
		{/if}
		{#if formError}
			<p class="m-0 text-sm text-red-600 dark:text-red-400">{formError}</p>
		{/if}
		<button class="btn-accent w-fit" type="submit" disabled={busy}>Сменить пароль</button>
	</form>
{/if}
