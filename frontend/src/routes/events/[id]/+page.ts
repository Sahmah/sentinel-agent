import { error } from '@sveltejs/kit';
import { ApiError, getEvent } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params }) => {
	try {
		return { event: await getEvent(params.id, fetch) };
	} catch (e) {
		if (e instanceof ApiError) error(404, e.message);
		throw e;
	}
};
