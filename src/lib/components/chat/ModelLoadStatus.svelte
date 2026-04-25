<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { config, runtimeModelLoad } from '$lib/stores';
	import { cancelRuntimeModelLoadJob } from '$lib/apis/models';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n: Writable<i18nType> = getContext('i18n');

	const terminalStates = new Set(['ready', 'failed', 'cancelled']);

	const formatBytes = (value: number | null | undefined) => {
		if (!value || value <= 0) return '';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		let amount = value;
		let index = 0;
		while (amount >= 1024 && index < units.length - 1) {
			amount /= 1024;
			index += 1;
		}
		return `${amount.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
	};

	const formatDuration = (seconds: number | null | undefined) => {
		if (!seconds || seconds <= 0) return '';
		if (seconds < 60) return `${Math.round(seconds)} с`;
		const minutes = Math.floor(seconds / 60);
		const rest = Math.round(seconds % 60);
		return rest > 0 ? `${minutes} мин ${rest} с` : `${minutes} мин`;
	};

	$: load = $runtimeModelLoad;
	$: runtimeModelsEnabled = Boolean($config?.features?.enable_agent_navigator_runtime_models);
	$: isTerminal = load?.state ? terminalStates.has(load.state) : false;
	$: canCancel = Boolean(load?.job_id && !isTerminal);
	$: percent = typeof load?.percent === 'number' ? Math.max(0, Math.min(100, load.percent)) : null;
	$: phaseLabel =
		load?.state === 'failed'
			? $i18n.t('Model load failed')
			: load?.state === 'cancelled'
				? $i18n.t('Model load cancelled')
				: load?.phase === 'loading_memory'
					? $i18n.t('Loading into memory')
					: load?.phase === 'starting_process'
						? $i18n.t('Starting runtime')
						: load?.phase === 'queued'
							? $i18n.t('Queued')
							: $i18n.t('Preparing model');
	$: loadedLabel =
		load?.bytes_loaded && load?.bytes_total
			? `${formatBytes(load.bytes_loaded)} / ${formatBytes(load.bytes_total)}`
			: '';
	$: speedLabel = load?.rate_bytes_per_sec ? `${formatBytes(load.rate_bytes_per_sec)}/s` : '';
	$: etaLabel = load?.eta_seconds ? formatDuration(load.eta_seconds) : '';

	const cancelLoad = async () => {
		if (!load?.job_id) return;
		try {
			const result = await cancelRuntimeModelLoadJob(localStorage.token, load.job_id);
			runtimeModelLoad.set({
				...(result?.job ?? load),
				display_name: load.display_name ?? result?.job?.model_id
			});
		} catch (error) {
			runtimeModelLoad.set({
				...load,
				state: 'failed',
				phase: 'failed',
				error: `${error}`
			});
		}
	};
</script>

{#if load && runtimeModelsEnabled}
	<div
		class="fixed right-4 top-20 z-50 w-[22rem] max-w-[calc(100vw-2rem)] border border-gray-200 bg-white p-3 text-gray-900 shadow-lg dark:border-gray-800 dark:bg-gray-900 dark:text-gray-100 rounded-lg"
		role="status"
		aria-live="polite"
	>
		<div class="flex items-start gap-3">
			{#if !isTerminal}
				<div class="mt-0.5">
					<Spinner />
				</div>
			{/if}

			<div class="min-w-0 flex-1">
				<div class="text-sm font-medium line-clamp-1">
					{$i18n.t('Loading model')}: {load.display_name ?? load.model_id}
				</div>
				<div class="mt-1 text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
					{phaseLabel}
					{#if load.error}
						: {load.error}
					{/if}
				</div>

					{#if percent !== null}
						<div class="mt-2 h-1.5 w-full overflow-hidden rounded bg-gray-100 dark:bg-gray-800">
							<div
								class="h-full rounded bg-gray-900 transition-all dark:bg-gray-100"
								style="width: {percent}%"
							></div>
						</div>
					<div class="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-gray-500 dark:text-gray-400">
						<span>{percent.toFixed(percent % 1 === 0 ? 0 : 1)}%</span>
						{#if loadedLabel}<span>{loadedLabel}</span>{/if}
						{#if speedLabel}<span>{speedLabel}</span>{/if}
						{#if etaLabel}<span>{etaLabel}</span>{/if}
					</div>
				{/if}
			</div>

			<button
				type="button"
				class="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
				on:click={() => {
					if (canCancel) {
						void cancelLoad();
					} else {
						runtimeModelLoad.set(null);
					}
				}}
			>
				{canCancel ? $i18n.t('Cancel') : $i18n.t('Close')}
			</button>
		</div>
	</div>
{/if}
