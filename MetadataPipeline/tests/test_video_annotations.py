"""Unit tests for CoCANoT video timeline annotation validation."""
import pytest

from VideoPipeline.processing import validate_video_annotations


def test_annotations_are_sorted_and_final_video_relative():
    items = [
        {"id": "b", "onset": 30, "duration": 4, "description": "Movement"},
        {"id": "a", "onset": 10, "duration": 5, "description": "Seizure"},
    ]
    result = validate_video_annotations(items, 60)
    assert [item["id"] for item in result] == ["a", "b"]
    assert result[0]["onset"] == 10.0
    assert result[1]["duration"] == 4.0


def test_instant_events_can_have_zero_duration():
    result = validate_video_annotations(
        [{"onset": 8, "duration": 0, "description": "Event marker"}], 20
    )
    assert result[0]["duration"] == 0


@pytest.mark.parametrize("item", [
    {"onset": -1, "duration": 3, "description": "Negative"},
    {"onset": 8, "duration": 3, "description": "Beyond end"},
    {"onset": 1, "duration": -1, "description": "Invalid duration"},
    {"onset": "nan", "duration": 1, "description": "Not finite"},
    {"onset": 1, "duration": 1, "description": ""},
])
def test_reject_bad_or_incomplete_events(item):
    with pytest.raises(ValueError):
        validate_video_annotations([item], 10)


def test_reject_duplicate_event_ids():
    events = [
        {"id": "same", "onset": 1, "duration": 1, "description": "First"},
        {"id": "same", "onset": 2, "duration": 1, "description": "Second"},
    ]
    with pytest.raises(ValueError):
        validate_video_annotations(events, 10)


def test_reject_too_many_events():
    with pytest.raises(ValueError):
        validate_video_annotations([{}] * 2001, 10)
