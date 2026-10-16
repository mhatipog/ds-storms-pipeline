"""In-process regression for NHC WSP forecast-only cutouts.

Pipeline database I/O is mocked. Requires project dependencies; no DB or NHC
network access is necessary.
"""
from datetime import datetime
from unittest.mock import MagicMock

import geopandas as gpd
from shapely import wkt
from shapely.geometry import box

from src.pipelines import nhc


def test_offcycle_advisory_is_subtracted_from_forecast_only(monkeypatch):
    atcf_id = "AL012026"
    issuance = datetime(2026, 8, 15, 15)
    intermediate = datetime(2026, 8, 15, 16, 30)
    future = datetime(2026, 8, 15, 19)
    wsp = gpd.GeoDataFrame([{
        "issued_time": issuance,
        "wind_threshold_kt": 34,
        "percentage": 50,
        "atcf_id": atcf_id,
        "geometry": box(0, 0, 4, 4),
    }], geometry="geometry", crs="EPSG:4326")
    lookup = {
        (atcf_id, intermediate, 34): box(0, 0, 2, 4),
        (atcf_id, future, 34): box(0, 0, 4, 4),
    }
    written = []
    monkeypatch.setattr(nhc, "_load_wsp_for_exposure", lambda *a, **k: wsp)
    monkeypatch.setattr(nhc, "_load_obsv_buffer_lookup", lambda *a: lookup)
    monkeypatch.setattr(
        nhc, "_write_wsp_fcastonly_batch",
        lambda batch, engine, chunksize: written.extend(batch),
    )
    engine = MagicMock()
    nhc.process_nhc_wsp_fcastonly_polygons(
        engine=engine, issued_time=issuance, overwrite=True,
    )
    assert len(written) == 1
    assert written[0]["obsv_valid_time"] == intermediate
    assert wkt.loads(written[0]["geometry"]).area == 8
    engine.begin.return_value.__enter__.return_value.execute.assert_called()
