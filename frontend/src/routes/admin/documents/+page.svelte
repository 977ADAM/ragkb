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

<h1>Документы</h1>
{#if error}
	<p class="error">{error}</p>
{/if}
{#if summary}
	<p class="counts">
		Файлов: <b>{summary.corpus_files}</b>
		· В индексе: <b>{summary.indexed_docs}</b>
		· Чанков: <b>{summary.chunks}</b>
	</p>
{/if}
<p class="toolbar">
	<button type="button" disabled={busy} onclick={() => fileInput?.click()}>Загрузить</button>
	<input bind:this={fileInput} type="file" hidden disabled={busy} onchange={onPick} />
	{#if busy}
		<span class="muted">Индексация…</span>
	{/if}
</p>
<table>
	<thead>
		<tr>
			<th>Имя</th>
			<th>Состояние</th>
			<th>Размер</th>
			<th>Изменён</th>
			<th>Чанков</th>
			<th></th>
		</tr>
	</thead>
	<tbody>
		{#each corpus as row (row.name)}
			<tr>
				<td>{row.name}</td>
				<td>{stateLabel(row.state)}</td>
				<td>{formatSize(row.size)}</td>
				<td>{formatTime(row.mtime)}</td>
				<td>{row.chunks}</td>
				<td>
					<button type="button" disabled={busy} onclick={() => remove(row.name)}>Удалить</button>
				</td>
			</tr>
		{/each}
	</tbody>
</table>
{#if corpus.length === 0 && !error}
	<p class="muted">Документов нет.</p>
{/if}

{#if orphans.length}
	<h2>Сироты</h2>
	<p class="muted">документа нет в каталоге — исчезнет при полной переиндексации</p>
	<table>
		<thead>
			<tr>
				<th>Название</th>
				<th>Источник</th>
				<th>Чанки</th>
			</tr>
		</thead>
		<tbody>
			{#each orphans as orphan, i (orphan.source ?? i)}
				<tr>
					<td>{orphan.title ?? ''}</td>
					<td>{orphan.source ?? ''}</td>
					<td>{orphan.chunks ?? 0}</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}

{#if skipped.length}
	<h2>Пропущено при сборке</h2>
	<ul>
		{#each skipped as item, i (i)}
			<li>{skippedPath(item)}{skippedReason(item) ? ` — ${skippedReason(item)}` : ''}</li>
		{/each}
	</ul>
{/if}

<style>
	h1 {
		font-size: 1.25rem;
		margin: 0 0 1rem;
	}
	h2 {
		font-size: 1.1rem;
		margin: 1.5rem 0 0.5rem;
	}
	.counts {
		margin: 0 0 0.75rem;
	}
	.toolbar {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		margin: 0 0 1rem;
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th,
	td {
		text-align: left;
		padding: 0.4rem 0.5rem;
		border-bottom: 1px solid var(--line, #d1d5db);
	}
	.error {
		color: var(--error);
	}
	.muted {
		color: var(--muted, #6b7280);
	}
	button {
		font: inherit;
		padding: 0.35rem 0.7rem;
		border: 1px solid var(--line, #d1d5db);
		border-radius: 0.4rem;
		background: var(--panel, #f3f4f6);
		color: inherit;
		cursor: pointer;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
