import { defineConfig } from 'vitest/config';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
			},
			// A static SPA: `sentinel serve` serves build/ and the API from one origin.
			// Unknown paths fall back to index.html, so client-side routes survive a reload.
			adapter: adapter({ fallback: 'index.html' })
		})
	],
	server: {
		// In `npm run dev`, forward API calls to `sentinel serve` (default port 8000).
		proxy: { '/api': 'http://127.0.0.1:8000' }
	},
	test: {
		expect: { requireAssertions: true },
		projects: [
			{
				extends: './vite.config.ts',
				test: {
					name: 'server',
					environment: 'node',
					include: ['src/**/*.{test,spec}.{js,ts}'],
					exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
				}
			}
		]
	}
});
