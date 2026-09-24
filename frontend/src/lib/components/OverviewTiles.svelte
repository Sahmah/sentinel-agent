<script lang="ts">
	import { resolve } from '$app/paths';
	import type { DaysSummary } from '$lib/api';
	import { percent } from '$lib/format';
	import { totalsOver } from '$lib/overview';

	let { days }: { days: DaysSummary } = $props();

	let week = $derived(totalsOver(days.days, 7));
</script>

<div class="tiles">
	<a class={['tile', 'pending', { waiting: days.needs_review > 0 }]} href={resolve('/events?view=pending')}>
		<span class="label">Needs your decision</span>
		<span class="value">{days.needs_review}</span>
		<span class="note">{days.needs_review > 0 ? 'Open the queue →' : 'Nothing waiting'}</span>
	</a>
	<div class="tile">
		<span class="label">Events, last 7 days</span>
		<span class="value">{week.events.toLocaleString()}</span>
	</div>
	<div class="tile">
		<span class="label">Alerts, last 7 days</span>
		<span class="value">{week.alerts.toLocaleString()}</span>
	</div>
	<div class="tile">
		<span class="label">False alarms among reviewed</span>
		<span class="value">{percent(week.falseAlarmRate)}</span>
		<span class="note">✓ {week.real} real · ✗ {week.falseAlarms} false, last 7 days</span>
	</div>
</div>

<style>
	.tiles {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
		gap: 0.6rem;
	}
	.tile {
		display: grid;
		align-content: start;
		gap: 0.15rem;
		padding: 0.8rem 1rem;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--text);
		text-decoration: none;
	}
	.label {
		color: var(--muted);
		font-size: 0.85rem;
	}
	.value {
		font-size: 1.8rem;
		font-weight: 600;
		line-height: 1.2;
	}
	.note {
		color: var(--muted);
		font-size: 0.8rem;
	}
	.pending:hover {
		border-color: var(--accent);
	}
	.pending.waiting {
		border-color: var(--review);
		border-left-width: 5px;
		background: color-mix(in srgb, var(--review) 10%, var(--surface));
	}
	.pending.waiting .note {
		color: var(--text);
		font-weight: 600;
	}
</style>
