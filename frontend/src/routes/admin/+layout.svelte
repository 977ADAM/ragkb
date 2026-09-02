<script>
	let { children } = $props();
</script>

<div class="admin">
	<nav>
		<a href="/admin">Организация</a>
		<a href="/admin/users">Пользователи</a>
		<a href="/admin/reports">Отчёты</a>
		<a href="/new">К диалогам</a>
	</nav>
	{@render children()}
</div>

<style>
	.admin {
		max-width: 46rem;
		margin: 0 auto;
		padding: 1.5rem 1rem 2rem;
		font: 16px/1.5 system-ui, sans-serif;
	}
	nav {
		display: flex;
		flex-wrap: wrap;
		gap: 1rem;
		margin-bottom: 1.25rem;
	}
	a {
		color: inherit;
	}
</style>
