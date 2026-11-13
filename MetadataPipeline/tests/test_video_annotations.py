"""Unit tests for CoCANoT video timeline annotation validation."""
import pytest

from VideoPipeline.processing import validate_video_annotations


def test_annotations_are_sorted_and_final_video_relative():
    items = [
        {"id": "b", "onset": 30, "duration": 4, "description": "Movement"},
        {"id": "a", "onset": 10, "duration": 5, "description": "Seizure"},
    ]
    result = validate_video_annotations(items, 60)
    assert [item["description"] for item in result] == ["Seizure", "Movement"]
    assert all("id" not in item for item in result)
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
    {"onset": 1, "duration": "2.0JS:2", "description": "Invalid suffix"},
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


def test_internal_ids_are_not_exported():
    result = validate_video_annotations(
        [{"id": "internal-key", "onset": 2, "duration": 3,
          "description": "Observed event"}], 10
    )
    assert result == [{"onset": 2.0, "duration": 3.0,
                       "description": "Observed event"}]


def test_valid_duration_is_serialized_as_plain_number():
    result = validate_video_annotations(
        [{"onset": 1.5438862, "duration": "2.0",
          "description": "SEIZURE"}], 20
    )
    assert result[0]["duration"] == 2.0
    assert isinstance(result[0]["duration"], int)
    assert result[0]["onset"] == 1.54
    assert isinstance(result[0]["onset"], float)


def test_whole_second_times_have_no_float_notation_in_json():
    import json
    result = validate_video_annotations(
        [{"onset": 10.0, "duration": 2.0, "description": "Seizure"}], 20
    )
    assert json.dumps(result) == (
        '[{"onset": 10, "duration": 2, "description": "Seizure"}]'
    )


def test_annotation_times_round_to_two_decimal_places():
    result = validate_video_annotations([
        {"onset": 1.5438862, "duration": 2.1356,
         "description": "Clinical event"},
    ], 20)
    assert result == [{
        "onset": 1.54, "duration": 2.14, "description": "Clinical event",
    }]
    assert round(result[0]["onset"] + result[0]["duration"], 2) == 3.68


def test_half_centisecond_rounds_up():
    result = validate_video_annotations([
        {"onset": 1.545, "duration": 0.005,
         "description": "Brief marker"},
    ], 20)
    assert result[0]["onset"] == 1.55
    assert result[0]["duration"] == 0.01
