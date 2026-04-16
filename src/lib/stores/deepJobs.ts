import { browser } from '$app/environment';
import { writable } from 'svelte/store';

import { getDeepJob, type DeepJobSnapshot, type DeepJobState } from '$lib/apis/deep_jobs';

const ACTIVE_POLL_DELAY_MS = 2000;
const HIDDEN_POLL_DELAY_MS = 5000;
const MAX_RETRY_DELAY_MS = 20000;

const snapshotCache = new Map<string, DeepJobSnapshot>();

const isTerminalState = (state: DeepJobState | null | undefined) =>
	state === 'completed' || state === 'failed' || state === 'cancelled';

const getPollDelayMs = (hidden: boolean) => (hidden ? HIDDEN_POLL_DELAY_MS : ACTIVE_POLL_DELAY_MS);

const getRetryDelayMs = (hidden: boolean, failureCount: number) => {
	const baseDelay = getPollDelayMs(hidden);
	const multiplier = Math.max(1, 2 ** Math.min(failureCount, 2));
	return Math.min(MAX_RETRY_DELAY_MS, baseDelay * multiplier);
};

type CreateDeepJobStoreParams = {
	token: string;
	jobId: string;
	initialSnapshot?: DeepJobSnapshot | null;
};

export const getCachedDeepJobSnapshot = (jobId: string) => snapshotCache.get(jobId) ?? null;

export const createDeepJobStore = ({
	token,
	jobId,
	initialSnapshot = null
}: CreateDeepJobStoreParams) => {
	const cachedSnapshot = getCachedDeepJobSnapshot(jobId);
	let currentSnapshot = initialSnapshot ?? cachedSnapshot;
	const store = writable<DeepJobSnapshot | null>(currentSnapshot);

	let pollTimer: number | null = null;
	let abortController: AbortController | null = null;
	let failureCount = 0;
	let started = false;

	const clearPollTimer = () => {
		if (pollTimer !== null) {
			window.clearTimeout(pollTimer);
			pollTimer = null;
		}
	};

	const setSnapshot = (snapshot: DeepJobSnapshot | null) => {
		currentSnapshot = snapshot;
		if (snapshot?.job_id) {
			snapshotCache.set(snapshot.job_id, snapshot);
		}
		store.set(snapshot);
	};

	const scheduleRefresh = () => {
		if (!browser || !started) {
			return;
		}

		if (currentSnapshot && isTerminalState(currentSnapshot.state)) {
			return;
		}

		const hidden = document.visibilityState === 'hidden';
		const delay =
			failureCount > 0 ? getRetryDelayMs(hidden, failureCount) : getPollDelayMs(hidden);

		clearPollTimer();
		pollTimer = window.setTimeout(() => {
			void refresh();
		}, delay);
	};

	const refresh = async () => {
		if (!browser || !token || !jobId) {
			return currentSnapshot;
		}

		abortController?.abort();
		abortController = new AbortController();

		try {
			const snapshot = await getDeepJob(token, jobId, abortController.signal);
			failureCount = 0;
			setSnapshot(snapshot);
			return snapshot;
		} catch (error) {
			if ((error as DOMException)?.name === 'AbortError') {
				return currentSnapshot;
			}

			failureCount += 1;
			console.error(error);
			return currentSnapshot;
		} finally {
			scheduleRefresh();
		}
	};

	const handleFocus = () => {
		failureCount = 0;
		clearPollTimer();
		void refresh();
	};

	const handleVisibilityChange = () => {
		failureCount = 0;
		clearPollTimer();
		void refresh();
	};

	const start = () => {
		if (!browser || started) {
			return;
		}

		started = true;
		window.addEventListener('focus', handleFocus);
		document.addEventListener('visibilitychange', handleVisibilityChange);
		void refresh();
	};

	const destroy = () => {
		if (!browser || !started) {
			return;
		}

		started = false;
		clearPollTimer();
		abortController?.abort();
		abortController = null;
		window.removeEventListener('focus', handleFocus);
		document.removeEventListener('visibilitychange', handleVisibilityChange);
	};

	return {
		subscribe: store.subscribe,
		refresh,
		start,
		destroy
	};
};
