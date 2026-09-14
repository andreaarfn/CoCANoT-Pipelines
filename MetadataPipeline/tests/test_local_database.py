from MetadataPipeline.storage import LocalMetadataStore


def test_site_id_round_trip(tmp_path):
    store = LocalMetadataStore(
        tmp_path / "metadata.sqlite3"
    )

    assert store.get_site_id() == ""

    store.set_site_id("UMN")

    assert store.get_site_id() == "UMN"


def test_first_assessment_is_ca_001(tmp_path):
    store = LocalMetadataStore(
        tmp_path / "metadata.sqlite3"
    )

    result = store.save_clinical_assessment(
        "UMN",
        "P001",
        {
            "CoCANoT Patient ID": "P001",
            "Epilepsy Type": "Focal",
            "Comments (free text)": "",
        },
        tracked_fields=["Epilepsy Type"],
    )

    assert result["assessment_id"] == "CA-001"
    assert result["action"] == "created"


def test_tracked_change_creates_next_assessment(tmp_path):
    store = LocalMetadataStore(
        tmp_path / "metadata.sqlite3"
    )

    store.save_clinical_assessment(
        "UMN",
        "P001",
        {
            "CoCANoT Patient ID": "P001",
            "Epilepsy Type": "Focal",
        },
        tracked_fields=["Epilepsy Type"],
    )

    result = store.save_clinical_assessment(
        "UMN",
        "P001",
        {
            "CoCANoT Patient ID": "P001",
            "Epilepsy Type": "Generalized",
        },
        tracked_fields=["Epilepsy Type"],
    )

    assert result["assessment_id"] == "CA-002"
    assert result["action"] == "created_new_assessment"


def test_untracked_change_keeps_same_assessment_id(tmp_path):
    store = LocalMetadataStore(
        tmp_path / "metadata.sqlite3"
    )

    store.save_clinical_assessment(
        "UMN",
        "P001",
        {
            "CoCANoT Patient ID": "P001",
            "Epilepsy Type": "Focal",
            "Comments (free text)": "Original",
        },
        tracked_fields=["Epilepsy Type"],
    )

    result = store.save_clinical_assessment(
        "UMN",
        "P001",
        {
            "CoCANoT Patient ID": "P001",
            "Epilepsy Type": "Focal",
            "Comments (free text)": "Corrected",
        },
        tracked_fields=["Epilepsy Type"],
    )

    assert result["assessment_id"] == "CA-001"
    assert result["action"] == "corrected_existing"


def test_patient_ids_are_scoped_by_site(tmp_path):
    store = LocalMetadataStore(
        tmp_path / "metadata.sqlite3"
    )

    umn = store.save_clinical_assessment(
        "UMN",
        "001",
        {
            "CoCANoT Patient ID": "001",
            "Epilepsy Type": "Focal",
        },
        tracked_fields=["Epilepsy Type"],
    )

    mayo = store.save_clinical_assessment(
        "MAYO",
        "001",
        {
            "CoCANoT Patient ID": "001",
            "Epilepsy Type": "Generalized",
        },
        tracked_fields=["Epilepsy Type"],
    )

    assert umn["assessment_id"] == "CA-001"
    assert mayo["assessment_id"] == "CA-001"

    assert (
        store.latest_clinical_assessment(
            "UMN",
            "001",
        )["metadata"]["Epilepsy Type"]
        == "Focal"
    )
