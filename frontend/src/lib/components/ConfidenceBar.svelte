<script lang="ts">
	import { percent } from '$lib/format';

	let {
		label,
		value,
		color,
		note = ''
	}: { label: string; value: number | null; color: string; note?: string } = $props();
</script>

<div class="row">
	<span class="label">{label}</span>
	<span
		class="track"
		role="meter"
		aria-label={label}
		aria-valuemin={0}
		aria-valuemax={100}
		aria-valuenow={value === null ? undefined : Math.round(value * 100)}
	>
		<span class="fill" style:--p={value ?? 0} style:--c={color}></span>
	</span>
	<span class="value">{percent(value)}{note}</span>
</div>

<style>
	.row {
		display: grid;
		grid-template-columns: 3.2rem 1fr 3.4rem;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.8rem;
	}
	.label {
		color: var(--muted);
	}
	.track {
		height: 0.45rem;
		border-radius: 999px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.fill {
		display: block;
		height: 100%;
		width: calc(var(--p) * 100%);
		background: var(--c);
	}
	.value {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
</style>
