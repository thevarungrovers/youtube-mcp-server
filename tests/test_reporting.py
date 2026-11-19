import pytest

import youtube
from youtube.errors import InvalidRequestError, OAuthRequiredError
from youtube.reporting import parse_report

from tests.helpers import client, ok


def test_list_report_types():
    c, _ = client(ok({"reportTypes": [{"id": "channel_basic_a3", "name": "User activity"}]}), oauth=True)
    assert youtube.list_report_types(c)["report_types"] == [{"id": "channel_basic_a3", "name": "User activity"}]


def test_create_job_refuses_duplicates():
    c, _ = client(ok({"jobs": [{"id": "j1", "reportTypeId": "channel_basic_a3"}]}), oauth=True)
    with pytest.raises(InvalidRequestError, match="already exists: j1"):
        youtube.create_reporting_job(c, "channel_basic_a3")


def test_create_job():
    c, _ = client(ok({}), ok({"id": "j2", "reportTypeId": "channel_reach_basic_a1", "name": "reach"}), oauth=True)
    job = youtube.create_reporting_job(c, "channel_reach_basic_a1", name="reach")
    assert job["id"] == "j2"


def test_list_reports_pages_and_sorts():
    c, _ = client(
        ok({"reports": [{"id": "r1", "startTime": "2026-11-01T07:00:00Z"}], "nextPageToken": "N"}),
        ok({"reports": [{"id": "r2", "startTime": "2026-11-02T07:00:00Z", "downloadUrl": "https://x"}]}),
        oauth=True,
    )
    reports = youtube.list_reports(c, "j1")["reports"]
    assert [r["id"] for r in reports] == ["r2", "r1"] and reports[0]["download_url"] == "https://x"


def test_download_report():
    csv_body = "date,channel_id,views\n20261101,UCx,5\n"
    c, _ = client(({"status": "200", "content-length": str(len(csv_body))}, csv_body), oauth=True)
    data = youtube.download_report(c, "https://youtubereporting.googleapis.com/v1/media/x?alt=media")
    assert parse_report(data) == [{"date": "20261101", "channel_id": "UCx", "views": "5"}]


def test_download_rejects_non_https():
    c, _ = client(oauth=True)
    with pytest.raises(InvalidRequestError):
        youtube.download_report(c, "file:///etc/passwd")


def test_reporting_needs_oauth():
    c, _ = client()
    with pytest.raises(OAuthRequiredError):
        youtube.list_reporting_jobs(c)
