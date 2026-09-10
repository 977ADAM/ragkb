import adapter from '@sveltejs/adapter-node';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		adapter: adapter(),
		csrf: {
			// Загрузка документов — POST multipart/form-data. Kit считает его
			// формой и сравнивает Origin с origin процесса. С LAN-адреса
			// (http://10.10.1.114:3000) проверка отвечает 403 «Cross-site POST
			// form submissions are forbidden». JSON-ручки при этом работают.
			// '*' — эквивалент прежнего checkOrigin: false (доступ с IP LAN).
			trustedOrigins: ['*']
		}
	}
};

export default config;
