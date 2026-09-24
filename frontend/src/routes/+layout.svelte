<script lang="ts">
	import { resolve } from '$app/paths';
	import '../app.css';
	import { page } from '$app/state';
	import favicon from '$lib/assets/favicon.svg';

	let { children } = $props();

	let reviewQueue = $derived(page.url.searchParams.get('action') === 'human_review');
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Sentinel</title>
</svelte:head>

<header>
	<a class="brand" href={resolve('/')}>Sentinel</a>
	<nav aria-label="Main">
		<a href={resolve('/')} aria-current={page.url.pathname === '/' && !reviewQueue ? 'page' : undefined}
			>Events</a
		>
		<a href={resolve('/?action=human_review')} aria-current={reviewQueue ? 'page' : undefined}
			>Review queue</a
		>
	</nav>
</header>

<main>
	{@render children()}
</main>

<style>
	header {
		display: flex;
		align-items: center;
		gap: 1.5rem;
		padding: 0.8rem 1.5rem;
		border-bottom: 1px solid var(--border);
		background: var(--surface);
	}
	.brand {
		font-weight: 700;
		font-size: 1.1rem;
		color: var(--text);
		text-decoration: none;
	}
	nav {
		display: flex;
		gap: 1rem;
	}
	nav a {
		color: var(--muted);
		text-decoration: none;
		padding-bottom: 0.15rem;
		border-bottom: 2px solid transparent;
	}
	nav a[aria-current='page'] {
		color: var(--text);
		border-bottom-color: var(--accent);
	}
	main {
		max-width: 60rem;
		margin: 0 auto;
		padding: 1.5rem;
	}
</style>
