"""业务追踪时间推算与运行周期校验。"""

from __future__ import annotations

import pytest

from inspection_platform.inspection_work.tracking_times import (
    estimate_running_end,
    estimate_waiting_window,
    resolve_publish_snapshot,
    validate_schedule_fields,
)


def test_validate_schedule_periodic_requires_interval():
    with pytest.raises(ValueError, match="schedule_interval"):
        validate_schedule_fields("periodic", "", None)


def test_validate_schedule_scheduled_requires_times():
    with pytest.raises(ValueError, match="schedule_times"):
        validate_schedule_fields("scheduled", None, "")


def test_estimate_manual_waiting_has_no_window():
    from datetime import datetime

    base = datetime(2026, 7, 8, 18, 0, 0)
    start, end = estimate_waiting_window({"schedule_mode": "manual"}, base=base)
    assert start is None
    assert end is None


def test_estimate_scheduled_window():
    from datetime import datetime

    base = datetime(2026, 7, 8, 9, 0, 0)
    start, end = estimate_waiting_window(
        {"schedule_mode": "scheduled", "schedule_times": "14:00,20:00"},
        base=base,
    )
    assert start == "2026-07-08 14:00:00"
    assert end == "2026-07-08 15:00:00"


def test_estimate_continuous_waiting_has_no_end():
    from datetime import datetime

    base = datetime(2026, 7, 8, 10, 0, 0)
    start, end = estimate_waiting_window({"schedule_mode": "continuous"}, base=base)
    assert start == "2026-07-08 10:00:00"
    assert end is None


def test_estimate_running_end_continuous_is_none():
    from datetime import datetime

    started = datetime(2026, 7, 8, 10, 0, 0)
    assert estimate_running_end({"schedule_mode": "continuous"}, started_at=started) is None


def test_resolve_publish_manual():
    snap = resolve_publish_snapshot({"schedule_mode": "manual"})
    assert snap["queue_status"] == "waiting"
    assert snap["started_at"] is None
    assert snap["estimated_start_at"] is None


def test_estimate_scheduled_window_at_16():
    from datetime import datetime

    base = datetime(2026, 6, 29, 14, 28, 52)
    start, end = estimate_waiting_window(
        {"schedule_mode": "scheduled", "schedule_times": "16:00"},
        base=base,
    )
    assert start == "2026-06-29 16:00:00"
    assert end == "2026-06-29 17:00:00"


def test_parse_schedule_times_with_spaces():
    from datetime import datetime

    base = datetime(2026, 6, 29, 14, 0, 0)
    start, _ = estimate_waiting_window(
        {"schedule_mode": "scheduled", "schedule_times": "16 : 00"},
        base=base,
    )
    assert start == "2026-06-29 16:00:00"


def test_parse_schedule_times_with_fullwidth_colon():
    from datetime import datetime

    base = datetime(2026, 6, 29, 14, 0, 0)
    start, _ = estimate_waiting_window(
        {"schedule_mode": "scheduled", "schedule_times": "16：00"},
        base=base,
    )
    assert start == "2026-06-29 16:00:00"


def test_resolve_publish_periodic_with_iso_earliest_execution():
    snap = resolve_publish_snapshot(
        {"schedule_mode": "scheduled", "schedule_times": "08:00"},
        earliest_execution_at="2026-06-26T11:52:08Z",
    )
    assert snap["queue_status"] == "waiting"
    assert snap["estimated_start_at"] is not None


def test_parse_iso_z_datetime():
    from inspection_platform.inspection_work.tracking_times import parse_db_datetime

    dt = parse_db_datetime("2026-06-26T11:52:08Z")
    assert dt is not None
    assert dt.tzinfo is None


def test_resolve_publish_continuous_with_prior_execution():
    snap = resolve_publish_snapshot(
        {"schedule_mode": "continuous"},
        earliest_execution_at="2026-06-20 08:30:00",
    )
    assert snap["queue_status"] == "running"
    assert snap["started_at"] == "2026-06-20 08:30:00"
    assert snap["estimated_end_at"] is None
