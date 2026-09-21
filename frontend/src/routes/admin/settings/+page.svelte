<script>
	import { onMount } from 'svelte';

	/**
	 * @typedef {{
	 *   path: string, label: string, kind: string, help: string, options: string[],
	 *   minimum: number | null, maximum: number | null, requires: string | null,
	 *   secret: boolean, value: any, default: any, source: string
	 * }} Field
	 * @typedef {{ title: string, fields: Field[] }} Group
	 * @typedef {{ path: string, label: string, help: string, value: any }} ReadonlyField
	 * @typedef {{ status: string, chunks?: number, documents?: number, embedder?: string,
	 *   store?: string, stale?: boolean, warnings?: string[], detail?: string }} IndexState
	 * @typedef {{ file: string, groups: Group[], readonly: ReadonlyField[],
	 *   overridden: string[], index: IndexState }} Payload
	 */

	/** @type {Payload | null} */
	let data = $state(null);
	/** Значения формы: строка/число/флаг по пути поля. @type {Record<string, any>} */
	let draft = $state({});
	/** Поля, у которых снято переопределение. @type {string[]} */
	let resetting = $state([]);
	let loading = $state(true);
	let saving = $state(false);
	let rebuilding = $state(false);
	let error = $state('');
	let notice = $state('');

	onMount(load);

	async function load() {
		loading = true;
		error = '';
		try {
			const response = await fetch('/api/admin/settings', { credentials: 'include' });
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось загрузить настройки';
				return;
			}
			apply(body);
		} catch (err) {
			error = String(err);
		} finally {
			loading = false;
		}
	}

	/** @param {Payload} body */
	function apply(body) {
		data = body;
		draft = {};
		for (const group of body.groups) {
			for (const field of group.fields) draft[field.path] = field.value;
		}
		resetting = [];
	}

	/**
	 * Поля, значения которых разошлись с сохранёнными. Секреты пропускаем:
	 * их значение всегда приходит маской, и сравнивать его не с чем.
	 * @param {Payload} payload
	 * @returns {string[]}
	 */
	function dirtyPaths(payload) {
		/** @type {string[]} */
		const paths = [];
		for (const group of payload.groups) {
			for (const field of group.fields) {
				if (field.secret) continue;
				if (draft[field.path] !== field.value) paths.push(field.path);
			}
		}
		return paths;
	}

	/** @type {string[]} */
	let dirty = $derived(data ? dirtyPaths(data) : []);

	/** @type {number} */
	let changedCount = $derived(dirty.length + resetting.length);

	/** @param {Field} field */
	function toggleReset(field) {
		if (resetting.includes(field.path)) {
			resetting = resetting.filter((path) => path !== field.path);
			draft[field.path] = field.value;
			return;
		}
		resetting = [...resetting, field.path];
		draft[field.path] = field.default;
	}

	async function save() {
		saving = true;
		error = '';
		notice = '';
		try {
			/** @type {Record<string, any>} */
			const values = {};
			for (const path of dirty) values[path] = draft[path];
			const response = await fetch('/api/admin/settings', {
				method: 'PUT',
				credentials: 'include',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ values, reset: resetting })
			});
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось сохранить настройки';
				return;
			}
			apply(body);
			const parts = [];
			if (body.changed?.length) parts.push(`изменено полей: ${body.changed.length}`);
			if (body.requirements?.reindex) parts.push('нужна пересборка индекса');
			if (body.requirements?.restart) parts.push('часть полей применится после перезапуска');
			notice = parts.length ? `Сохранено: ${parts.join(', ')}.` : 'Изменений не было.';
		} catch (err) {
			error = String(err);
		} finally {
			saving = false;
		}
	}

	async function rebuild() {
		rebuilding = true;
		error = '';
		notice = '';
		try {
			const response = await fetch('/api/index/rebuild', {
				method: 'POST',
				credentials: 'include'
			});
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось пересобрать индекс';
				return;
			}
			notice = `Индекс пересобран: файлов ${body.files}, чанков ${body.chunks}, ${body.elapsed_sec} с.`;
			await load();
		} catch (err) {
			error = String(err);
		} finally {
			rebuilding = false;
		}
	}

	/** @param {string} source */
	function sourceLabel(source) {
		if (source === 'settings') return 'изменено здесь';
		if (source === 'env') return 'из окружения';
		return 'по умолчанию';
	}

	/** @param {string | null} requires */
	function requiresLabel(requires) {
		if (requires === 'reindex') return 'нужна пересборка индекса';
		if (requires === 'restart') return 'применится при перезапуске';
		return '';
	}

	/** @param {Field} field */
	function inputType(field) {
		if (field.kind === 'number') return 'number';
		if (field.kind === 'secret') return 'password';
		return 'text';
	}
</script>

