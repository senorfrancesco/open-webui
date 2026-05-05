from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from open_webui.services import runtime_models as runtime_models_service
from open_webui.utils.auth import get_admin_user, get_verified_user


router = APIRouter()


class ScanFolderForm(BaseModel):
    path: str


class PreviewPathForm(BaseModel):
    path: str


class RegisterRuntimeModelForm(BaseModel):
    source_path: str
    entry: Dict[str, Any]


class LoadRuntimeModelForm(BaseModel):
    device_mode: Optional[str] = None


def _raise_proxy_http_error(exc: runtime_models_service.RuntimeModelProxyError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get('/status')
async def get_runtime_models_status(request: Request, user=Depends(get_verified_user)):
    return await runtime_models_service.get_status(request)


@router.get('/browse-folders')
async def browse_folders(
    request: Request,
    path: Optional[str] = None,
    show_hidden: bool = False,
    user=Depends(get_admin_user),
):
    try:
        return await runtime_models_service.browse_folders(request, path=path, show_hidden=show_hidden)
    except runtime_models_service.RuntimeModelProxyError as exc:
        _raise_proxy_http_error(exc)


@router.get('/scan-folders')
async def get_scan_folders(request: Request, user=Depends(get_admin_user)):
    try:
        return await runtime_models_service.list_scan_folders(request)
    except runtime_models_service.RuntimeModelProxyError as exc:
        _raise_proxy_http_error(exc)


@router.post('/scan-folders')
async def add_scan_folder(
    form_data: ScanFolderForm,
    request: Request,
    user=Depends(get_admin_user),
):
    try:
        return await runtime_models_service.add_scan_folder(request, form_data.path)
    except runtime_models_service.RuntimeModelProxyError as exc:
        _raise_proxy_http_error(exc)


@router.delete('/scan-folders/{folder_id}')
async def delete_scan_folder(folder_id: str, request: Request, user=Depends(get_admin_user)):
    try:
        return await runtime_models_service.delete_scan_folder(request, folder_id)
    except runtime_models_service.RuntimeModelProxyError as exc:
        _raise_proxy_http_error(exc)


@router.post('/preview-path')
async def preview_path(
    form_data: PreviewPathForm,
    request: Request,
    user=Depends(get_admin_user),
):
    try:
        return await runtime_models_service.preview_path(request, form_data.path)
    except runtime_models_service.RuntimeModelProxyError as exc:
        _raise_proxy_http_error(exc)


@router.get('/catalog')
async def get_runtime_model_catalog(request: Request, user=Depends(get_verified_user)):
    try:
        return await runtime_models_service.list_catalog(request)
    except runtime_models_service.RuntimeModelProxyError as exc:
        _raise_proxy_http_error(exc)


@router.post('/register')
async def register_runtime_model(
    form_data: RegisterRuntimeModelForm,
    request: Request,
    user=Depends(get_admin_user),
):
    try:
        return await runtime_models_service.register_model(request, form_data.source_path, form_data.entry)
    except runtime_models_service.RuntimeModelProxyError as exc:
        _raise_proxy_http_error(exc)


@router.delete('/{model_id}/registration')
async def unregister_runtime_model(
    model_id: str,
    request: Request,
    user=Depends(get_admin_user),
):
    try:
        return await runtime_models_service.unregister_model(request, model_id)
    except runtime_models_service.RuntimeModelProxyError as exc:
        _raise_proxy_http_error(exc)


@router.post('/{model_id}/load')
async def load_runtime_model(
    model_id: str,
    form_data: LoadRuntimeModelForm,
    request: Request,
    user=Depends(get_admin_user),
):
    try:
        return await runtime_models_service.load_model(request, model_id, device_mode=form_data.device_mode)
    except runtime_models_service.RuntimeModelProxyError as exc:
        _raise_proxy_http_error(exc)


@router.get('/load-jobs/{job_id}')
async def get_runtime_model_load_job(
    job_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    try:
        return await runtime_models_service.get_load_job(request, job_id)
    except runtime_models_service.RuntimeModelProxyError as exc:
        _raise_proxy_http_error(exc)


@router.post('/load-jobs/{job_id}/cancel')
async def cancel_runtime_model_load_job(
    job_id: str,
    request: Request,
    user=Depends(get_admin_user),
):
    try:
        return await runtime_models_service.cancel_load_job(request, job_id)
    except runtime_models_service.RuntimeModelProxyError as exc:
        _raise_proxy_http_error(exc)
