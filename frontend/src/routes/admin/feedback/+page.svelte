<script>
	import { onMount } from 'svelte';

	/** @typedef {{ conversation_id: string, username: string, rating: 'up' | 'down', comment?: string, answer?: string, created_at?: string }} FeedbackItem */

	/** @type {{ up: number, down: number } | null} */
	let counts = $state(null);
	/** @type {FeedbackItem[]} */
	let items = $state([]);
	let error = $state('');

	onMount(load);

	async function load() {
		error = '';
		try {
			const response = await fetch('/api/admin/feedback', { credentials: 'include' });
			const body = await response.json().catch(() => ({}));
			if (!response.ok) {
				error = typeof body.detail === 'string' ? body.detail : 'Не удалось загрузить оценки';
				return;
			}
			counts = body.counts ?? { up: 0, down: 0 };
			items = body.items ?? [];
		} catch (err) {
			error = String(err);
		}
	}

	/** @param {string} conversationId */
	function openConversation(conversationId) {
		window.location.href = `/chat/${encodeURIComponent(conversationId)}`;
	}
</script>

<h1 class="mb-4 text-xl font-semibold">Оценки ответов</h1>
{#if error}
	<p class="text-red-600 dark:text-red-400">{error}</p>
{/if}
{#if counts}
	<p class="mb-3">
		Полезных ответов: <b>{counts.up}</b> · Не помогли: <b>{counts.down}</b>
	</p>
{/if}
<table class="w-full border-collapse text-left align-top">
	<thead>
		<tr>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Пользователь</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Оценка</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Комментарий</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Ответ</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700">Когда</th>
			<th class="border-b border-stone-300 px-2 py-1.5 dark:border-stone-700"></th>
		</tr>
	</thead>
	<tbody>
		{#each items as item (item.conversation_id + item.created_at)}
			<tr>
				<td class="border-b border-stone-300 px-2 py-1.5 align-top dark:border-stone-700">
					{item.username}
				</td>
				<td
					class="border-b border-stone-300 px-2 py-1.5 align-top dark:border-stone-700 {item.rating ===
					'down'
						? 'text-red-600 dark:text-red-400'
						: ''}"
				>
					{item.rating === 'up' ? '👍' : '👎'}
				</td>
				<td class="border-b border-stone-300 px-2 py-1.5 align-top dark:border-stone-700">
					{item.comment || '—'}
				</td>
				<td
					class="max-w-[28rem] border-b border-stone-300 px-2 py-1.5 align-top text-sm whitespace-pre-wrap dark:border-stone-700"
				>
					{item.answer ?? ''}
				</td>
				<td class="border-b border-stone-300 px-2 py-1.5 align-top dark:border-stone-700">
					{item.created_at ?? ''}
				</td>
				<td class="border-b border-stone-300 px-2 py-1.5 align-top dark:border-stone-700">
					<button class="btn" type="button" onclick={() => openConversation(item.conversation_id)}>
						Открыть диалог
					</button>
				</td>
			</tr>
		{/each}
	</tbody>
</table>
{#if !error && items.length === 0}
	<p class="text-stone-500 dark:text-stone-400">Оценок пока нет.</p>
{/if}
