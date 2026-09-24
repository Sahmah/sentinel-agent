<script lang="ts">
	import type { LiveStatus } from '$lib/live.svelte';
	import { enableNotifications, notificationsSupported } from '$lib/notify';

	let { status }: { status: LiveStatus } = $props();

	let permission = $state(notificationsSupported() ? Notification.permission : 'denied');

	async function askPermission() {
		permission = await enableNotifications();
	}
</script>

<div class="toolbar">
	<p class={['status', status]}>
		<span class="dot" aria-hidden="true"></span>
		{status === 'live' ? 'Live' : status === 'connecting' ? 'Connecting…' : 'Reconnecting…'}
	</p>
	{#if permission === 'default'}
		<button onclick={askPermission}>Enable alerts</button>
	{:else if permission === 'granted'}
		<span class="muted">Desktop alerts on</span>
	{/if}
</div>

<style>
	.toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 1rem;
	}
	.status {
		display: flex;
		align-items: center;
		gap: 0.45rem;
		margin: 0;
		font-size: 0.9rem;
		color: var(--muted);
	}
	.dot {
		width: 0.6rem;
		height: 0.6rem;
		border-radius: 50%;
		background: var(--review);
	}
	.live .dot {
		background: var(--logged);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--logged) 30%, transparent);
	}
	.muted {
		color: var(--muted);
		font-size: 0.9rem;
	}
</style>
