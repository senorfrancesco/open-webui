from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from open_webui.services import deep_jobs as deep_jobs_service
from open_webui.utils.auth import get_verified_user


router = APIRouter()


class DeepJobDeliveryRequest(BaseModel):
    result_message_id: str
    terminal_emitted_at: Optional[str] = None


def _raise_proxy_http_error(exc: deep_jobs_service.DeepJobProxyError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get('/deep-jobs/{job_id}')
async def get_deep_job(job_id: str, request: Request, user=Depends(get_verified_user)):
    try:
        return await deep_jobs_service.get_deep_job_snapshot(request, job_id)
    except deep_jobs_service.DeepJobProxyError as exc:
        _raise_proxy_http_error(exc)


@router.post('/deep-jobs/{job_id}/cancel')
async def cancel_deep_job(job_id: str, request: Request, user=Depends(get_verified_user)):
    try:
        return await deep_jobs_service.cancel_deep_job_snapshot(request, job_id)
    except deep_jobs_service.DeepJobProxyError as exc:
        _raise_proxy_http_error(exc)


@router.get('/deep-jobs/{job_id}/result')
async def get_deep_job_result(job_id: str, request: Request, user=Depends(get_verified_user)):
    try:
        return await deep_jobs_service.get_deep_job_result_payload(request, job_id)
    except deep_jobs_service.DeepJobProxyError as exc:
        _raise_proxy_http_error(exc)


@router.get('/deep-jobs/{job_id}/artifacts/{artifact_id}/download')
async def download_deep_job_artifact(
    job_id: str,
    artifact_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    try:
        artifact = await deep_jobs_service.download_deep_job_artifact(request, job_id, artifact_id)
    except deep_jobs_service.DeepJobProxyError as exc:
        _raise_proxy_http_error(exc)

    headers = {}
    if artifact.get('content_disposition'):
        headers['Content-Disposition'] = artifact['content_disposition']
    elif artifact.get('filename'):
        headers['Content-Disposition'] = f'attachment; filename="{artifact["filename"]}"'

    return Response(
        content=artifact['content'],
        media_type=str(artifact.get('content_type') or 'application/octet-stream'),
        headers=headers,
    )


@router.post('/deep-jobs/{job_id}/delivery')
async def record_deep_job_delivery(
    job_id: str,
    payload: DeepJobDeliveryRequest,
    request: Request,
    user=Depends(get_verified_user),
):
    try:
        return await deep_jobs_service.record_deep_job_delivery(
            request,
            job_id,
            payload.result_message_id,
            payload.terminal_emitted_at,
        )
    except deep_jobs_service.DeepJobProxyError as exc:
        _raise_proxy_http_error(exc)


@router.get('/chats/{chat_id}/deep-jobs/active')
async def get_active_deep_job(chat_id: str, request: Request, user=Depends(get_verified_user)):
    try:
        return {'job': await deep_jobs_service.get_active_deep_job_snapshot(request, chat_id)}
    except deep_jobs_service.DeepJobProxyError as exc:
        _raise_proxy_http_error(exc)
