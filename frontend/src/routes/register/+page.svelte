<script>
	import { goto } from '$app/navigation';

	let username = $state('');
	let password = $state('');
	let error = $state('');
	let pending = $state(false);

	/** @param {SubmitEvent} event */
	async function submit(event) {
		event.preventDefault();
		error = '';
		pending = true;
		try {
			const response = await fetch('/api/auth/signup', {
				method: 'POST',
				credentials: 'include',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ username, password })
			});
			if (response.ok) {
				await goto('/new');
				return;
			}
			const body = await response.json().catch(() => ({}));
			error = typeof body.detail === 'string' ? body.detail : 'Не удалось зарегистрироваться';
		} catch (err) {
			error = String(err);
		} finally {
			pending = false;
		}
	}
</script>

<h1>Регистрация</h1>
<form onsubmit={submit}>
	<label>
		Имя пользователя
		<input name="username" autocomplete="username" bind:value={username} required />
	</label>
	<label>
		Пароль
		<input name="password" type="password" autocomplete="new-password" bind:value={password} required />
	</label>
	{#if error}
		<p class="error">{error}</p>
	{/if}
	<button type="submit" disabled={pending}>Зарегистрироваться</button>
</form>
<p><a href="/login">Вход</a></p>

<style>
	h1 {
		font-size: 1.25rem;
		margin: 0 0 1rem;
	}
	form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		max-width: 20rem;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		font-size: 0.85rem;
		color: var(--muted, #6b7280);
	}
	input {
		font: inherit;
		padding: 0.4rem 0.5rem;
		border: 1px solid var(--line, #d1d5db);
		border-radius: 0.4rem;
		background: var(--bg, #fff);
		color: inherit;
	}
	.error {
		color: #b91c1c;
		margin: 0;
	}
	button {
		font: inherit;
		padding: 0.5rem 0.9rem;
		border: 1px solid var(--line, #d1d5db);
		border-radius: 0.5rem;
		background: var(--panel, #f3f4f6);
		color: inherit;
		cursor: pointer;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
