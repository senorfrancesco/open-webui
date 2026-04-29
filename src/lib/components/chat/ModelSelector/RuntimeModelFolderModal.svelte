<script lang="ts">
	import { createEventDispatcher, getContext, onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import {
		addRuntimeModelScanFolder,
		browseRuntimeModelFolders,
		cancelRuntimeModelScanJob,
		createRuntimeModelScanJob,
		deleteRuntimeModelScanFolder,
		ensureRuntimeWorkspaceModelRecord,
		getRuntimeModelScanJob,
		getRuntimeModelScanFolders,
		getRuntimeModelsStatus,
		registerRuntimeModel,
		unregisterRuntimeModel
	} from '$lib/apis/models';
	import { getModels } from '$lib/apis';
	import { config, models, settings } from '$lib/stores';

	const i18n = getContext('i18n') as any;
	const dispatch = createEventDispatcher();

	export let show = false;

	type RuntimeModelBrowseEntry = {
		name: string;
		path: string;
		source?: string;
		looks_like_model_dir?: boolean;
		model_file_count_hint?: number;
		folder_tags?: string[];
		folder_signals?: Record<string, boolean>;
	};

	type RuntimeModelPreviewEntry = {
		candidate_id: string;
		display_name: string;
		kind: string;
		runtime_type: string;
		status: string;
		status_reason: string;
		user_selectable: boolean;
		resolved_source: Record<string, unknown>;
	};

	type RuntimeModelPreviewWarning = {
		code: string;
		message: string;
	};

	type RuntimeModelPreview = {
		source_path: string;
		entries: RuntimeModelPreviewEntry[];
		warnings?: RuntimeModelPreviewWarning[];
	};

	type RuntimeModelScanJob = {
		job_id: string;
		state: string;
		status?: string;
		path: string;
		progress?: Record<string, number>;
		result?: RuntimeModelPreview | null;
		error?: unknown;
	};

	type RuntimeModelScanFolder = {
		id: string;
		path: string;
		name?: string;
	};

	type RuntimeModelsStatus = {
		enabled?: boolean;
		available?: boolean;
		detail?: string;
	};

	type RuntimeModelPreviewResolvedSource = {
		gguf_path?: string;
		mmproj_path?: string;
		primary_path?: string;
		shards?: string[];
	};

	const errorMessage = (error: unknown) => {
		if (error && typeof error === 'object' && 'detail' in error) {
			return `${(error as { detail?: unknown }).detail}`;
		}

		return `${error}`;
	};

	const directConnections = () =>
		$config?.features?.enable_direct_connections ? ($settings?.directConnections ?? null) : null;
	const runtimeModelsEnabled = () =>
		Boolean($config?.features?.enable_agent_navigator_runtime_models);
	const runtimeModelsBlocked = () => Boolean(runtimeStatus && !runtimeStatus.enabled);

	let initializedForOpen = false;
	let browseLoading = false;
	let scanFoldersLoading = false;
	let previewLoading = false;
	let registeringCandidateId = '';
	let addScanFolderLoading = false;
	let activeScanJobId = '';
	let scanPollTimer: ReturnType<typeof setTimeout> | null = null;

	let currentPath: string | null = null;
	let parentPath: string | null = null;
	let folderEntries: RuntimeModelBrowseEntry[] = [];
	let scanFolders: RuntimeModelScanFolder[] = [];
	let runtimeStatus: RuntimeModelsStatus | null = null;
	let preview: RuntimeModelPreview | null = null;
	let scanFolderInput = '';

	$: if (show && !initializedForOpen) {
		initializedForOpen = true;
		void initializeModal();
	}

	$: if (!show && initializedForOpen) {
		initializedForOpen = false;
		runtimeStatus = null;
		preview = null;
		scanFolderInput = '';
		registeringCandidateId = '';
		activeScanJobId = '';
		previewLoading = false;
		clearScanPolling();
	}

	onDestroy(() => {
		clearScanPolling();
	});

	function clearScanPolling() {
		if (scanPollTimer) {
			clearTimeout(scanPollTimer);
			scanPollTimer = null;
		}
	}

	function scheduleScanPolling(jobId: string) {
		clearScanPolling();
		scanPollTimer = setTimeout(() => {
			void pollScanJob(jobId);
		}, 700);
	}

	function applyScanJob(job: RuntimeModelScanJob | null) {
		if (!job) return;
		activeScanJobId = job.job_id;
		const state = job.state ?? job.status;
		if (state === 'completed') {
			if (job.result) {
				preview = job.result;
			}
			previewLoading = false;
			activeScanJobId = '';
			clearScanPolling();
			return;
		}
		if (state === 'cancelled') {
			previewLoading = false;
			activeScanJobId = '';
			clearScanPolling();
			return;
		}
		if (state === 'failed') {
			previewLoading = false;
			activeScanJobId = '';
			clearScanPolling();
			toast.error(errorMessage(job.error ?? 'scan_failed'));
			return;
		}
		scheduleScanPolling(job.job_id);
	}

	async function pollScanJob(jobId: string) {
		if (!jobId || jobId !== activeScanJobId) return;
		try {
			const job = await getRuntimeModelScanJob(localStorage.token, jobId);
			applyScanJob(job);
		} catch (error) {
			previewLoading = false;
			activeScanJobId = '';
			clearScanPolling();
			toast.error(errorMessage(error));
		}
	}

	const loadFolders = async (path: string | null = null) => {
		if (runtimeModelsBlocked()) return;

		browseLoading = true;
		try {
			const response = await browseRuntimeModelFolders(localStorage.token, path);
			currentPath = response?.current_path ?? null;
			parentPath = response?.parent_path ?? null;
			folderEntries = response?.entries ?? [];
			if (path === null) {
				preview = null;
			}
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			browseLoading = false;
		}
	};

	const loadScanFolders = async () => {
		if (runtimeModelsBlocked()) return;

		scanFoldersLoading = true;
		try {
			const response = await getRuntimeModelScanFolders(localStorage.token);
			scanFolders = response?.folders ?? [];
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			scanFoldersLoading = false;
		}
	};

	const initializeModal = async () => {
		runtimeStatus = await getRuntimeModelsStatus(localStorage.token).catch((error) => ({
			enabled: true,
			available: false,
			detail: errorMessage(error)
		}));
		if (!runtimeStatus?.enabled) {
			folderEntries = [];
			scanFolders = [];
			preview = null;
			return;
		}

		await Promise.all([loadFolders(null), loadScanFolders()]);
	};

	const previewCurrentFolder = async () => {
		if (runtimeModelsBlocked()) return;

		if (!currentPath) {
			toast.error($i18n.t('Choose a folder first'));
			return;
		}
		previewLoading = true;
		clearScanPolling();
		try {
			const job = await createRuntimeModelScanJob(localStorage.token, currentPath);
			applyScanJob(job);
		} catch (error) {
			previewLoading = false;
			activeScanJobId = '';
			toast.error(errorMessage(error));
		}
	};

	const cancelPreviewScan = async () => {
		if (!activeScanJobId) {
			previewLoading = false;
			return;
		}
		const jobId = activeScanJobId;
		try {
			const job = await cancelRuntimeModelScanJob(localStorage.token, jobId);
			applyScanJob(job);
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			previewLoading = false;
			activeScanJobId = '';
			clearScanPolling();
		}
	};

	const addScanFolderPath = async (rawPath: string) => {
		if (runtimeModelsBlocked()) return;

		const path = rawPath.trim();
		if (!path) {
			return;
		}
		addScanFolderLoading = true;
		try {
			const response = await addRuntimeModelScanFolder(localStorage.token, path);
			if (scanFolderInput.trim() === path) {
				scanFolderInput = '';
			}
			await loadScanFolders();
			await loadFolders(response?.path ?? path);
			toast.success($i18n.t('Folder added'));
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			addScanFolderLoading = false;
		}
	};

	const addScanFolder = async () => addScanFolderPath(scanFolderInput);

	const addCurrentFolderAsRoot = async () => {
		if (!currentPath) {
			toast.error($i18n.t('Choose a folder first'));
			return;
		}
		await addScanFolderPath(currentPath);
	};

	const removeScanFolder = async (folderId: string) => {
		try {
			await deleteRuntimeModelScanFolder(localStorage.token, folderId);
			await loadScanFolders();
			toast.success($i18n.t('Folder removed'));
		} catch (error) {
			toast.error(errorMessage(error));
		}
	};

	const refreshModels = async () => {
		models.set(
			await getModels(localStorage.token, directConnections(), false, true, runtimeModelsEnabled())
		);
	};

	const registerEntry = async (entry: RuntimeModelPreviewEntry) => {
		const sourcePath = preview?.source_path ?? currentPath;
		if (!sourcePath) {
			toast.error($i18n.t('Preview the folder before registration'));
			return;
		}
		registeringCandidateId = entry.candidate_id;
		try {
			const response = await registerRuntimeModel(localStorage.token, sourcePath, entry);
			const runtimeModel = response?.model ?? null;
			if (!runtimeModel?.model_id) {
				throw new Error('runtime-model-registration-response-invalid');
			}
			try {
				await ensureRuntimeWorkspaceModelRecord(localStorage.token, runtimeModel);
			} catch (workspaceError) {
				try {
					await unregisterRuntimeModel(localStorage.token, runtimeModel.model_id);
				} catch (rollbackError) {
					console.error('Failed to rollback runtime registration', rollbackError);
				}
				throw workspaceError;
			}
			await refreshModels();
			dispatch('registered', { model: runtimeModel });
			toast.success(
				$i18n.t('Model "{{modelName}}" added to the list', {
					modelName: entry.display_name
				})
			);
			show = false;
		} catch (error) {
			toast.error(errorMessage(error));
		} finally {
			registeringCandidateId = '';
		}
	};

	const statusClassName = (status: string) => {
		if (status === 'ready') {
			return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-200';
		}
		if (status === 'incomplete') {
			return 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-200';
		}
		if (status === 'ambiguous') {
			return 'bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-200';
		}
		return 'bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-200';
	};

	const statusLabel = (status: string) => {
		if (status === 'ready') return $i18n.t('Ready');
		if (status === 'incomplete') return $i18n.t('Incomplete');
		if (status === 'ambiguous') return $i18n.t('Needs review');
		return $i18n.t('Unsupported');
	};

	const canRegister = (entry: RuntimeModelPreviewEntry) => {
		return entry.status === 'ready' && entry.user_selectable;
	};

	const browseEntryTags = (entry: RuntimeModelBrowseEntry) => {
		const tags = Array.isArray(entry.folder_tags) ? entry.folder_tags.filter(Boolean) : [];
		return tags.slice(0, 2);
	};

	const previewEntryBadges = (entry: RuntimeModelPreviewEntry) => {
		const badges: string[] = [];
		if (entry.runtime_type === 'gguf' || entry.runtime_type === 'gguf-vl') {
			badges.push('GGUF');
		}
		if (entry.runtime_type === 'gguf-vl' || entry.kind === 'vision') {
			badges.push($i18n.t('Vision'));
		}
		const resolvedSource = (entry.resolved_source ?? {}) as RuntimeModelPreviewResolvedSource;
		if (Array.isArray(resolvedSource.shards) && resolvedSource.shards.length > 0) {
			badges.push($i18n.t('Split'));
		}
		return [...new Set(badges)];
	};
</script>

<Modal bind:show size="lg">
	<div class="flex flex-col max-h-[85vh]">
		<div
			class="flex items-center justify-between px-5 py-4 border-b border-gray-100 dark:border-gray-850"
		>
			<div>
				<div class="text-base font-medium">{$i18n.t('Add model from folder')}</div>
				<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
					{$i18n.t('Browse folders, preview a model candidate, and add it to the shared list')}
				</div>
			</div>
			<button
				class="text-sm text-gray-500 hover:text-gray-900 dark:hover:text-white"
				on:click={() => (show = false)}
			>
				{$i18n.t('Close')}
			</button>
		</div>

		{#if runtimeStatus && (!runtimeStatus.enabled || !runtimeStatus.available)}
			<div
				class="mx-5 mt-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100"
			>
				{$i18n.t('Runtime model backend is unavailable')}
				{#if runtimeStatus.detail}
					<div class="mt-1 text-xs opacity-80">{runtimeStatus.detail}</div>
				{/if}
			</div>
		{/if}

		<div class="grid grid-cols-1 lg:grid-cols-[1.1fr,0.9fr] gap-4 p-5 overflow-y-auto">
			<div class="space-y-4 min-w-0">
				<div class="space-y-2">
					<div class="flex items-center justify-between gap-2">
						<div class="text-sm font-medium">{$i18n.t('Saved folders')}</div>
						{#if scanFoldersLoading}
							<Spinner />
						{/if}
					</div>
					<div class="flex gap-2">
						<input
							bind:value={scanFolderInput}
							class="flex-1 rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
							placeholder={$i18n.t('Add custom folder path')}
							disabled={runtimeModelsBlocked()}
							on:keydown={(event) => {
								if (event.key === 'Enter') {
									event.preventDefault();
									void addScanFolder();
								}
							}}
						/>
						<button
							class="rounded-xl px-3 py-2 text-sm bg-gray-900 text-white dark:bg-white dark:text-gray-900 disabled:opacity-60"
							disabled={runtimeModelsBlocked() || addScanFolderLoading || !scanFolderInput.trim()}
							on:click={addScanFolder}
						>
							{$i18n.t('Add')}
						</button>
					</div>

					{#if scanFolders.length > 0}
						<div class="flex flex-wrap gap-2">
							{#each scanFolders as folder}
								<div
									class="flex items-center gap-1 rounded-xl bg-gray-100 dark:bg-gray-850 px-2.5 py-1.5 text-xs"
								>
									<button
										class="text-left hover:text-gray-900 dark:hover:text-white"
										on:click={() => loadFolders(folder.path)}
									>
										{folder.name ?? folder.path}
									</button>
									<button
										class="text-gray-500 hover:text-rose-500"
										on:click={() => removeScanFolder(folder.id)}
									>
										×
									</button>
								</div>
							{/each}
						</div>
					{/if}
				</div>

				<div class="rounded-2xl border border-gray-100 dark:border-gray-850 overflow-hidden">
					<div
						class="flex items-center justify-between gap-2 px-4 py-3 border-b border-gray-100 dark:border-gray-850 bg-gray-50/80 dark:bg-gray-900/60"
					>
						<div class="min-w-0">
							<div class="text-sm font-medium">{$i18n.t('Folder browser')}</div>
							<div class="mt-1 text-xs text-gray-500 dark:text-gray-400 truncate">
								{#if currentPath}
									{currentPath}
								{:else}
									{$i18n.t('Allowed roots')}
								{/if}
							</div>
						</div>
						<div class="flex items-center gap-2 shrink-0">
							<button
								class="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-white"
								disabled={runtimeModelsBlocked()}
								on:click={() => loadFolders(null)}
							>
								{$i18n.t('Roots')}
							</button>
							<button
								class="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-white disabled:opacity-50"
								disabled={runtimeModelsBlocked() || !parentPath}
								on:click={() => (parentPath ? loadFolders(parentPath) : loadFolders(null))}
							>
								{$i18n.t('Up')}
							</button>
						</div>
					</div>

					<div class="min-h-[18rem] max-h-[24rem] overflow-y-auto">
						{#if browseLoading}
							<div class="flex items-center justify-center py-10"><Spinner /></div>
						{:else if folderEntries.length === 0}
							<div class="px-4 py-6 text-sm text-gray-500 dark:text-gray-400">
								{$i18n.t('No folders found')}
							</div>
						{:else}
							{#each folderEntries as entry}
								<button
									class="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-850/70 border-b border-gray-100 dark:border-gray-850 last:border-b-0"
									on:click={() => loadFolders(entry.path)}
								>
									<div class="min-w-0 flex-1">
										<div class="text-sm truncate">{entry.name}</div>
										<div class="mt-1 text-xs text-gray-500 dark:text-gray-400 truncate">
											{entry.path}
										</div>
										{#if entry.looks_like_model_dir || browseEntryTags(entry).length > 0}
											<div class="mt-2 flex flex-wrap items-center gap-1.5">
												{#if entry.looks_like_model_dir}
													<div
														class="rounded-full border border-gray-200 dark:border-gray-800 px-2 py-0.5 text-[0.7rem] text-gray-600 dark:text-gray-300"
													>
														{$i18n.t('Models')}
													</div>
												{/if}
												{#each browseEntryTags(entry) as tag}
													<div
														class="rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-[0.7rem] text-gray-600 dark:text-gray-300"
													>
														{tag}
													</div>
												{/each}
											</div>
										{/if}
									</div>
									{#if (entry.model_file_count_hint ?? 0) > 0}
										<div class="shrink-0 text-[0.7rem] text-gray-500 dark:text-gray-400">
											{entry.model_file_count_hint}
											{$i18n.t('files')}
										</div>
									{/if}
								</button>
							{/each}
						{/if}
					</div>

					<div
						class="flex items-center justify-between gap-2 px-4 py-3 border-t border-gray-100 dark:border-gray-850 bg-gray-50/70 dark:bg-gray-900/50"
					>
						<div class="text-xs text-gray-500 dark:text-gray-400">
							{#if currentPath}
								{$i18n.t('Preview the current folder to find runtime model candidates')}
							{:else}
								{$i18n.t('Open a folder before previewing it')}
							{/if}
						</div>
						<div class="flex items-center gap-2">
							<button
								class="rounded-xl px-3 py-2 text-sm border border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-60"
								disabled={runtimeModelsBlocked() || !currentPath || addScanFolderLoading}
								on:click={() => void addCurrentFolderAsRoot()}
							>
								{$i18n.t('Use this folder')}
							</button>
							{#if activeScanJobId}
								<button
									class="rounded-xl px-3 py-2 text-sm border border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-60"
									on:click={cancelPreviewScan}
								>
									{$i18n.t('Cancel')}
								</button>
							{/if}
							<button
								class="rounded-xl px-3 py-2 text-sm bg-gray-900 text-white dark:bg-white dark:text-gray-900 disabled:opacity-60"
								disabled={runtimeModelsBlocked() || !currentPath || previewLoading}
								on:click={previewCurrentFolder}
							>
								{#if previewLoading}
									{$i18n.t('Scanning...')}
								{:else}
									{$i18n.t('Preview current folder')}
								{/if}
							</button>
						</div>
					</div>
				</div>
			</div>

			<div class="space-y-4 min-w-0">
				<div class="rounded-2xl border border-gray-100 dark:border-gray-850 min-h-[28rem]">
					<div class="px-4 py-3 border-b border-gray-100 dark:border-gray-850">
						<div class="text-sm font-medium">{$i18n.t('Preview')}</div>
						<div class="mt-1 text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('Only ready candidates can be registered')}
						</div>
					</div>

					<div class="p-4 space-y-3">
						{#if !preview}
							<div class="text-sm text-gray-500 dark:text-gray-400">
								{$i18n.t('No folder preview yet')}
							</div>
						{:else}
							<div class="text-xs text-gray-500 dark:text-gray-400 break-all">
								{preview.source_path}
							</div>

							{#if (preview.warnings ?? []).length > 0}
								<div class="space-y-2">
									{#each preview.warnings ?? [] as warning}
										<div
											class="rounded-xl bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200 px-3 py-2 text-xs"
										>
											{warning.message}
										</div>
									{/each}
								</div>
							{/if}

							{#if (preview.entries ?? []).length === 0}
								<div class="text-sm text-gray-500 dark:text-gray-400">
									{$i18n.t('No model candidates found in this folder')}
								</div>
							{:else}
								<div class="space-y-3">
									{#each preview.entries as entry}
										<div
											class="rounded-2xl border border-gray-100 dark:border-gray-850 px-3.5 py-3"
										>
											<div class="flex items-start justify-between gap-3">
												<div class="min-w-0">
													<div class="text-sm font-medium truncate">{entry.display_name}</div>
													<div class="mt-2 flex flex-wrap items-center gap-1.5">
														{#each previewEntryBadges(entry) as badge}
															<div
																class="rounded-full border border-gray-200 dark:border-gray-800 px-2 py-0.5 text-[0.7rem] text-gray-600 dark:text-gray-300"
															>
																{badge}
															</div>
														{/each}
														<div class="text-xs text-gray-500 dark:text-gray-400">
															{entry.runtime_type} · {entry.kind}
														</div>
													</div>
												</div>
												<div
													class={`shrink-0 rounded-full px-2 py-1 text-[0.7rem] font-medium ${statusClassName(entry.status)}`}
												>
													{statusLabel(entry.status)}
												</div>
											</div>

											<div class="mt-2 text-xs text-gray-500 dark:text-gray-400 break-all">
												{entry.status_reason}
											</div>

											<div class="mt-3 flex justify-end">
												<button
													class="rounded-xl px-3 py-2 text-sm bg-gray-900 text-white dark:bg-white dark:text-gray-900 disabled:opacity-60"
													disabled={!canRegister(entry) ||
														registeringCandidateId === entry.candidate_id}
													on:click={() => registerEntry(entry)}
												>
													{#if registeringCandidateId === entry.candidate_id}
														{$i18n.t('Registering...')}
													{:else}
														{$i18n.t('Register')}
													{/if}
												</button>
											</div>
										</div>
									{/each}
								</div>
							{/if}
						{/if}
					</div>
				</div>
			</div>
		</div>
	</div>
</Modal>
