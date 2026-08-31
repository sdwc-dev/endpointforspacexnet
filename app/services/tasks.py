"""
app/services/tasks.py — Google Cloud Tasks integration.
"""
from __future__ import annotations

import os
import json
from google.cloud import tasks_v2
from app.config import settings
from app.utils.logging import get_logger

log = get_logger(__name__)

client = None

def get_tasks_client():
    global client
    if client is None:
        if settings.google_application_credentials:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.google_application_credentials
        client = tasks_v2.CloudTasksClient()
    return client

async def enqueue_batch_task(
    job_id: str,
    leads_batch: list[dict],
    callback_url: str,
    auth_key: str,
    file_key: str,
) -> None:
    """Enqueue a batch of leads for enrichment via Google Cloud Tasks."""
    tasks_client = get_tasks_client()
    project = settings.firebase_project_id
    location = settings.gcp_location
    queue = settings.cloud_tasks_queue_name

    if not project:
        log.warning("GCP Project ID not set. Skipping Cloud Task enqueue.")
        return

    parent = tasks_client.queue_path(project, location, queue)

    url = f"{settings.api_base_url.rstrip('/')}/api/internal/process-batch"
    
    payload = {
        "job_id": job_id,
        "leads_batch": leads_batch,
        "callback_url": callback_url,
        "auth_key": auth_key,
        "file_key": file_key,
    }
    
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": url,
            "headers": {
                "Content-type": "application/json",
                "X-Internal-Auth": settings.internal_auth_token,
            },
            "body": json.dumps(payload).encode("utf-8"),
        }
    }
    
    try:
        response = tasks_client.create_task(request={"parent": parent, "task": task})
        log.info("Enqueued batch task", task_name=response.name, job_id=job_id, batch_size=len(leads_batch))
    except Exception as e:
        log.error("Failed to enqueue batch task", error=str(e), job_id=job_id, batch_size=len(leads_batch))
        raise
