<script>
	import { onMount } from 'svelte';

	/**
	 * @typedef {{
	 *   name: string,
	 *   size: number,
	 *   mtime: string,
	 *   indexed: boolean,
	 *   chunks: number,
	 *   state: string | null,
	 *   registered: boolean,
	 *   origin: string | null,
	 *   uploaded_by: string,
	 *   uploaded_at: string
	 * }} CorpusRow
	 * @typedef {{ title?: string, source?: string, chunks?: number }} Orphan
	 * @typedef {{ corpus_files: number, indexed_docs: number, chunks: number, external_files: number }} Summary
	 * @typedef {{
	 *   id: string, name: string, size: number, file: File,
	 *   status: 'wait' | 'upload' | 'done' | 'error', percent: number, error: string
	 * }} QueueItem
	 * @typedef {{ files?: number, chunks?: number, excluded?: string[], accepted?: string[], elapsed_sec?: number }} Report
	 */

	/** @type {CorpusRow[]} */
	let corpus = $state([]);
	/** @type {Orphan[]} */
	let orphans = $state([]);
	/** @type {unknown[]} */
	let skipped = $state([]);
	/** @type {Summary | null} */
	let summary = $state(null);
	let registryOn = $state(true);
	let error = $state('');
	let busy = $state(false);
	/** @type {HTMLInputElement | undefined} */
	let fileInput = $state();

	/** Очередь загрузки: каждый файл со своим состоянием и прогрессом. */
	/** @type {QueueItem[]} */
	let queue = $state([]);
	let uploading = $state(false);
	let indexing = $state(false);
	let accepting = $state(false);
	let dragging = $state(false);
	/** @type {Report | null} */
	let report = $state(null);

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
			registryOn = body.registry !== 'off';
		} catch (err) {
			error = String(err);
		}
	}

	const external = $derived(corpus.filter((row) => row.state === 'external'));

	/** @param {string | null | undefined} state */
	function stateLabel(state) {
		if (state === 'indexed') return 'в индексе';
		if (state === 'new') return 'ожидает индексации';
		if (state === 'stale') return 'изменён, нужна переиндексация';
		if (state === 'unknown') return 'в индексе (дата неизвестна)';
		if (state === 'external') return 'вне корпуса — в индекс не попадёт';
		return 'индекс не собран';
	}

	/** @param {string | null | undefined} state */
	function stateClass(state) {
		if (state === 'stale') return 'text-amber-600 dark:text-amber-400';
		if (state === 'new') return 'text-red-600 dark:text-red-400';
		if (state === 'external') return 'text-amber-600 dark:text-amber-400';
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

	/** @param {QueueItem} item */
	function queueStatus(item) {
		if (item.status === 'wait') return 'в очереди';
		if (item.status === 'upload') return `загрузка ${item.percent}%`;
		if (item.status === 'done') return 'загружен';
		return item.error || 'ошибка';
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

	/** @param {FileList | File[] | null | undefined} list */
	function enqueue(list) {
		const files = Array.from(list ?? []);
		if (!files.length || uploading) return;
		const clashes = files.filter((file) => corpus.some((row) => row.name === file.name));
		if (clashes.length) {
			const names = clashes.map((file) => file.name).join(', ');
			if (!confirm(`Эти документы уже есть в корпусе и будут заменены: ${names}. Продолжить?`)) {
				return;
			}
		}
		for (const file of files) {
			queue.push({
				id: crypto.randomUUID(),
				name: file.name,
				size: file.size,
				file,
				status: 'wait',
				percent: 0,
				error: ''
			});
		}
		run();
	}

	/**
	 * Загружает очередь последовательно и пересобирает индекс один раз.
	 *
	 * Индексация — самая дорогая часть, поэтому её делаем в конце пачки,
	 * а не после каждого файла.
	 */
	async function run() {
		if (uploading) return;
		uploading = true;
		error = '';
		try {
			let uploaded = 0;
			for (const item of queue) {
				if (item.status !== 'wait') continue;
				item.status = 'upload';
				try {
					await uploadFile(item);
					item.status = 'done';
					item.percent = 100;
					uploaded += 1;
				} catch (err) {
					item.status = 'error';
					item.error = err instanceof Error ? err.message : String(err);
				}
			}
			if (uploaded) await reindex();
		} finally {
			uploading = false;
			await load();
		}
	}

	/** @param {QueueItem} item */
	function uploadFile(item) {
		return new Promise((resolve, reject) => {
			const request = new XMLHttpRequest();
			// index=false: файл принимается сразу, сборка будет одна на пачку.
			request.open('POST', '/api/admin/documents?index=false');
			request.withCredentials = true;
			request.upload.onprogress = (event) => {
				if (event.lengthComputable) {
					item.percent = Math.round((event.loaded / event.total) * 100);
				}
			};
			request.onload = () => {
				/** @type {{ detail?: string }} */
				let body = {};
				try {
					body = JSON.parse(request.responseText);
				} catch {
					body = {};
				}
				if (request.status >= 200 && request.status < 300) resolve(body);
				else reject(new Error(body.detail || `Ошибка ${request.status}`));
			};
			request.onerror = () => reject(new Error('Сеть недоступна'));
			const form = new FormData();
			form.append('file', item.file);
			request.send(form);
		});
	}

	async function reindex() {
		indexing = true;
		try {
			const response = await fetch('/api/index/rebuild', {
				method: 'POST',
				credentials: 'include'
			});
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error =
					typeof body.detail === 'string' ? body.detail : 'Не удалось перестроить индекс';
				return;
			}
			report = body;
		} catch (err) {
			error = String(err);
		} finally {
			indexing = false;
			await load();
		}
	}

	/** @param {string[]} names */
	async function accept(names) {
		if (!names.length || accepting) return;
		accepting = true;
		error = '';
		try {
			const response = await fetch('/api/admin/documents/accept', {
				method: 'POST',
				credentials: 'include',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ names })
			});
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error =
					typeof body.detail === 'string' ? body.detail : 'Не удалось принять документы';
				return;
			}
			report = body;
		} catch (err) {
			error = String(err);
		} finally {
			accepting = false;
			await load();
		}
	}

	/** @param {string} name */
	async function remove(name) {
		if (busy) return;
		if (!confirm(`Удалить «${name}»? Файл и запись индекса будут удалены.`)) return;
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

	/** @param {DragEvent} event */
	function onDrop(event) {
		event.preventDefault();
		dragging = false;
		enqueue(event.dataTransfer?.files);
	}

	function clearFinished() {
		queue = queue.filter((item) => item.status === 'wait' || item.status === 'upload');
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
		{#if summary.external_files}
			· Вне корпуса: <b>{summary.external_files}</b>
		{/if}
	</p>
{/if}

{#if !registryOn}
	<p class="mb-3 rounded-md border border-amber-500 bg-amber-50 p-2 text-sm dark:bg-amber-950">
		Реестр документов недоступен (нет базы данных), поэтому индексируется весь каталог:
		в базу знаний попадёт и то, что положили мимо интерфейса. Задайте
		<code>RAGKB_DATABASE_URL</code>, чтобы работала загрузка только через интерфейс.
	</p>
{/if}

{#if external.length}
	<div class="mb-4 rounded-md border border-amber-500 bg-amber-50 p-3 text-sm dark:bg-amber-950">
		<p class="m-0">
			<b>{external.length}</b> документ(ов) лежат в каталоге корпуса мимо интерфейса — в индекс
			они не попадут, пока их не примут.
		</p>
		<button
			class="btn mt-2"
			type="button"
			disabled={accepting || busy}
			onclick={() => accept(external.map((row) => row.name))}
		>
			Принять все в корпус
		</button>
	</div>
{/if}

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="mb-4 rounded-lg border-2 border-dashed p-4 text-center transition-colors {dragging
		? 'border-red-500 bg-red-50 dark:bg-red-950/40'
		: 'border-stone-300 dark:border-stone-700'}"
	role="button"
	tabindex="0"
	aria-label="Загрузить документы"
	onclick={() => fileInput?.click()}
	onkeydown={(event) => {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			fileInput?.click();
		}
	}}
	ondragover={(event) => {
		event.preventDefault();
		dragging = true;
	}}
	ondragleave={() => (dragging = false)}
	ondrop={onDrop}
>
	<p class="m-0">
		Перетащите файлы сюда или <span class="text-red-600 underline dark:text-red-400">выберите</span
		>
	</p>
	<p class="m-0 mt-1 text-sm text-stone-500 dark:text-stone-400">
		Можно несколько сразу: они встанут в очередь, индекс пересоберётся один раз в конце
	</p>
	<input
		bind:this={fileInput}
		type="file"
		multiple
		hidden
		disabled={uploading || indexing}
		onchange={(event) => {
			const input = /** @type {HTMLInputElement} */ (event.currentTarget);
			const files = input.files;
			input.value = '';
			enqueue(files);
		}}
	/>
</div>

{#if indexing}
	<p class="mb-3 text-stone-500 dark:text-stone-400">Индексация…</p>
{/if}
{#if report && !indexing}
	<p class="mb-3 text-sm text-stone-500 dark:text-stone-400">
		{#if report.accepted}
			Принято документов: <b>{report.accepted.length}</b>.
		{/if}
		Проиндексировано файлов: <b>{report.files ?? 0}</b>, чанков: <b>{report.chunks ?? 0}</b>, за
		<b>{report.elapsed_sec ?? 0}</b> с.
		{#if report.excluded?.length}
			Вне корпуса осталось: <b>{report.excluded.length}</b>.
		{/if}
	</p>
{/if}

{#if queue.length}
	<div class="mb-4">
		<div class="mb-1 flex items-center gap-3">
			<h2 class="m-0 text-lg font-semibold">Очередь загрузки</h2>
			<button
				class="btn"
				type="button"
				disabled={uploading}
				onclick={clearFinished}
			>
				Очистить список
			</button>
		</div>
		<ul class="m-0 list-none p-0">
			{#each queue as item (item.id)}
				<li class="flex items-center gap-2 border-b border-stone-200 py-1 dark:border-stone-800">
					<span class="min-w-0 flex-1 truncate">{item.name}</span>
					<span class="w-20 text-right text-sm text-stone-500 dark:text-stone-400">
						{formatSize(item.size)}
					</span>
					<span
						class="w-56 text-sm {item.status === 'error'
							? 'text-red-600 dark:text-red-400'
							: 'text-stone-500 dark:text-stone-400'}"
					>
						{queueStatus(item)}
					</span>
				</li>
			{/each}
		</ul>
	</div>
{/if}

<table class="w-full border-collapse text-left">
	<thead>
		<tr>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Имя</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Состояние</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Кто загрузил</th>
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
					{row.uploaded_by || '—'}
					{#if row.origin === 'external'}
						<span class="text-xs text-stone-500 dark:text-stone-400">(принят из каталога)</span>
					{/if}
				</td>
				<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">
					{formatSize(row.size)}
				</td>
				<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">
					{formatTime(row.mtime)}
				</td>
				<td class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">{row.chunks}</td>
				<td
					class="border-b border-stone-300 px-2 py-1.5 whitespace-nowrap dark:border-stone-700"
				>
					{#if row.state === 'external'}
						<button
							class="btn mr-1"
							type="button"
							disabled={accepting || busy}
							onclick={() => accept([row.name])}
						>
							Принять
						</button>
					{/if}
					<button class="btn" type="button" disabled={busy || accepting} onclick={() => remove(row.name)}>
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
