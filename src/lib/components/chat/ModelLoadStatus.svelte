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
		if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '';
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
		if (seconds < 60) return `${Math.round(seconds)}s`;
		const minutes = Math.floor(seconds / 60);
		const rest = Math.round(seconds % 60);
		if (minutes < 60) return rest > 0 ? `${minutes}m ${rest}s` : `${minutes}m`;
		const hours = Math.floor(minutes / 60);
		const minuteRest = minutes % 60;
		return minuteRest > 0 ? `${hours}h ${minuteRest}m` : `${hours}h`;
	};

	const phaseKey = (load: any) => {
		if (load?.state === 'ready') return 'Model loaded';
		if (load?.state === 'failed') return 'Model load failed';
		if (load?.state === 'cancelled') return 'Model load cancelled';
		if (load?.phase === 'validating') return 'Validating model';
		if (load?.phase === 'releasing_previous_model') return 'Stopping previous model';
		if (load?.phase === 'refreshing_resources') return 'Checking runtime resources';
		if (load?.phase === 'loading_memory') return 'Loading into memory';
		if (load?.phase === 'starting_process') return 'Starting runtime';
		if (load?.phase === 'queued') return 'Queued';
		return 'Preparing model';
	};

	const clampPercent = (value: number | null | undefined) => {
		if (typeof value !== 'number' || !Number.isFinite(value)) return null;
		return Math.max(0, Math.min(100, value));
	};

	$: load = $runtimeModelLoad;
	$: runtimeModelsEnabled = Boolean($config?.features?.enable_agent_navigator_runtime_models);
	$: isTerminal = load?.state ? terminalStates.has(load.state) : false;
	$: canCancel = Boolean(load?.job_id && !isTerminal);
	$: percent = clampPercent(load?.percent);
	$: phaseLabel = $i18n.t(phaseKey(load));
	$: titleLabel =
		load?.state === 'ready' || load?.state === 'failed' || load?.state === 'cancelled'
			? phaseLabel
			: $i18n.t('Loading model');
	$: loadedLabel =
		typeof load?.bytes_loaded === 'number' && typeof load?.bytes_total === 'number'
			? `${formatBytes(load.bytes_loaded)} / ${formatBytes(load.bytes_total)}`
			: '';
	$: speedLabel = load?.rate_bytes_per_sec ? `${formatBytes(load.rate_bytes_per_sec)}/s` : '';
	$: etaLabel = load?.eta_seconds ? formatDuration(load.eta_seconds) : '';
	$: secondaryLabel = [speedLabel, etaLabel].filter(Boolean).join(' · ');

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
		<div class="flex items-stretch gap-3">
			{#if !isTerminal}
				<div class="flex items-center">
					<Spinner />
				</div>
			{/if}

			<div class="min-w-0 flex-1">
				<div class="text-sm font-medium line-clamp-1">
					{titleLabel}: {load.display_name ?? load.model_id}
				</div>
				<div class="mt-1 text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
					{phaseLabel}
					{#if load.error}
						: {load.error}
					{/if}
				</div>

				{#if percent !== null}
					<div class="mt-2">
						<div
							class="flex items-center justify-between gap-2 text-[11px] text-gray-500 dark:text-gray-400"
						>
							<span class="min-w-0 truncate">{loadedLabel || phaseLabel}</span>
							<span class="shrink-0 tabular-nums">
								{percent.toFixed(percent % 1 === 0 ? 0 : 1)}%
							</span>
						</div>
						{#if secondaryLabel}
							<div class="mt-0.5 truncate text-[11px] text-gray-500 dark:text-gray-400">
								{secondaryLabel}
							</div>
						{/if}
						<div class="mt-1.5 h-1.5 w-full overflow-hidden rounded bg-gray-100 dark:bg-gray-800">
							<div
								class="h-full rounded bg-gray-900 transition-all dark:bg-gray-100"
								style="width: {percent}%"
							></div>
						</div>
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
