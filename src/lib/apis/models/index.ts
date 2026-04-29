import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getModelItems = async (
	token: string = '',
	query,
	viewOption,
	selectedTag,
	orderBy,
	direction,
	page
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (query) {
		searchParams.append('query', query);
	}
	if (viewOption) {
		searchParams.append('view_option', viewOption);
	}
	if (selectedTag) {
		searchParams.append('tag', selectedTag);
	}
	if (orderBy) {
		searchParams.append('order_by', orderBy);
	}
	if (direction) {
		searchParams.append('direction', direction);
	}
	if (page) {
		searchParams.append('page', page.toString());
	}

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/list?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getModelTags = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/tags`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const importModels = async (token: string, models: object[]) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/import`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ models: models })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getBaseModels = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/base`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const createNewModel = async (token: string, model: object) => {
	let error = null;

	const { id, base_model_id, name, meta, params, access_grants, is_active } = model as any;
	const payload = { id, base_model_id, name, meta, params, access_grants, is_active };

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(payload)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getModelById = async (token: string, id: string) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('id', id);

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const toggleModelById = async (token: string, id: string) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('id', id);

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model/toggle?${searchParams.toString()}`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateModelById = async (token: string, id: string, model: object) => {
	let error = null;

	const { base_model_id, name, meta, params, access_grants, is_active } = model as any;
	const payload = { id, base_model_id, name, meta, params, access_grants, is_active };

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(payload)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateModelAccessGrants = async (
	token: string,
	id: string,
	name: string,
	accessGrants: any[]
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model/access/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ id, name, access_grants: accessGrants })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteModelById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model/delete`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ id })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteAllModels = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/delete/all`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

type RuntimeRegisteredModel = {
	model_id?: string;
	display_name?: string;
	runtime_type?: string;
	kind?: string;
	status?: string;
	catalog_origin?: string;
	user_selectable?: boolean;
	capabilities?: Record<string, unknown> | null;
};

type RuntimeManagedModel = {
	id?: string;
	meta?: Record<string, unknown> | null;
	info?: {
		meta?: Record<string, unknown> | null;
	} | null;
};

type RuntimeRegistrationMeta = {
	managed?: boolean;
	model_id?: string | null;
	catalog_origin?: string | null;
	runtime_type?: string | null;
	kind?: string | null;
	status?: string | null;
	user_selectable?: boolean | null;
};

const asRecord = (value: unknown): Record<string, any> => {
	if (value && typeof value === 'object' && !Array.isArray(value)) {
		return value as Record<string, any>;
	}
	return {};
};

const buildRuntimeRegistrationMeta = (
	runtimeModel: RuntimeRegisteredModel,
	managed: boolean,
	currentMeta: Record<string, unknown> = {}
): RuntimeRegistrationMeta => {
	const currentRuntimeRegistration = asRecord(currentMeta?.runtime_registration);

	return {
		...currentRuntimeRegistration,
		managed,
		model_id: runtimeModel.model_id ?? currentRuntimeRegistration.model_id ?? null,
		catalog_origin: runtimeModel.catalog_origin ?? currentRuntimeRegistration.catalog_origin ?? null,
		runtime_type: runtimeModel.runtime_type ?? currentRuntimeRegistration.runtime_type ?? null,
		kind: runtimeModel.kind ?? currentRuntimeRegistration.kind ?? null,
		status: runtimeModel.status ?? currentRuntimeRegistration.status ?? null,
		user_selectable: runtimeModel.user_selectable ?? currentRuntimeRegistration.user_selectable ?? null
	};
};

const getModelMetaSources = (model: RuntimeManagedModel | null | undefined) => {
	const modelRecord = asRecord(model);
	const infoRecord = asRecord(modelRecord.info);
	return {
		rootMeta: asRecord(modelRecord.meta),
		infoMeta: asRecord(infoRecord.meta)
	};
};

export const getRuntimeRegistrationMeta = (
	model: RuntimeManagedModel | null | undefined
): RuntimeRegistrationMeta | null => {
	const { rootMeta, infoMeta } = getModelMetaSources(model);
	const rootRuntimeRegistration = asRecord(rootMeta.runtime_registration);
	const infoRuntimeRegistration = asRecord(infoMeta.runtime_registration);

	const runtimeRegistration = Object.keys(rootRuntimeRegistration).length
		? rootRuntimeRegistration
		: infoRuntimeRegistration;
	const catalogOrigin =
		(infoMeta.catalog_origin as string | undefined) ??
		(rootMeta.catalog_origin as string | undefined) ??
		(runtimeRegistration.catalog_origin as string | undefined) ??
		null;

	if (!catalogOrigin && Object.keys(runtimeRegistration).length === 0) {
		return null;
	}

	return {
		...runtimeRegistration,
		catalog_origin: catalogOrigin,
		managed:
			typeof runtimeRegistration.managed === 'boolean' ? runtimeRegistration.managed : undefined,
		model_id: (runtimeRegistration.model_id as string | undefined) ?? null,
		runtime_type:
			(infoMeta.runtime_type as string | undefined) ??
			(rootMeta.runtime_type as string | undefined) ??
			(runtimeRegistration.runtime_type as string | undefined) ??
			null,
		kind:
			(infoMeta.kind as string | undefined) ??
			(rootMeta.kind as string | undefined) ??
			(runtimeRegistration.kind as string | undefined) ??
			null,
		status:
			(infoMeta.catalog_status as string | undefined) ??
			(rootMeta.catalog_status as string | undefined) ??
			(runtimeRegistration.status as string | undefined) ??
			null,
		user_selectable:
			typeof runtimeRegistration.user_selectable === 'boolean'
				? runtimeRegistration.user_selectable
				: ((infoMeta.user_selectable as boolean | undefined) ?? null)
	};
};

