# Sentinel dashboard

A Svelte 5 + SvelteKit single-page app over the Sentinel HTTP API: live event feed
(Server-Sent Events), snapshot crops, the agent's reasoning, and one-click human review
("Real" / "False alarm"), whose verdicts calibrate the webcam's confidence.

Rules for working on it (runes, the live feed, API types, snapshots, notifications,
accessibility): [`.claude/skills/svelte-frontend/SKILL.md`](../.claude/skills/svelte-frontend/SKILL.md).

## Run it

```bash
npm install          # if npm 10 fails with "reading 'edgesOut'", use: npx npm@11 install
npm run build        # writes build/, which `sentinel serve` serves
cd .. && uv run sentinel serve    # http://127.0.0.1:8000
```

For development with hot reload, run `uv run sentinel serve` in one terminal and
`npm run dev` in another; Vite (http://localhost:5173) proxies `/api` to port 8000.

## Check it

```bash
npm run check                                     # svelte-check + TypeScript
npm test                                          # Vitest (src/lib/*.spec.ts)
npx @sveltejs/mcp svelte-autofixer src/routes/+page.svelte   # official Svelte linter
```

## Layout

| Path | What it is |
| --- | --- |
| `src/lib/api.ts` | Types mirroring the Python models, and the API client |
| `src/lib/live.svelte.ts` | The `/api/stream` connection (`LiveFeed`) |
| `src/lib/feed.ts` | Pure list logic for live events (tested) |
| `src/lib/notify.ts` | Desktop notifications for `alert` and `human_review` |
| `src/routes/+page.svelte` | Summary, filters, live event list |
| `src/routes/events/[id]/+page.svelte` | Scene, crop, reasoning, confidences, review |
