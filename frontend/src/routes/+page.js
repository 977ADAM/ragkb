import { redirect } from '@sveltejs/kit';

// Корень — это всегда новый диалог: показывать на нём чужое состояние нечего.
export function load() {
	redirect(307, '/new');
}
