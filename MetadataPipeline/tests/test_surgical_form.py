from MetadataPipeline.forms.surgical_form import (
    build_surgical_form,
    build_surgical_record,
)


def test_build_surgical_form_uses_dictionary():
    dictionary = {
        "tables": {
            "Surgical": {
                "fields": [
                    {
                        "field_order": 1,
                        "field_name": "Surgery ID",
                        "ui_prompt": "Enter Surgery ID",
                        "help_text": "",
                        "input_type": "identifier",
                        "allowed_values": [],
                        "required": True,
                        "required_if_field": None,
                        "required_if_operator": None,
                        "required_if_value": None,
                        "manual_review_required": False,
                        "system_generated": False,
                    }
                ]
            }
        }
    }

    fields = build_surgical_form(
        dictionary
    )

    assert len(fields) == 1
    assert fields[0]["field_name"] == "Surgery ID"
    assert fields[0]["label"] == "Enter Surgery ID"


def test_build_surgical_record_merges_context():
    record = build_surgical_record(
        {
            "Clinical Assessment ID": "CA-001",
        },
        {
            "Surgery ID": "001",
        },
    )

    assert record == {
        "Clinical Assessment ID": "CA-001",
        "Surgery ID": "001",
    }
