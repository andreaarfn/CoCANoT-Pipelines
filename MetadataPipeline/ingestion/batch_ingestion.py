"""Load and validate Clinical or Surgical metadata uploads."""

from __future__ import annotations

from MetadataPipeline.validation.validator import MetadataValidator

from .file_loader import load_metadata_file
from .record_normalizer import normalize_record
from .table_detector import detect_upload_table


def validate_uploaded_metadata(dictionary, file_path):
    """Load one upload, detect its table, and validate every row."""
    loaded = load_metadata_file(file_path)

    table_name = detect_upload_table(
        dictionary,
        loaded["columns"],
    )

    validator = MetadataValidator(dictionary)
    row_results = []

    for row_number, uploaded_record in enumerate(
        loaded["rows"],
        start=2,
    ):
        record = normalize_record(
            dictionary,
            table_name,
            uploaded_record,
        )

        validation = validator.validate_record(
            table_name,
            record,
        )

        row_results.append({
            "row_number": row_number,
            "record": record,
            "validation": validation,
        })

    return {
        "source_file": loaded["source_file"],
        "sheet_name": loaded["sheet_name"],
        "table_name": table_name,
        "row_count": len(row_results),
        "rows": row_results,
    }
