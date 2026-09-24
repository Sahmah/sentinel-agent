import { error } from '@sveltejs/kit';
import { ACTIONS, ApiError, getSummary, listEvents, type Action } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
	const param = url.searchParams.get('action');
	const action = ACTIONS.includes(param as Action) ? (param as Action) : null;
	try {
		const [summary, page] = await Promise.all([
			getSummary(fetch),
			listEvents({ action }, fetch)
		]);
		return { summary, page, action };
	} catch (e) {
		if (e instanceof ApiError) error(503, e.message);
		throw e;
	}
};
