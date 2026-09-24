<script lang="ts">
	import { resolve } from '$app/paths';
	import { cropUrl, type EventRecord } from '$lib/api';
	import { describeDuration, formatTime } from '$lib/format';
	import ActionBadge from './ActionBadge.svelte';
	import ConfidenceBar from './ConfidenceBar.svelte';

	let { event, fresh = false }: { event: EventRecord; fresh?: boolean } = $props();

	let crop = $derived(cropUrl(event));
</script>

<a class={['card', { fresh }]} href={resolve('/events/[id]', { id: event.id })}>
	{#if crop}
		<img
			src={crop}
			alt={`Crop of the ${event.label} event at ${formatTime(event.occurred_at)}`}
			loading="lazy"
			width="96"
			height="96"
		/>
	{:else}
		<div class="placeholder" aria-hidden="true">no image</div>
	{/if}

	<div class="body">
		<div class="top">
			<ActionBadge action={event.action} />
			<strong class="label">{event.label}</strong>
			{#if event.entered_restricted_zone}<span class="zone">in zone</span>{/if}
			<time datetime={event.occurred_at}>{formatTime(event.occurred_at)}</time>
		</div>
		<p class="meta">
			{event.camera_id} · {describeDuration(event.duration_seconds, event.detection_count)}
			{#if event.disagreement}<span class="flag">· vision and agent disagree</span>{/if}
			{#if event.review}<span class="reviewed">· reviewed: {event.review.replace('_', ' ')}</span
				>{/if}
		</p>
		<ConfidenceBar
			label="vision"
			value={event.p_cv}
			color="var(--cv)"
			note={event.p_cv_calibrated ? '' : '*'}
		/>
		<ConfidenceBar label="agent" value={event.llm_confidence} color="var(--llm)" />
	</div>
</a>

<style>
	.card {
		display: grid;
		grid-template-columns: 96px 1fr;
		gap: 0.9rem;
		padding: 0.8rem;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		box-shadow: var(--shadow);
		color: inherit;
		text-decoration: none;
		transition: border-color 0.2s;
	}
	.card:hover,
	.card:focus-visible {
		border-color: var(--accent);
	}
	.fresh {
		animation: arrive 2.5s ease-out;
	}
	@keyframes arrive {
		from {
			border-color: var(--accent);
			box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 35%, transparent);
		}
	}
	img,
	.placeholder {
		width: 96px;
		height: 96px;
		border-radius: 8px;
		object-fit: cover;
		background: var(--surface-2);
	}
	.placeholder {
		display: grid;
		place-items: center;
		font-size: 0.7rem;
		color: var(--muted);
	}
	.body {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		min-width: 0;
	}
	.top {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.label {
		text-transform: capitalize;
	}
	.zone {
		font-size: 0.75rem;
		color: var(--alert);
		font-weight: 600;
	}
	time {
		margin-left: auto;
		font-size: 0.8rem;
		color: var(--muted);
		font-variant-numeric: tabular-nums;
	}
	.meta {
		margin: 0;
		font-size: 0.8rem;
		color: var(--muted);
	}
	.flag {
		color: var(--review);
		font-weight: 600;
	}
</style>
