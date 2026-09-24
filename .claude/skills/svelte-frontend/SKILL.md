---
name: svelte-frontend
description: Do/don't rules for the Sentinel Agent dashboard (frontend/, Svelte 5 + SvelteKit SPA). Load before writing or reviewing any .svelte, .svelte.ts or SvelteKit config file in this repo. Covers runes, the live SSE feed, talking to the Python API, snapshots, notifications, accessibility, and validating code with the official Svelte MCP/CLI.
---

# Svelte frontend — do / don't (Sentinel Agent dashboard)

Grounded in the official Svelte AI tooling (checked 2026-09-24):
[svelte-core-bestpractices skill](https://github.com/sveltejs/ai-tools/tree/main/tools/skills/svelte-core-bestpractices),
[Svelte MCP docs](https://svelte.dev/docs/ai/overview), the
[SPA](https://svelte.dev/docs/kit/single-page-apps) and
[`svelte/reactivity`](https://svelte.dev/docs/svelte/svelte-reactivity) pages. Where this file
and the docs disagree, the docs win: fetch them (below) and fix this file.

## 0. Tooling first

- **Do** validate every component you write or change with the official autofixer, and fix
  everything it reports before you consider the file done:
  ```bash
  npx @sveltejs/mcp svelte-autofixer frontend/src/routes/+page.svelte
  ```
- **Do** look syntax up instead of recalling it. Svelte 5 changed most of the API, and training
  data is full of Svelte 3/4:
  ```bash
  npx @sveltejs/mcp list-sections
  npx @sveltejs/mcp get-documentation "svelte/\$state,svelte/\$derived,kit/single-page-apps"
  ```
  (escape `$` as `\$` in the shell). The repo's `.mcp.json` also registers the Svelte MCP server
  (`svelte`) with the same tools: `list-sections`, `get-documentation`, `svelte-autofixer`,
  `playground-link`.
- **Do** run `npm run check` (svelte-check + TypeScript) and `npm run build` before committing.
- **Don't** hand-roll a project: scaffold with `npx sv create`, then add
  `@sveltejs/adapter-static`.

## 1. Architecture of this dashboard

- **Do** keep it a static SPA: `adapter-static` with `fallback: 'index.html'`, and
  `export const ssr = false` in `src/routes/+layout.ts`. The Python server (`sentinel serve`)
  serves the build and the API from one origin, so there is no CORS and no Node server in
  production.
- **Do** call the API with relative URLs (`/api/events`). In dev, Vite proxies `/api` to
  `http://127.0.0.1:8000` (`vite.config.ts`), so the same code works in both modes.
- **Don't** add `+page.server.ts`, `+server.ts` or form actions: SvelteKit server code has no
  server to run on here. All data comes from the Python API.
- **Don't** duplicate backend logic (fusion, thresholds, calibration) in TypeScript. The UI
  shows what the backend decided; the numbers come from the API.
- **Do** keep API types in one file (`src/lib/api.ts`) that mirrors `EventRecord` /
  `EventPage` / `EventSummary` from the Python side, and update it when those models change.

## 2. Reactivity (Svelte 5 runes)

- **Do** use `$state` only for values the UI reacts to. Use `$state.raw` for API payloads that
  are replaced, never mutated in place (event pages, the summary): no proxy overhead.
- **Do** compute with `$derived` (or `$derived.by` for multi-line logic):
  `let alerts = $derived(events.filter((e) => e.action === 'alert'))`.
- **Don't** compute state inside `$effect` (`$effect(() => { alerts = ... })`). That is the most
  common Svelte 5 mistake and the autofixer flags it.
- **Do** use `$effect` only to connect to something outside Svelte, and return its cleanup.
  The live feed is the canonical case:
  ```ts
  $effect(() => {
    const source = new EventSource('/api/stream');
    source.addEventListener('event', (e) => live.add(JSON.parse(e.data)));
    return () => source.close();
  });
  ```
- **Don't** open an `EventSource` or `setInterval` without closing it in the cleanup. Every
  navigation would leak a connection to the server.
- **Do** treat props as changing: derive from them with `$derived`, don't copy them into
  local variables.
- **Do** share state through a class with `$state` fields in a `.svelte.ts` module
  (for example `LiveFeed`), not through stores.
- **Don't** use legacy syntax: no `export let`, `$:`, `on:click`, `<slot>`, `createEventDispatcher`
  or stores for new code. Use `$props`, `$derived`, `onclick`, snippets and callback props.

## 3. Templates

- **Do** key every `{#each}` by the event id: `{#each events as event (event.id)}`. The live
  feed prepends items; without a key, every row re-renders and images reload.
- **Don't** key by index.
- **Do** use `{#snippet}` + `{@render}` for repeated markup (badges, confidence bars).
- **Do** set dynamic CSS values with `style:` or custom properties (`style:--p={p_llm}`),
  and use clsx-style `class={['badge', action]}` instead of `class:` directives.

## 4. Data, errors and loading

- **Do** load a page's data in `+page.ts` `load` functions (they run in the browser in SPA mode)
  and use the `fetch` passed to `load`.
- **Do** handle every API failure visibly: the backend answers `{"error": "..."}` with a 4xx.
  Show the message; don't swallow it and render an empty list.
- **Do** paginate with the `next_cursor` the API returns ("Load more"). Never ask for
  more than 100 events at once; the API caps it anyway.
- **Do** show a clear "live" / "reconnecting" state: `EventSource` reconnects on its own
  (the server sends `retry: 3000`), and the operator must know when the feed is stale.
- **Do** after a review (`POST /api/events/{id}/review`), replace the item with the record
  the API returns. Don't assume the write succeeded.

## 5. Snapshots (the YOLO crops)

- **Do** load them from `/api/snapshots/<id>.jpg` (crop) and `/api/snapshots/<id>_scene.jpg`
  (full frame). `snapshot` is null when an event has no crop: render a placeholder, not a
  broken image.
- **Do** give every image an `alt` that says what it is ("Crop of person event at 14:02").
- **Do** set `loading="lazy"` and fixed dimensions (width/height or `aspect-ratio`) on list
  thumbnails, so the feed doesn't jump while images load.
- **Don't** put snapshots in the page URL or in notifications that leave the machine: they
  are images of someone's home.

## 6. Notifications

- **Do** ask for `Notification.requestPermission()` only from a click ("Enable alerts"),
  never on page load. Browsers block or penalise unprompted requests.
- **Do** notify only for `alert` and `human_review`, and only for events that arrive on the
  live stream (not the backlog). Use `tag: event.id` so a reconnect cannot double-notify.
- **Don't** assume permission: check `Notification.permission` and degrade to an in-page
  banner.

## 7. Accessibility and UX

- **Do** use real `<button>` elements for actions (review, load more), with visible text.
- **Do** never convey the decision by colour alone: the action badge carries text
  (`ALERT`, `REVIEW`), colour is a second cue.
- **Do** announce new live events with an `aria-live="polite"` region.
- **Do** support dark mode through CSS custom properties and `prefers-color-scheme`.
- **Do** format times in the viewer's locale with `Intl.DateTimeFormat`; the API sends UTC.

## 8. Security

- **Don't** render model output as HTML. `reasoning` and `confidence_basis` come from an LLM:
  always `{text}`, never `{@html text}`.
- **Don't** expose `sentinel serve` beyond localhost (it has no auth) and don't build auth
  into the UI instead: auth belongs in front of the API.

## 9. Testing

- **Do** unit-test logic in `.ts`/`.svelte.ts` modules (formatting, the live feed's
  de-duplication) with Vitest; keep components thin so there is little to test in them.
- **Do** keep the Python side's API tests (`tests/integration/test_api.py`) as the contract;
  when an endpoint changes, update `src/lib/api.ts` in the same commit.
