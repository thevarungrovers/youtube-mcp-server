"""The YouTube Reporting API: Google-generated daily CSV reports, for bulk history.

Unlike the Analytics API, which answers queries, the Reporting API produces
one CSV per day for each *job* you schedule, and keeps them for 60 days (with
some history backfilled when a job is created). Some data exists only here,
such as thumbnail impressions and impression click-through rate
(``channel_reach_basic_a1``).

Creating a job is the one call in this package that changes anything: it
schedules report generation for the channel. It never touches videos or the
channel itself, and it is not exposed as an MCP tool.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from googleapiclient.http import MediaIoBaseDownload

from youtube.client import YouTubeClient
from youtube.errors import InvalidRequestError
from youtube.operations import operation

API = "YouTube Reporting API"


@operation(requires_oauth=True)
def list_report_types(client: YouTubeClient) -> dict[str, Any]:
    """The report types available to the channel (``channel_basic_a3``, ``channel_reach_basic_a1``, ...)."""
    response = client.execute(client.reporting.reportTypes().list(), api=API)
    return {"report_types": [{"id": t["id"], "name": t.get("name")} for t in response.get("reportTypes", [])]}


@operation(requires_oauth=True)
def list_reporting_jobs(client: YouTubeClient) -> dict[str, Any]:
    """The report jobs scheduled for the channel."""
    response = client.execute(client.reporting.jobs().list(), api=API)
    return {
        "jobs": [
            {"id": j["id"], "report_type_id": j.get("reportTypeId"), "name": j.get("name"), "created_at": j.get("createTime")}
            for j in response.get("jobs", [])
        ]
    }


@operation(requires_oauth=True)
def create_reporting_job(client: YouTubeClient, report_type_id: str, name: str | None = None) -> dict[str, Any]:
    """Schedule daily reports of one type. The first reports appear within about 48 hours.

    Args:
        client: The API client (OAuth).
        report_type_id: A type from :func:`list_report_types`.
        name: A label for the job (defaults to the type ID).

    Returns:
        ``{"id", "report_type_id", "name", "created_at"}``.

    Raises:
        InvalidRequestError: Unknown type, or a job for this type already exists.
    """
    report_type_id = (report_type_id or "").strip()
    if not report_type_id:
        raise InvalidRequestError("report_type_id must not be empty.")
    existing = [j for j in list_reporting_jobs(client)["jobs"] if j["report_type_id"] == report_type_id]
    if existing:
        raise InvalidRequestError(f"A job for {report_type_id} already exists: {existing[0]['id']}.")
    job = client.execute(
        client.reporting.jobs().create(body={"reportTypeId": report_type_id, "name": name or report_type_id}), api=API
    )
    return {"id": job["id"], "report_type_id": job.get("reportTypeId"), "name": job.get("name"), "created_at": job.get("createTime")}


@operation(requires_oauth=True)
def list_reports(client: YouTubeClient, job_id: str, created_after: str | None = None) -> dict[str, Any]:
    """The reports a job has produced, newest first, each covering one day.

    Args:
        client: The API client (OAuth).
        job_id: A job from :func:`list_reporting_jobs`.
        created_after: Only reports created after this RFC 3339 timestamp
            (e.g. ``2026-11-01T00:00:00Z``), to fetch just the new ones.

    Returns:
        ``{"job_id", "reports": [{id, start_time, end_time, created_at, download_url}]}``.
    """
    if not job_id or not job_id.strip():
        raise InvalidRequestError("job_id must not be empty.")
    reports: list[dict[str, Any]] = []
    params: dict[str, Any] = {"jobId": job_id.strip()}
    if created_after:
        params["createdAfter"] = created_after
    while True:
        response = client.execute(client.reporting.jobs().reports().list(**params), api=API)
        reports += [
            {
                "id": r["id"],
                "start_time": r.get("startTime"),
                "end_time": r.get("endTime"),
                "created_at": r.get("createTime"),
                "download_url": r.get("downloadUrl"),
            }
            for r in response.get("reports", [])
        ]
        if not response.get("nextPageToken"):
            break
        params["pageToken"] = response["nextPageToken"]
    reports.sort(key=lambda r: r["start_time"] or "", reverse=True)
    return {"job_id": job_id.strip(), "reports": reports}


@operation(requires_oauth=True)
def download_report(client: YouTubeClient, download_url: str) -> bytes:
    """Download one report's CSV (``download_url`` from :func:`list_reports`)."""
    if not download_url or not download_url.startswith("https://"):
        raise InvalidRequestError("download_url must be the https URL from list_reports.")
    request = client.reporting.media().download(resourceName="")
    request.uri = download_url
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    def run() -> dict[str, Any]:
        done = False
        while not done:
            _, done = downloader.next_chunk(num_retries=2)
        return {}

    client.execute(_Callable(run), api=API)
    return buffer.getvalue()


def parse_report(data: bytes) -> list[dict[str, str]]:
    """Parse a downloaded report CSV into rows."""
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"))))


def save_report(data: bytes, path: str | Path) -> Path:
    """Write a downloaded report to ``path``, creating its directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class _Callable:
    """Adapts a function to the ``execute()`` interface so downloads get the client's locking and error mapping."""

    def __init__(self, fn: Any) -> None:
        self._fn = fn

    def execute(self, num_retries: int = 0) -> Any:
        return self._fn()
