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
			const response = await fetch('/api/auth/signin', {
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
			error = typeof body.detail === 'string' ? body.detail : 'Не удалось войти';
		} catch (err) {
			error = String(err);
		} finally {
			pending = false;
		}
	}
</script>

<svelte:head>
	<title>Вход — База знаний</title>
</svelte:head>

<div class="page">
	<div class="card">
		<img class="logo" src="/logo.png" alt="" width="72" height="72" />
		<h1>База знаний</h1>
		<p class="subtitle">Вход</p>
		<form onsubmit={submit}>
			<label>
				Имя пользователя
				<input name="username" autocomplete="username" bind:value={username} required />
			</label>
			<label>
				Пароль
				<input name="password" type="password" autocomplete="current-password" bind:value={password} required />
			</label>
			{#if error}
				<p class="error">{error}</p>
			{/if}
			<button type="submit" disabled={pending}>Войти</button>
		</form>
		<p class="switch"><a href="/register">Регистрация</a></p>
	</div>
</div>

<style>
	.page {
		min-height: 100dvh;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 1rem;
		box-sizing: border-box;
	}
	.card {
		width: 100%;
		max-width: 21rem;
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 0.9rem;
		padding: 1.6rem 1.5rem;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.4rem;
	}
	.logo {
		border-radius: 1rem;
		margin-bottom: 0.4rem;
	}
	h1 {
		font-size: 1.35rem;
		margin: 0;
		color: var(--accent);
	}
	.subtitle {
		margin: 0 0 0.9rem;
		color: var(--muted);
		font-size: 0.9rem;
	}
	form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		width: 100%;
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
		padding: 0.45rem 0.55rem;
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
		font-size: 0.85rem;
	}
	button {
		font: inherit;
		padding: 0.55rem 0.9rem;
		border: 1px solid var(--accent);
		border-radius: 0.5rem;
		background: var(--accent);
		color: var(--accent-contrast);
		cursor: pointer;
		margin-top: 0.2rem;
	}
	button:hover:not(:disabled) {
		filter: brightness(1.08);
	}
	button:disabled {
		opacity: 0.55;
		cursor: default;
	}
	.switch {
		margin: 0.9rem 0 0;
		font-size: 0.85rem;
	}
	a {
		color: var(--accent);
	}
</style>
