"""Clinical and Surgical metadata file ingestion."""

from .batch_ingestion import validate_uploaded_metadata
from .file_loader import MetadataFileError, load_metadata_file
from .record_normalizer import normalize_record
from .table_detector import TableDetectionError, detect_upload_table

__all__ = [
    "MetadataFileError",
    "TableDetectionError",
    "detect_upload_table",
    "load_metadata_file",
    "normalize_record",
    "validate_uploaded_metadata",
]
