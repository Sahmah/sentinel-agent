<script lang="ts">
	import type { Action } from '$lib/api';
	import { ACTION_LABELS } from '$lib/format';

	let { action }: { action: Action } = $props();
</script>

<!-- Text carries the meaning; colour is only a second cue. -->
<span class={['badge', action]}>{ACTION_LABELS[action]}</span>

<style>
	.badge {
		display: inline-block;
		padding: 0.1rem 0.55rem;
		border-radius: 999px;
		font-size: 0.75rem;
		font-weight: 600;
		letter-spacing: 0.02em;
		text-transform: uppercase;
		color: white;
		background: var(--dismissed);
	}
	.alert {
		background: var(--alert);
	}
	.human_review {
		background: var(--review);
	}
	.logged {
		background: var(--logged);
	}
</style>
