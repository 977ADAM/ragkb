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

<h1>Оценки ответов</h1>
{#if error}
	<p class="error">{error}</p>
{/if}
{#if counts}
	<p class="counts">
		Полезных ответов: <b>{counts.up}</b> · Не помогли: <b>{counts.down}</b>
	</p>
{/if}
<table>
	<thead>
		<tr>
			<th>Пользователь</th>
			<th>Оценка</th>
			<th>Комментарий</th>
			<th>Ответ</th>
			<th>Когда</th>
			<th></th>
		</tr>
	</thead>
	<tbody>
		{#each items as item (item.conversation_id + item.created_at)}
			<tr>
				<td>{item.username}</td>
				<td class:down={item.rating === 'down'}>{item.rating === 'up' ? '👍' : '👎'}</td>
				<td>{item.comment || '—'}</td>
				<td class="answer">{item.answer ?? ''}</td>
				<td>{item.created_at ?? ''}</td>
				<td>
					<button type="button" onclick={() => openConversation(item.conversation_id)}>
						Открыть диалог
					</button>
				</td>
			</tr>
		{/each}
	</tbody>
</table>
{#if !error && items.length === 0}
	<p class="muted">Оценок пока нет.</p>
{/if}

<style>
	h1 {
		font-size: 1.25rem;
		margin: 0 0 1rem;
	}
	.counts {
		margin: 0 0 0.75rem;
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
		vertical-align: top;
	}
	.down {
		color: #b91c1c;
	}
	.answer {
		max-width: 28rem;
		white-space: pre-wrap;
		font-size: 0.85rem;
	}
	.error {
		color: #b91c1c;
	}
	.muted {
		color: var(--muted, #6b7280);
	}
</style>
