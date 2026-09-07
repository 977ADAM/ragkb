<script>
	let { children } = $props();
</script>

<div class="mx-auto max-w-[46rem] px-4 py-6 pb-8">
	<nav class="mb-5 flex flex-wrap gap-4">
		<a class="no-underline hover:underline" href="/admin">Организация</a>
		<a class="no-underline hover:underline" href="/admin/users">Пользователи</a>
		<a class="no-underline hover:underline" href="/admin/documents">Документы</a>
		<a class="no-underline hover:underline" href="/admin/reports">Отчёты</a>
		<a class="no-underline hover:underline" href="/new">К диалогам</a>
	</nav>
	{@render children()}
</div>
