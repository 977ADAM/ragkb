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
			const response = await fetch('/api/auths/signin', {
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

<div class="flex min-h-dvh items-center justify-center p-4">
	<div
		class="flex w-full max-w-sm flex-col items-center gap-1.5 rounded-xl border border-stone-300 bg-white p-6 dark:border-stone-700 dark:bg-stone-900"
	>
		<img class="mb-1.5 rounded-2xl" src="/logo.png" alt="" width="72" height="72" />
		<h1 class="m-0 text-xl text-red-600 dark:text-red-400">База знаний</h1>
		<p class="m-0 mb-3 text-sm text-stone-500 dark:text-stone-400">Вход</p>
		<form class="flex w-full flex-col gap-3" onsubmit={submit}>
			<label class="flex flex-col gap-1 text-sm text-stone-500 dark:text-stone-400">
				Имя пользователя
				<input
					class="field"
					name="username"
					autocomplete="username"
					bind:value={username}
					required
				/>
			</label>
			<label class="flex flex-col gap-1 text-sm text-stone-500 dark:text-stone-400">
				Пароль
				<input
					class="field"
					name="password"
					type="password"
					autocomplete="current-password"
					bind:value={password}
					required
				/>
			</label>
			{#if error}
				<p class="m-0 text-sm text-red-600 dark:text-red-400">{error}</p>
			{/if}
			<button class="btn-accent mt-1 py-2.5" type="submit" disabled={pending}>Войти</button>
		</form>
		<p class="mt-3 text-sm"><a class="hover:underline" href="/register">Регистрация</a></p>
	</div>
</div>
