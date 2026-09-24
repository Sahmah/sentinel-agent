<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
</script>

<h1>{page.status}</h1>
<p>{page.error?.message}</p>
{#if page.status === 503}
	<p>Start the API with <code>uv run sentinel serve</code> and reload.</p>
{/if}
<p><a href={resolve('/')}>Back to events</a></p>
