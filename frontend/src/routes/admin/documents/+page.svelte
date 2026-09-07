<script>
	import { onMount } from 'svelte';

	/**
	 * @typedef {{
	 *   name: string,
	 *   size: number,
	 *   mtime: string,
	 *   indexed: boolean,
	 *   chunks: number,
	 *   state: string | null
	 * }} CorpusRow
	 * @typedef {{ title?: string, source?: string, chunks?: number }} Orphan
	 * @typedef {{ corpus_files: number, indexed_docs: number, chunks: number }} Summary
	 */

	/** @type {CorpusRow[]} */
	let corpus = $state([]);
	/** @type {Orphan[]} */
	let orphans = $state([]);
	/** @type {unknown[]} */
	let skipped = $state([]);
	/** @type {Summary | null} */
	let summary = $state(null);
	let error = $state('');
	let busy = $state(false);
	/** @type {HTMLInputElement | undefined} */
	let fileInput = $state();

	onMount(load);

	async function load() {
		error = '';
		try {
			const response = await fetch('/api/admin/documents', { credentials: 'include' });
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось загрузить документы';
				return;
			}
			corpus = body.corpus ?? [];
			orphans = body.orphans ?? [];
			skipped = body.skipped ?? [];
			summary = body.summary ?? null;
		} catch (err) {
			error = String(err);
		}
	}

	/** @param {string | null | undefined} state */
	function stateLabel(state) {
		if (state === 'indexed') return 'в индексе';
		if (state === 'new') return 'новый, не проиндексирован';
		if (state === 'stale') return 'изменён, нужна переиндексация';
		if (state === 'unknown') return 'в индексе (дата неизвестна)';
		return 'индекс не собран';
	}

	/** @param {string | null | undefined} state */
	function stateClass(state) {
		if (state === 'stale') return 'text-amber-600 dark:text-amber-400';
		if (state === 'new') return 'text-red-600 dark:text-red-400';
		return '';
	}

	/** @param {number} bytes */
	function formatSize(bytes) {
		if (!Number.isFinite(bytes)) return '';
		if (bytes < 1024) return `${bytes} Б`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
	}

	/** @param {string | undefined} iso */
	function formatTime(iso) {
		if (!iso) return '';
		const date = new Date(iso);
		return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
	}

	/** @param {unknown} item */
	function skippedPath(item) {
		if (Array.isArray(item)) return String(item[0] ?? '');
		if (item && typeof item === 'object' && 'path' in item) return String(item.path ?? '');
		return String(item ?? '');
	}

	/** @param {unknown} item */
	function skippedReason(item) {
		if (Array.isArray(item)) return String(item[1] ?? '');
		if (item && typeof item === 'object' && 'reason' in item) return String(item.reason ?? '');
		return '';
	}

	/** @param {Event} event */
	async function onPick(event) {
		const input = /** @type {HTMLInputElement} */ (event.currentTarget);
		const file = input.files?.[0];
		input.value = '';
		if (!file || busy) return;
		if (corpus.some((row) => row.name === file.name)) {
			if (!confirm('Файл существует — перезаписать?')) return;
		}
		busy = true;
		error = '';
		try {
			const form = new FormData();
			form.append('file', file);
			const response = await fetch('/api/admin/documents', {
				method: 'POST',
				credentials: 'include',
				body: form
			});
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось загрузить документ';
				return;
			}
			await load();
		} catch (err) {
			error = String(err);
		} finally {
			busy = false;
		}
	}

	/** @param {string} name */
	async function remove(name) {
		if (busy) return;
		if (!confirm(`Удалить «${name}»?`)) return;
		busy = true;
		error = '';
		try {
			const response = await fetch(`/api/admin/documents/${encodeURIComponent(name)}`, {
				method: 'DELETE',
				credentials: 'include'
			});
			if (!response.ok) {
				const body = await response.json().catch(() => ({}));
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось удалить документ';
				return;
			}
			await load();
		} catch (err) {
			error = String(err);
		} finally {
			busy = false;
		}
	}
</script>

<h1 class="mb-4 text-xl font-semibold">Документы</h1>
{#if error}
	<p class="text-red-600 dark:text-red-400">{error}</p>
{/if}
{#if summary}
	<p class="mb-3">
		Файлов: <b>{summary.corpus_files}</b>
		· В индексе: <b>{summary.indexed_docs}</b>
		· Чанков: <b>{summary.chunks}</b>
	</p>
{/if}
<p class="mb-4 flex items-center gap-3">
	<button class="btn" type="button" disabled={busy} onclick={() => fileInput?.click()}>
		Загрузить
	</button>
	<input bind:this={fileInput} type="file" hidden disabled={busy} onchange={onPick} />
	{#if busy}
		<span class="text-stone-500 dark:text-stone-400">Индексация…</span>
	{/if}
</p>
<table class="w-full border-collapse text-left">
	<thead>
		<tr>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Имя</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Состояние</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Размер</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Изменён</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Чанков</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700"></th>
		</tr>
	</thead>
	<tbody>
		{#each corpus as row (row.name)}
			<tr>
				<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">{row.name}</td>
				<td
					class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700 {stateClass(
						row.state
					)}"
				>
					{stateLabel(row.state)}
				</td>
				<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">
					{formatSize(row.size)}
				</td>
				<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">
					{formatTime(row.mtime)}
				</td>
				<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">{row.chunks}</td>
				<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">
					<button class="btn" type="button" disabled={busy} onclick={() => remove(row.name)}>
						Удалить
					</button>
				</td>
			</tr>
		{/each}
	</tbody>
</table>
{#if corpus.length === 0 && !error}
	<p class="text-stone-500 dark:text-stone-400">Документов нет.</p>
{/if}

{#if orphans.length}
	<h2 class="mt-6 mb-1 text-lg font-semibold">Сироты</h2>
	<p class="text-stone-500 dark:text-stone-400">
		документа нет в каталоге — исчезнет при полной переиндексации
	</p>
	<table class="mt-2 w-full border-collapse text-left">
		<thead>
			<tr>
				<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Название</th>
				<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Источник</th>
				<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Чанки</th>
			</tr>
		</thead>
		<tbody>
			{#each orphans as orphan, i (orphan.source ?? i)}
				<tr>
					<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">
						{orphan.title ?? ''}
					</td>
					<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">
						{orphan.source ?? ''}
					</td>
					<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">
						{orphan.chunks ?? 0}
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}

{#if skipped.length}
	<h2 class="mt-6 mb-1 text-lg font-semibold">Пропущено при сборке</h2>
	<ul class="list-disc pl-5 text-stone-500 dark:text-stone-400">
		{#each skipped as item, i (i)}
			<li>
				{skippedPath(item)}{skippedReason(item) ? ` — ${skippedReason(item)}` : ''}
			</li>
		{/each}
	</ul>
{/if}
