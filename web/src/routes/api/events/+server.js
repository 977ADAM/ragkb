import { proxyJson } from '$lib/server/backend.js';

/** Приём телеметрии пачкой. Устройство чужого пути браузеру знать незачем. */
export async function POST({ request }) {
	return proxyJson('/event_logging/v1/batch', request, {
		method: 'POST',
		body: await request.text()
	});
}
