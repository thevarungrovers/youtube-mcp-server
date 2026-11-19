import csv
import json

import pytest

import youtube
from youtube.errors import InvalidRequestError, OAuthRequiredError
from youtube.export import export_dataset, write_rows

from tests.helpers import client, ok


def test_write_rows_csv_uses_union_of_keys(tmp_path):
    path = write_rows([{"day": "2026-11-01", "views": 1}, {"day": "2026-11-02", "views": 2, "likes": 3}], tmp_path / "x.csv")
    rows = list(csv.DictReader(path.open()))
    assert rows[1] == {"day": "2026-11-02", "views": "2", "likes": "3"} and rows[0]["likes"] == ""


def test_write_rows_jsonl(tmp_path):
    path = write_rows([{"term": "é"}], tmp_path / "sub" / "x.jsonl", "jsonl")
    assert json.loads(path.read_text()) == {"term": "é"}


def test_unknown_dataset_and_format(tmp_path):
    c, _ = client(oauth=True)
    with pytest.raises(InvalidRequestError, match="Unknown dataset"):
        export_dataset(c, "everything", "2026-11-01", "2026-11-02")
    with pytest.raises(InvalidRequestError, match="format"):
        write_rows([], tmp_path / "x.xml", "xml")


def test_analytics_dataset_needs_oauth():
    c, _ = client()
    with pytest.raises(OAuthRequiredError):
        export_dataset(c, "channel_daily", "2026-11-01", "2026-11-02")


def test_video_daily_batches_ids(monkeypatch):
    from youtube import export

    monkeypatch.setattr(export, "_all_uploads", lambda c: [{"video_id": f"v{i}"} for i in range(60)])
    filters = []

    def fake_query(client, start, end, metrics, **kw):
        filters.append(kw["filters"])
        return [{"day": "2026-11-01", "video": kw["filters"].split("==")[1].split(",")[0], "views": 1}]

    monkeypatch.setattr(export, "_query", fake_query)
    c, _ = client(oauth=True)
    rows = export_dataset(c, "video_daily", "2026-11-01", "2026-11-01")
    assert len(filters) == 2 and filters[0].count(",") == 49
    assert [r["video"] for r in rows] == ["v0", "v50"]


def test_channel_daily_rows():
    c, _ = client(ok({"columnHeaders": [{"name": "day"}, {"name": "views"}], "rows": [["2026-11-01", 5]]}), oauth=True)
    assert export_dataset(c, "channel_daily", "2026-11-01", "2026-11-01") == [{"day": "2026-11-01", "views": 5}]
