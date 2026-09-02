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
			const response = await fetch('/api/auth/profile', { credentials: 'include' });
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
			const response = await fetch('/api/auth/password', {
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

<h1>Профиль</h1>

{#if error}
	<p class="error">{error}</p>
{:else if profile}
	<dl class="facts">
		<dt>Имя пользователя</dt>
		<dd>{profile.username}</dd>
		<dt>Роль</dt>
		<dd>{roleLabel(profile.role)}</dd>
		{#if profile.created_at}
			<dt>Зарегистрирован</dt>
			<dd>{new Date(profile.created_at).toLocaleString()}</dd>
		{/if}
	</dl>

	<h2>Смена пароля</h2>
	<form onsubmit={submit}>
		<label>
			Текущий пароль
			<input
				name="current"
				type="password"
				autocomplete="current-password"
				bind:value={form.current}
				required
			/>
		</label>
		<label>
			Новый пароль
			<input
				name="next"
				type="password"
				autocomplete="new-password"
				minlength="8"
				bind:value={form.next}
				required
			/>
		</label>
		<label>
			Повторите новый пароль
			<input
				name="repeat"
				type="password"
				autocomplete="new-password"
				minlength="8"
				bind:value={form.repeat}
				required
			/>
		</label>
		{#if notice}
			<p class="notice">{notice}</p>
		{/if}
		{#if formError}
			<p class="error">{formError}</p>
		{/if}
		<button type="submit" disabled={busy}>Сменить пароль</button>
	</form>
{/if}

<style>
	h1 {
		font-size: 1.25rem;
		margin: 0 0 1rem;
	}
	h2 {
		font-size: 1.05rem;
		margin: 1.5rem 0 0.75rem;
	}
	.facts {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.25rem 1rem;
		margin: 0;
		font-size: 0.95rem;
	}
	dt {
		color: var(--muted);
	}
	dd {
		margin: 0;
	}
	form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		max-width: 22rem;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		font-size: 0.85rem;
		color: var(--muted);
	}
	input {
		font: inherit;
		padding: 0.4rem 0.5rem;
		border: 1px solid var(--line);
		border-radius: 0.4rem;
		background: var(--bg);
		color: inherit;
	}
	input:focus {
		outline: 2px solid var(--accent);
		outline-offset: 0;
		border-color: transparent;
	}
	.error {
		color: var(--error);
		margin: 0;
	}
	.notice {
		color: var(--accent);
		margin: 0;
	}
	button {
		font: inherit;
		padding: 0.5rem 0.9rem;
		border: 1px solid var(--accent);
		border-radius: 0.5rem;
		background: var(--accent);
		color: var(--accent-contrast);
		cursor: pointer;
		align-self: flex-start;
	}
	button:disabled {
		opacity: 0.55;
		cursor: default;
	}
</style>
