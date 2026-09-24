import type { EventRecord } from './api';

export type LiveStatus = 'connecting' | 'live' | 'reconnecting';

/** The /api/stream Server-Sent Events connection. `connect()` returns the cleanup,
 * so a component opens it with `$effect(() => feed.connect(onEvent))`. */
export class LiveFeed {
	status = $state<LiveStatus>('connecting');

	connect(onEvent: (record: EventRecord) => void, url = '/api/stream'): () => void {
		const source = new EventSource(url);
		source.onopen = () => (this.status = 'live');
		// EventSource reconnects by itself (the server sends `retry: 3000`).
		source.onerror = () => (this.status = 'reconnecting');
		source.addEventListener('event', (message) => {
			onEvent(JSON.parse((message as MessageEvent<string>).data) as EventRecord);
		});
		return () => source.close();
	}
}