export const isDynamicRuntimeModel = (model: RuntimeManagedModel | null | undefined) => {
	return getRuntimeRegistrationMeta(model)?.catalog_origin === 'dynamic';
};

export const unregisterRuntimeManagedModel = async (
	token: string,
	model: RuntimeManagedModel | null | undefined
) => {
	const modelRecord = asRecord(model);
	const modelId = `${modelRecord.id ?? ''}`.trim();
	if (!modelId) {
		throw new Error('runtime-model-id-required');
	}

	const runtimeRegistration = getRuntimeRegistrationMeta(model);
	await unregisterRuntimeModel(token, modelId);

	if (runtimeRegistration?.managed) {
		await deleteModelById(token, modelId);
	}

	return {
		model_id: modelId,
		removed_workspace_record: Boolean(runtimeRegistration?.managed)
	};
};

export const ensureRuntimeWorkspaceModelRecord = async (
	token: string,
	runtimeModel: RuntimeRegisteredModel
) => {
	const modelId = `${runtimeModel?.model_id ?? ''}`.trim();
	if (!modelId) {
		throw new Error('runtime-model-id-required');
	}

	let existingModel = null;
	try {
		existingModel = await getModelById(token, modelId);
	} catch (error) {
		existingModel = null;
	}

	if (existingModel) {
		const { rootMeta } = getModelMetaSources(existingModel);
		const currentRuntimeRegistration = getRuntimeRegistrationMeta(existingModel) ?? {};

		return await updateModelById(token, modelId, {
			id: modelId,
			base_model_id: existingModel?.base_model_id ?? null,
			name: `${existingModel?.name ?? modelId}`,
			meta: {
				...rootMeta,
				runtime_registration: buildRuntimeRegistrationMeta(
					runtimeModel,
					Boolean(currentRuntimeRegistration?.managed),
					rootMeta
				)
			},
			params: asRecord(existingModel?.params),
			access_grants: Array.isArray(existingModel?.access_grants) ? existingModel.access_grants : undefined,
			is_active: existingModel?.is_active ?? true
		});
	}

	return await createNewModel(token, {
		id: modelId,
		base_model_id: null,
		name: `${runtimeModel.display_name ?? modelId}`,
		meta: {
			profile_image_url: '/static/favicon.png',
			description: null,
			suggestion_prompts: null,
			capabilities:
				runtimeModel?.capabilities &&
				typeof runtimeModel.capabilities === 'object' &&
				!Array.isArray(runtimeModel.capabilities)
					? runtimeModel.capabilities
					: null,
			runtime_registration: buildRuntimeRegistrationMeta(runtimeModel, true)
		},
		params: {}
	});
};


export const browseRuntimeModelFolders = async (
	token: string,
	path: string | null = null,
	showHidden = false
) => {
	let error = null;
	const searchParams = new URLSearchParams();
	searchParams.append('show_hidden', String(showHidden));
	if (path) {
		searchParams.append('path', path);
	}

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/runtime-models/browse-folders?${searchParams.toString()}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getRuntimeModelScanFolders = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/runtime-models/scan-folders`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const addRuntimeModelScanFolder = async (token: string, path: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/runtime-models/scan-folders`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ path })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteRuntimeModelScanFolder = async (token: string, folderId: string) => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/runtime-models/scan-folders/${encodeURIComponent(folderId)}`,
		{
			method: 'DELETE',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getRuntimeModelCatalog = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/runtime-models/catalog`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getRuntimeModelsStatus = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/runtime-models/status`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const previewRuntimeModelPath = async (token: string, path: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/runtime-models/preview-path`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ path })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const createRuntimeModelScanJob = async (token: string, path: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/runtime-models/scan-jobs`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ path })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getRuntimeModelScanJob = async (token: string, jobId: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/runtime-models/scan-jobs/${encodeURIComponent(jobId)}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const cancelRuntimeModelScanJob = async (token: string, jobId: string) => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/runtime-models/scan-jobs/${encodeURIComponent(jobId)}/cancel`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const registerRuntimeModel = async (token: string, sourcePath: string, entry: object) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/runtime-models/register`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ source_path: sourcePath, entry })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const unregisterRuntimeModel = async (token: string, modelId: string) => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/runtime-models/${encodeURIComponent(modelId)}/registration`,
		{
			method: 'DELETE',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const loadRuntimeModel = async (token: string, modelId: string, deviceMode: string | null = null) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/runtime-models/${encodeURIComponent(modelId)}/load`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ ...(deviceMode && { device_mode: deviceMode }) })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const stopRuntimeModel = async (token: string, modelId: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/runtime-models/${encodeURIComponent(modelId)}/stop`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getRuntimeModelLoadJob = async (token: string, jobId: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/runtime-models/load-jobs/${encodeURIComponent(jobId)}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const cancelRuntimeModelLoadJob = async (token: string, jobId: string) => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/runtime-models/load-jobs/${encodeURIComponent(jobId)}/cancel`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
