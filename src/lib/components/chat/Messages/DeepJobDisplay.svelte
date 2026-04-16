<script lang="ts">
	import { browser } from '$app/environment';
	import { getContext, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nType } from 'i18next';

	import { createDeepJobStore, getCachedDeepJobSnapshot } from '$lib/stores/deepJobs';
	import type {
		DeepJobProgress,
		DeepJobSnapshot,
		DeepJobState,
		DeepJobStep
	} from '$lib/apis/deep_jobs';

	const i18n = getContext<Writable<I18nType>>('i18n');

	export let jobId = '';
	export let title = 'Deep job';
	export let initialSummary = 'Deep job';
	export let initialState: DeepJobState = 'queued';
	export let resultMessageId: string | null = null;

	const initialSnapshot: DeepJobSnapshot | null =
		jobId === ''
			? null
			: {
					job_id: jobId,
					chat_id: null,
					state: initialState,
					phase: null,
					summary: initialSummary,
					progress: null,
					steps: [],
					cancel_requested: false,
					result_message_id: resultMessageId,
					error: null,
					updated_at: null
			  };

	const deepJobStore = createDeepJobStore({
		token: browser ? (localStorage.token ?? '') : '',
		jobId,
		initialSnapshot: getCachedDeepJobSnapshot(jobId) ?? initialSnapshot
	});

	let expanded = false;

	const STATE_CLASSNAMES: Record<DeepJobState, string> = {
		queued: 'border-gray-200 bg-gray-100 text-gray-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200',
		running: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/70 dark:bg-blue-950/60 dark:text-blue-300',
		completed: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/70 dark:bg-emerald-950/60 dark:text-emerald-300',
		failed: 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/70 dark:bg-red-950/60 dark:text-red-300',
		cancelled: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/70 dark:bg-amber-950/60 dark:text-amber-300'
	};

	const STEP_LEVEL_CLASSNAMES: Record<DeepJobStep['level'], string> = {
		info: 'bg-blue-500 dark:bg-blue-400',
		warning: 'bg-amber-500 dark:bg-amber-400',
		error: 'bg-red-500 dark:bg-red-400'
	};

	const isTerminalState = (state: DeepJobState | null | undefined) =>
		state === 'completed' || state === 'failed' || state === 'cancelled';

	const translate = (key: string, fallback: string) => {
		const translator = $i18n?.t;
		return typeof translator === 'function' ? translator(key) : fallback;
	};

	const getStateLabel = (state: DeepJobState) => {
		switch (state) {
			case 'queued':
				return translate('Queued', 'Queued');
			case 'running':
				return translate('Running', 'Running');
			case 'completed':
				return translate('Completed', 'Completed');
			case 'failed':
				return translate('Failed', 'Failed');
			case 'cancelled':
				return translate('Cancelled', 'Cancelled');
			default:
				return state;
		}
	};

	const getProgressPercent = (progress: DeepJobProgress | null) => {
		if (!progress || progress.current === null || progress.total === null || progress.total <= 0) {
			return null;
		}

		return Math.min(100, Math.max(0, (progress.current / progress.total) * 100));
	};

	const getProgressLabel = (progress: DeepJobProgress | null) => {
		if (!progress) {
			return '';
		}

		const values = [progress.current, progress.total].filter((value) => value !== null);
		let label = values.length > 0 ? values.join('/') : '';

		if (progress.unit) {
			label = label ? `${label} ${progress.unit}` : progress.unit;
		}

		return label;
	};

	const getErrorText = (error: DeepJobSnapshot['error']) => {
		if (!error) {
			return '';
		}

		if (typeof error === 'string') {
			return error;
		}

		if (typeof error === 'object') {
			for (const key of ['detail', 'message', 'error']) {
				const value = error[key];
				if (typeof value === 'string' && value.trim() !== '') {
					return value;
				}
			}
		}

		return '';
	};

	const formatTimestamp = (value: string | null) => {
		if (!value) {
			return '';
		}

		const timestamp = new Date(value);
		if (Number.isNaN(timestamp.getTime())) {
			return '';
		}

		return timestamp.toLocaleTimeString([], {
			hour: '2-digit',
			minute: '2-digit'
		});
	};

	onMount(() => {
		deepJobStore.start();

		return () => {
			deepJobStore.destroy();
		};
	});

	$: snapshot = $deepJobStore ?? initialSnapshot;
	$: displayState = snapshot?.state ?? initialState;
	$: displayStateLabel =
		snapshot?.cancel_requested && !isTerminalState(displayState)
			? translate('Stopping...', 'Stopping...')
			: getStateLabel(displayState);
	$: displayStateClassName = STATE_CLASSNAMES[displayState] ?? STATE_CLASSNAMES.queued;
	$: displaySummary = snapshot?.summary || initialSummary || title;
	$: progressLabel = getProgressLabel(snapshot?.progress ?? null);
	$: progressPercent = getProgressPercent(snapshot?.progress ?? null);
	$: errorText = getErrorText(snapshot?.error ?? null);
	$: updatedLabel = formatTimestamp(snapshot?.updated_at ?? null);
	$: steps = snapshot?.steps ?? [];
