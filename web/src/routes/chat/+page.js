import { redirect } from '@sveltejs/kit';

// Голый /chat не адресует ничего: диалог всегда указывается идентификатором.
export function load() {
	redirect(307, '/new');
}
