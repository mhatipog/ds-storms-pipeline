"""As-of lookup for NHC observed wind buffers used by WSP cut-outs.

Each observation is a cumulative wind swath. A WSP issued at ``it`` may
be paired with the latest available observation at or before ``it + offset``;
an exact timestamp match is not required for special/off-cycle advisories.
"""

from bisect import bisect_right


def index_obsv_times(obsv_lookup: dict) -> dict:
    """Index timestamps by (storm, wind threshold) for logarithmic lookups.

    ``obsv_lookup`` is keyed by (atcf_id, valid_time, wind_speed_kt).
    The index never mixes observations from different storms or thresholds.
    """
    index = {}
    for atcf_id, valid_time, wind_speed_kt in obsv_lookup:
        index.setdefault((atcf_id, wind_speed_kt), []).append(valid_time)
    for times in index.values():
        times.sort()
    return index


def latest_obsv_at_or_before(
    obsv_times: dict,
    obsv_lookup: dict,
    atcf_id: str,
    wind_speed_kt: int,
    cutoff,
) -> tuple:
    """Return ``(valid_time, geometry)`` of the newest eligible observation.

    Never consume observations after the cutoff, even if they exist for the
    same storm and threshold. Return ``(None, None)`` on no eligible record.
    """
    times = obsv_times.get((atcf_id, wind_speed_kt), ())
    pos = bisect_right(times, cutoff)
    if pos == 0:
        return None, None
    valid_time = times[pos - 1]
    return valid_time, obsv_lookup[(atcf_id, valid_time, wind_speed_kt)]