</script>

<div
	class="my-2 overflow-hidden rounded-2xl border border-gray-200/80 bg-gray-50/80 text-sm shadow-sm dark:border-gray-800 dark:bg-gray-900/60"
>
	<div class="flex flex-col gap-3 p-4">
		<div class="flex flex-wrap items-center gap-2">
			<div class="min-w-0 flex-1 text-sm font-medium text-gray-900 dark:text-gray-100">{title}</div>
			<div
				class={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${displayStateClassName}`}
			>
				{displayStateLabel}
			</div>
		</div>

		{#if snapshot?.phase}
			<div class="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
				{snapshot.phase}
			</div>
		{/if}

		<div class="text-sm text-gray-700 dark:text-gray-200">{displaySummary}</div>

		{#if progressLabel || updatedLabel}
			<div class="space-y-1.5">
				<div class="flex flex-wrap items-center justify-between gap-2 text-[11px] text-gray-500 dark:text-gray-400">
					<div>{progressLabel}</div>
					{#if updatedLabel}
						<div>{translate('Updated', 'Updated')} {updatedLabel}</div>
					{/if}
				</div>

				{#if progressPercent !== null}
					<div class="h-1.5 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-800">
						<div
							class="h-full rounded-full bg-blue-500 transition-[width] duration-300 dark:bg-blue-400"
							style={`width: ${progressPercent}%`}
						></div>
					</div>
				{/if}
			</div>
		{/if}

		{#if errorText}
			<div class="rounded-xl border border-red-200 bg-red-50 px-3 py-2 dark:border-red-900/70 dark:bg-red-950/40">
				<div class="text-xs font-medium uppercase tracking-wide text-red-700 dark:text-red-300">
					{translate('Error', 'Error')}
				</div>
				<div class="mt-1 text-sm text-red-700 dark:text-red-200">{errorText}</div>
			</div>
		{/if}

		{#if snapshot?.result_message_id}
			<div class="text-xs text-gray-500 dark:text-gray-400">
				Result saved in a separate assistant response.
			</div>
		{/if}

		{#if steps.length > 0}
			<div class="border-t border-gray-200/80 pt-3 dark:border-gray-800">
				<button
					class="flex w-full items-center justify-between gap-3 text-left text-xs font-medium uppercase tracking-wide text-gray-600 transition hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
					on:click={() => {
						expanded = !expanded;
					}}
				>
					<span>Execution log</span>
					<svg
						class={`size-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
						viewBox="0 0 20 20"
						fill="currentColor"
						aria-hidden="true"
					>
						<path
							fill-rule="evenodd"
							d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z"
							clip-rule="evenodd"
						/>
					</svg>
				</button>

				{#if expanded}
					<div class="mt-3 space-y-2">
						{#each steps as step, stepIdx (`${step.ts ?? 'step'}-${stepIdx}`)}
							<div class="flex items-start gap-3 rounded-xl bg-white/70 px-3 py-2 dark:bg-gray-950/40">
								<div class={`mt-1 size-1.5 rounded-full ${STEP_LEVEL_CLASSNAMES[step.level] ?? STEP_LEVEL_CLASSNAMES.info}`}></div>
								<div class="min-w-0 flex-1">
									<div class="text-sm text-gray-800 dark:text-gray-100">{step.text}</div>
									<div class="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-gray-500 dark:text-gray-400">
										{#if step.phase}
											<span>{step.phase}</span>
										{/if}
										{#if formatTimestamp(step.ts)}
											<span>{formatTimestamp(step.ts)}</span>
										{/if}
									</div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>
