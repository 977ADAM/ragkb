import { proxyJson } from '$lib/server/backend.js';

/** Приём телеметрии пачкой. Устройство чужого пути браузеру знать незачем. */
export async function POST({ request }) {
	return proxyJson('/events', request, {
		method: 'POST',
		body: await request.text()
	});
}
