<script lang="ts">
	import { ACTIONS, type EventSummary } from '$lib/api';
	import { ACTION_LABELS } from '$lib/format';

	let { summary }: { summary: EventSummary } = $props();
</script>

<dl class="tiles">
	<div class="tile">
		<dt>Events</dt>
		<dd>{summary.total}</dd>
	</div>
	{#each ACTIONS as action (action)}
		<div class={['tile', action]}>
			<dt>{ACTION_LABELS[action]}</dt>
			<dd>{summary.by_action[action] ?? 0}</dd>
		</div>
	{/each}
	<div class="tile">
		<dt>Disagreements</dt>
		<dd>{summary.disagreements}</dd>
	</div>
	<div class="tile">
		<dt>Reviewed</dt>
		<dd>{summary.reviewed}</dd>
	</div>
</dl>

<style>
	.tiles {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(7.5rem, 1fr));
		gap: 0.6rem;
		margin: 0;
	}
	.tile {
		padding: 0.6rem 0.8rem;
		border: 1px solid var(--border);
		border-left-width: 4px;
		border-radius: var(--radius);
		background: var(--surface);
	}
	.alert {
		border-left-color: var(--alert);
	}
	.human_review {
		border-left-color: var(--review);
	}
	.logged {
		border-left-color: var(--logged);
	}
	.dismissed {
		border-left-color: var(--dismissed);
	}
	dt {
		font-size: 0.75rem;
		color: var(--muted);
	}
	dd {
		margin: 0;
		font-size: 1.4rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
</style>
