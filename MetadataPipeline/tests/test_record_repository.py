from MetadataPipeline.storage.record_repository import (
    MetadataRepository,
)


def test_repository_saves_and_reads_surgical_record(
    tmp_path,
):
    repository = MetadataRepository(
        tmp_path / "metadata.sqlite3"
    )

    saved = repository.save_record(
        "umn",
        "Surgical",
        {
            "CoCANoT Patient ID": "001",
            "Surgery ID": "SURG-001",
            "Clinical Assessment ID": "CA-001",
        },
    )

    assert saved["site_id"] == "UMN"
    assert saved["patient_id"] == "001"
    assert saved["record_id"] == "SURG-001"

    records = repository.records_for_patient(
        "UMN",
        "001",
        "Surgical",
    )

    assert len(records) == 1
    assert records[0]["metadata"]["Surgery ID"] == "SURG-001"


def test_repository_updates_existing_record(
    tmp_path,
):
    repository = MetadataRepository(
        tmp_path / "metadata.sqlite3"
    )

    repository.save_record(
        "UMN",
        "Imaging",
        {
            "CoCANoT Patient ID": "001",
            "Image ID": "IMG-001",
            "Comments (free text)": "First",
        },
    )

    repository.save_record(
        "UMN",
        "Imaging",
        {
            "CoCANoT Patient ID": "001",
            "Image ID": "IMG-001",
            "Comments (free text)": "Corrected",
        },
    )

    records = repository.records_for_patient(
        "UMN",
        "001",
        "Imaging",
    )

    assert len(records) == 1
    assert (
        records[0]["metadata"]["Comments (free text)"]
        == "Corrected"
    )
