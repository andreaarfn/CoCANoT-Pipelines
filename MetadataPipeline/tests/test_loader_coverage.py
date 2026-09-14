from pathlib import Path

from MetadataPipeline.validation.dictionary_loader import load_dictionary


DICTIONARY = (
    Path(__file__).resolve().parents[1]
    / "dictionaries"
    / "CoCANoT_Metadata_Phase1.xlsx"
)


def test_every_loaded_row_preserves_original_machine_columns():
    dictionary = load_dictionary(DICTIONARY)

    for table in dictionary["tables"].values():
        original_columns = set(table["columns"])

        for field in table["fields"]:
            loaded_original_columns = {
                key for key in field
                if not key.startswith("_")
                and key not in {"allowed_values", "conditional_allowed_values"}
            }

            assert loaded_original_columns == original_columns


def test_json_columns_are_parsed_for_every_row():
    dictionary = load_dictionary(DICTIONARY)

    for table in dictionary["tables"].values():
        for field in table["fields"]:
            assert type(field["allowed_values"]) is list
            assert type(field["conditional_allowed_values"]) is dict