<div class="mb-5 flex flex-wrap items-center gap-3">
	<h1 class="m-0 text-xl font-semibold">Настройки</h1>
	{#if changedCount > 0}
		<span class="rounded-md bg-amber-100 px-2 py-0.5 text-sm dark:bg-amber-900">
			не сохранено: {changedCount}
		</span>
	{/if}
	<button class="btn ml-auto" onclick={save} disabled={saving || changedCount === 0}>
		{saving ? 'Сохранение…' : 'Сохранить'}
	</button>
</div>

{#if loading}
	<p class="text-stone-500 dark:text-stone-400">Загрузка…</p>
{:else if error && !data}
	<p class="text-red-600 dark:text-red-400">{error}</p>
{:else if data}
	{#if error}
		<p class="mb-3 rounded-md border border-red-500 bg-red-50 p-2 text-sm dark:bg-red-950">{error}</p>
	{/if}
	{#if notice}
		<p class="mb-3 rounded-md border border-green-600 bg-green-50 p-2 text-sm dark:bg-green-950">
			{notice}
		</p>
	{/if}

	<section class="mb-5 rounded-md border border-stone-300 p-3 text-sm dark:border-stone-700">
		<h2 class="m-0 mb-1 text-base font-semibold">Индекс</h2>
		{#if data.index.status === 'ok'}
			<p class="m-0">
				Собран: {data.index.documents} док., {data.index.chunks} чанков, эмбеддер
				<code>{data.index.embedder}</code>, хранилище <code>{data.index.store}</code>.
			</p>
			{#if data.index.stale}
				<ul class="m-0 mt-2 list-none p-0 text-amber-700 dark:text-amber-400">
					{#each data.index.warnings ?? [] as warning}
						<li>• {warning}</li>
					{/each}
				</ul>
				<button class="btn mt-2" onclick={rebuild} disabled={rebuilding}>
					{rebuilding ? 'Пересборка…' : 'Перестроить индекс'}
				</button>
			{/if}
		{:else}
			<p class="m-0 text-amber-700 dark:text-amber-400">
				Индекс не собран: {data.index.detail ?? 'нет манифеста'}
			</p>
			<button class="btn mt-2" onclick={rebuild} disabled={rebuilding}>
				{rebuilding ? 'Пересборка…' : 'Собрать индекс'}
			</button>
		{/if}
		<p class="m-0 mt-2 text-stone-500 dark:text-stone-400">
			Значения хранятся в <code>{data.file}</code> и перекрывают окружение.
		</p>
	</section>

	{#each data.groups as group (group.title)}
		<section class="mb-5">
			<h2 class="mb-2 text-base font-semibold">{group.title}</h2>
			<div class="flex flex-col gap-3">
				{#each group.fields as field (field.path)}
					{@const wasReset = resetting.includes(field.path)}
					<div class="grid gap-1 sm:grid-cols-[16rem_1fr] sm:items-start sm:gap-3">
						<div>
							<label class="font-medium" for={field.path}>{field.label}</label>
							<div class="text-xs text-stone-500 dark:text-stone-400">
								<code>{field.path}</code>
							</div>
						</div>
						<div>
							{#if field.kind === 'boolean'}
								<label class="flex items-center gap-2">
									<input
										id={field.path}
										type="checkbox"
										bind:checked={draft[field.path]}
										disabled={wasReset}
									/>
									<span class="text-sm">{draft[field.path] ? 'включено' : 'выключено'}</span>
								</label>
							{:else if field.kind === 'select'}
								<select id={field.path} bind:value={draft[field.path]} disabled={wasReset}>
									{#each field.options as option}
										<option value={option}>{option}</option>
									{/each}
								</select>
							{:else if field.kind === 'textarea'}
								<textarea
									id={field.path}
									rows="2"
									class="w-full"
									bind:value={draft[field.path]}
									disabled={wasReset}
								></textarea>
							{:else}
								<input
									id={field.path}
									type={inputType(field)}
									class="w-full sm:max-w-md"
									min={field.minimum ?? undefined}
									max={field.maximum ?? undefined}
									step="any"
									placeholder={field.secret && field.value ? 'задан' : ''}
									bind:value={draft[field.path]}
									disabled={wasReset}
								/>
							{/if}

							<div class="mt-1 flex flex-wrap items-center gap-2 text-xs">
								<span class="text-stone-500 dark:text-stone-400">{sourceLabel(field.source)}</span>
								{#if field.requires}
									<span class="rounded bg-stone-200 px-1.5 py-0.5 dark:bg-stone-800">
										{requiresLabel(field.requires)}
									</span>
								{/if}
								{#if field.source === 'settings' || wasReset}
									<button
										class="cursor-pointer border-0 bg-transparent p-0 text-red-600 underline dark:text-red-400"
										onclick={() => toggleReset(field)}
									>
										{wasReset ? 'вернуть изменение' : `сбросить (будет ${field.default || 'пусто'})`}
									</button>
								{/if}
							</div>
							{#if field.help}
								<p class="m-0 mt-1 text-xs text-stone-500 dark:text-stone-400">{field.help}</p>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</section>
	{/each}

	<section class="mb-5">
		<h2 class="mb-2 text-base font-semibold">Задано вне интерфейса</h2>
		<ul class="m-0 list-none p-0 text-sm">
			{#each data.readonly as item (item.path)}
				<li class="border-b border-stone-200 py-1 dark:border-stone-800">
					<span class="font-medium">{item.label}:</span>
					<code>{item.value || '—'}</code>
					<div class="text-xs text-stone-500 dark:text-stone-400">{item.help}</div>
				</li>
			{/each}
		</ul>
	</section>
{/if}
