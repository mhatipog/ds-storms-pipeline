"""Only mocked NOAA archive retrievals; no network access in tests."""
from datetime import datetime,timezone
from pathlib import Path
import json
import pytest
from storm_audit.archive_harvester import harvest,_download_noaa
from storm_audit.snapshot_timeline import SourceIntegrityError

HTML='''<a href="CurrentStorms_2026-10-01_0330.json">shortened ..</a>
<a href="CurrentStorms_2026-10-01_0930.json">second</a>
<a href="CurrentStorms_2026-10-02_0330.json">other day</a>
<a href="https://example.org/CurrentStorms_2026-10-01_1030.json">blocked</a>'''


def data(i="042"):
    return json.dumps({"activeStorms":[{
        "id":"ep152026","publicAdvisory":{
            "advNum":i,"issuance":"2026-10-01T03:00:00Z"}}]}).encode()


def test_catalog_only_never_invokes_downloader(tmp_path):
    def forbidden(_):raise AssertionError("unexpected network")
    r=harvest(HTML,"2026-10-01",tmp_path,downloader=forbidden)
    assert r["downloaded_count"]==0
    assert r["discovered_href_count"]==2
    assert r["capture_time_assurance"]=="historical_capture_times_not_established"
    assert not list(tmp_path.glob("*.json"))


def test_explicit_fetch_preserves_bytes_hash_and_retrieval_metadata(tmp_path):
    calls=[];sleep=[]
    def downloader(url):calls.append(url);return data("042" if "0330" in url else "043")
    def clock():return datetime(2026,10,16,8,tzinfo=timezone.utc)
    r=harvest(HTML,"2026-10-01",tmp_path,fetch=True,downloader=downloader,
              clock=clock,sleeper=sleep.append,min_interval_seconds=1.5)
    assert r["discovered_href_count"]==r["downloaded_count"]==2
    assert sleep==[1.5]
    assert all(x["retrieved_at"]=="2026-10-16T08:00:00Z" for x in r["files"])
    assert all("observed_at" not in x for x in r["files"])
    assert all((tmp_path/x["filename"]).read_bytes() in (data("042"),data("043")) for x in r["files"])
    assert r["independent_poll_log"] is False


def test_excess_archive_files_fail_before_download(tmp_path):
    def fail(url):raise AssertionError("should not download")
    with pytest.raises(SourceIntegrityError,match="exceeds max_files"):
        harvest(HTML,"2026-10-01",tmp_path,fetch=True,max_files=1,downloader=fail)


def test_no_coverage_when_directory_has_no_matching_links(tmp_path):
    with pytest.raises(SourceIntegrityError,match="Zero matching"):
        harvest("<a href='OtherFile.json'>x</a>","2026-10-01",tmp_path)


def test_invalid_calendar_date_fails(tmp_path):
    with pytest.raises(ValueError,match="Invalid calendar"):
        harvest(HTML,"2026-02-31",tmp_path)


def test_explicit_fetch_rejects_malformed_noaa_payload(tmp_path):
    with pytest.raises(SourceIntegrityError,match="Invalid CurrentStorms"):
        harvest(HTML,"2026-10-01",tmp_path,fetch=True,downloader=lambda _:b"bad")


def test_revision_conflict_cannot_overwrite_local_file(tmp_path):
    path=tmp_path/"CurrentStorms_2026-10-01_0330.json"
    path.write_bytes(data("042"))
    html='<a href="CurrentStorms_2026-10-01_0330.json">here</a>'
    with pytest.raises(SourceIntegrityError,match="changed bytes"):
        harvest(html,"2026-10-01",tmp_path,fetch=True,downloader=lambda _:data("043"))
    assert path.read_bytes()==data("042")


def test_cross_domain_noaa_download_blocked_before_network():
    with pytest.raises(SourceIntegrityError,match="official NOAA"):
        _download_noaa("https://evil.example/archive/activeJson/2026/x.json")


def test_day_time_stamp_is_not_from_html_last_modified(tmp_path):
    html='''<a href="CurrentStorms_2026-10-01_0330.json">thing</a> 2026-10-01 03:31'''
    r=harvest(html,"2026-10-01",tmp_path)
    assert "retrieved_at" not in r["files"][0]
    assert "publication_at" not in r["files"][0]
    assert r["publication_time_assurance"]=="not_established"


def test_redirect_handler_allows_official_noaa_hosts():
    from storm_audit.archive_harvester import _NOAARedirectsOnly
    handler = _NOAARedirectsOnly()
    from unittest.mock import MagicMock
    req = MagicMock()
    req.get_method.return_value = "GET"
    req.headers = {}
    for host in ("www.nhc.noaa.gov", "prod-east-nhc.woc.noaa.gov"):
        url = f"https://{host}/archive/activeJson/2026/CurrentStorms_2026-10-01-0232.json"
        res = handler.redirect_request(req, None, 302, "Found", {}, url)
        assert res is not None
        assert res.full_url == url


def test_redirect_handler_rejects_unauthorized_hosts():
    from storm_audit.archive_harvester import _NOAARedirectsOnly
    handler = _NOAARedirectsOnly()
    req = None
    unauthorized = [
        "https://evil.example.com/archive/activeJson/2026/CurrentStorms_2026-10-01-0232.json",
        "http://www.nhc.noaa.gov/archive/activeJson/2026/CurrentStorms_2026-10-01-0232.json",
        "https://www.nhc.noaa.gov/other/path/CurrentStorms_2026-10-01-0232.json",
    ]
    for url in unauthorized:
        with pytest.raises(SourceIntegrityError, match="outside allowlist"):
            handler.redirect_request(req, None, 302, "Found", {}, url)

