#!/usr/bin/env python3

"""Convert validated CoCANoT electrophysiology metadata and EDF files to BIDS."""



from __future__ import annotations



import argparse

import json

import re

import shutil

import sys

from collections import Counter

from pathlib import Path

from typing import Any, Dict, List, Optional



try:

    import pyedflib

except ImportError as exc:

    raise SystemExit(

        "pyedflib is required. Install it with:\n\n"

        "    python -m pip install pyedflib\n"

    ) from exc





SCRIPT_DIR = Path(__file__).resolve().parent

PIPELINE_DIR = SCRIPT_DIR.parent

PROJECT_ROOT = PIPELINE_DIR.parent



if str(PROJECT_ROOT) not in sys.path:

    sys.path.insert(0, str(PROJECT_ROOT))



from MetadataPipeline.storage.data_link_store import PatientDataLinkStore

from MetadataPipeline.validation import MetadataValidator, load_dictionary





SUPPORTED_BIDS_VERSION = "1.11.1"

METADATA_DICTIONARY_DIR = (

    PROJECT_ROOT

    / "MetadataPipeline"

    / "dictionaries"

)

METADATA_DICTIONARY_PATTERN = re.compile(

    r"^CoCANoT_Metadata_Phase(?P<version>\d+(?:\.\d+)*)\.xlsx$",

    re.IGNORECASE,

)



TASK_NAME = "clinicalmonitoring"





def _version_tuple(value: str) -> tuple[int, ...]:

    match = re.search(

        r"(\d+(?:\.\d+)*)",

        str(value or ""),

    )

    if match is None:

        raise ValueError(

            f"Could not parse dictionary version: {value!r}"

        )

    return tuple(

        int(part)

        for part in match.group(1).split(".")

    )





def active_metadata_dictionary() -> Path:

    if not METADATA_DICTIONARY_DIR.is_dir():

        raise FileNotFoundError(

            "Metadata dictionary directory does not exist: "

            f"{METADATA_DICTIONARY_DIR}"

        )



    candidates: list[tuple[tuple[int, ...], Path]] = []



    for path in METADATA_DICTIONARY_DIR.iterdir():

        if not path.is_file():

            continue



        match = METADATA_DICTIONARY_PATTERN.fullmatch(path.name)

        if match is None:

            continue



        version = tuple(

            int(part)

            for part in match.group("version").split(".")

        )

        candidates.append((version, path))



    if not candidates:

        raise FileNotFoundError(

            "No CoCANoT metadata dictionary matching "

            "'CoCANoT_Metadata_Phase*.xlsx' was found in "

            f"{METADATA_DICTIONARY_DIR}"

        )



    candidates.sort(key=lambda item: item[0])

    return candidates[-1][1]



RECORDING_MODALITY_TO_DATATYPE = {

    "Scalp EEG": "eeg",

    "Stereo EEG (SEEG)": "ieeg",

    "Subdural grid": "ieeg",

    "Subdural strips": "ieeg",

    "Depth electrodes (not SEEG)": "ieeg",

    "Intraoperative electrocorticography (ECoG)": "ieeg",

    "Magnetoencephalography (MEG)": "meg",

}





def load_json(path: Path) -> Dict[str, Any]:

    try:

        payload = json.loads(

            path.read_text(

                encoding="utf-8"

            )

        )

    except FileNotFoundError as exc:

        raise ValueError(

            f"JSON file does not exist: {path}"

        ) from exc

    except json.JSONDecodeError as exc:

        raise ValueError(

            f"Invalid JSON in {path}: {exc}"

        ) from exc



    if type(payload) is not dict:

        raise ValueError(

            f"JSON root must be an object: {path}"

        )



    return payload





def write_json(

    path: Path,

    payload: Dict[str, Any],

) -> None:

    path.parent.mkdir(

        parents=True,

        exist_ok=True,

    )

    path.write_text(

        json.dumps(

            payload,

            indent=2,

            allow_nan=False,

        )

        + "\n",

        encoding="utf-8",

    )





def json_safe_value(value: Any) -> Any:

    if value is None or isinstance(

        value,

        (str, int, float, bool),

    ):

        return value



    if isinstance(value, dict):

        return {

            str(key): json_safe_value(item)

            for key, item in value.items()

        }



    if isinstance(value, (list, tuple, set)):

        return [

            json_safe_value(item)

            for item in value

        ]



    if hasattr(value, "isoformat"):

        try:

            return value.isoformat()

        except Exception:

            pass



    if hasattr(value, "item"):

        try:

            return json_safe_value(value.item())

        except Exception:

            pass



    return str(value)





def write_tsv(

    path: Path,

    rows: List[Dict[str, Any]],

    columns: List[str],

) -> None:

    path.parent.mkdir(

        parents=True,

        exist_ok=True,

    )



    with path.open(

        "w",

        encoding="utf-8",

        newline="",

    ) as handle:

        handle.write(

            "\t".join(columns)

            + "\n"

        )



        for row in rows:

            values = []



            for column in columns:

                value = row.get(

                    column,

                    "n/a",

                )



                if value in (

                    None,

                    "",

                ):

                    value = "n/a"



                values.append(

                    str(value)

                    .replace(

                        "\t",

                        " ",

                    )

                    .replace(

                        "\n",

                        " ",

                    )

                )



            handle.write(

                "\t".join(values)

                + "\n"

            )





def clean_project(

    value: str,

) -> str:

    cleaned = re.sub(

        r"[\x00-\x1f/\\]+",

        "-",

        value.strip(),

    ).strip(

        " .-"

    )



    if not cleaned:

        raise ValueError(

            "Project must contain a usable folder name."

        )



    return cleaned





def clean_label(

    value: str,

    field: str,

) -> str:

    text = str(

        value

    ).strip()



    prefixes = {

        "participant_id": "sub-",

        "session_id": "ses-",

    }

    prefix = prefixes.get(

        field

    )



    if (

        prefix

        and text.lower().startswith(

            prefix

        )

    ):

        text = text[

            len(prefix):

        ]



    if not text:

        raise ValueError(

            f"{field} is required."

        )



    cleaned = re.sub(

        r"[^A-Za-z0-9+]",

        "",

        text,

    )



    if not cleaned:

        raise ValueError(

            f"{field} must contain at least one letter or number."

        )



    return cleaned





def read_edf_metadata(

    edf_path: Path,

) -> Dict[str, Any]:

    reader = pyedflib.EdfReader(

        str(edf_path)

    )



    try:

        sample_frequencies: List[

            Optional[float]

        ] = []



        for index in range(

            reader.signals_in_file

        ):

            try:

                sample_frequencies.append(

                    float(

                        reader.getSampleFrequency(

                            index

                        )

                    )

                )

            except Exception:

                sample_frequencies.append(

                    None

                )



        return {

            "file_header": json_safe_value(

                reader.getHeader()

            ),

            "channel_count": int(

                reader.signals_in_file

            ),

            "channel_labels": list(

                reader.getSignalLabels()

            ),

            "signal_headers": json_safe_value(

                list(

                    reader.getSignalHeaders()

                )

            ),

            "sample_frequencies": sample_frequencies,

            "duration_seconds": float(

                reader.file_duration

            ),

        }

    finally:

        reader.close()





def exact_auxiliary_channel_type(

    label: str,

) -> Optional[str]:

    normalized = re.sub(

        r"[\s_-]+",

        "",

        str(label).upper(),

    )



    return {

        "ECG": "ECG",

        "EKG": "ECG",

        "ECG1": "ECG",

        "EKG1": "ECG",

        "EOG": "EOG",

        "LOC": "EOG",

        "ROC": "EOG",

        "HEOG": "HEOG",

        "VEOG": "VEOG",

        "EMG": "EMG",

        "EMG1": "EMG",

        "TRIG": "TRIG",

        "TRIGGER": "TRIG",

        "STATUS": "TRIG",

        "EVENT": "TRIG",

        "MARKER": "TRIG",

    }.get(

        normalized

    )





def channel_type_for(

    label: str,

    datatype: str,

    recording_modality: str,

) -> str:

    auxiliary = (

        exact_auxiliary_channel_type(

            label

        )

    )



    if auxiliary is not None:

        return auxiliary



    if datatype == "eeg":

        return "EEG"



    if recording_modality == (

        "Stereo EEG (SEEG)"

    ):

        return "SEEG"



    if recording_modality in {

        "Subdural grid",

        "Subdural strips",

        "Intraoperative electrocorticography (ECoG)",

    }:

        return "ECOG"



    return "SEEG"





def primary_sampling_frequency(

    metadata: Dict[str, Any],

    record: Dict[str, Any],

) -> float:

    neural_types = (

        {"EEG"}

        if record["datatype"] == "eeg"

        else {

            "SEEG",

            "ECOG",

        }

    )



    frequencies = []



    for index, label in enumerate(

        metadata["channel_labels"]

    ):

        channel_type = channel_type_for(

            label,

            record["datatype"],

            record["recording_modality"],

        )

        frequency = metadata[

            "sample_frequencies"

        ][index]



        if (

            channel_type in neural_types

            and frequency is not None

        ):

            frequencies.append(

                float(

                    frequency

                )

            )



    if not frequencies:

        frequencies = [

            float(value)

            for value in metadata[

                "sample_frequencies"

            ]

            if value is not None

        ]



    if not frequencies:

        raise ValueError(

            "Could not determine SamplingFrequency from "

            f"{record['edf_path']}."

        )



    return Counter(

        frequencies

    ).most_common(

        1

    )[0][0]





def make_channels_rows(

    metadata: Dict[str, Any],

    record: Dict[str, Any],

) -> List[Dict[str, Any]]:

    rows = []



    for index, label in enumerate(

        metadata["channel_labels"]

    ):

        header = metadata[

            "signal_headers"

        ][index]



        rows.append({

            "name": label,

            "type": channel_type_for(

                label,

                record["datatype"],

                record["recording_modality"],

            ),

            "units": (

                header.get(

                    "dimension",

                    "n/a",

                )

                or "n/a"

            ),

            "sampling_frequency": (

                metadata[

                    "sample_frequencies"

                ][index]

                if metadata[

                    "sample_frequencies"

                ][index] is not None

                else "n/a"

            ),

            "status": "n/a",

            "status_description": "n/a",

        })



    return rows





def make_ieeg_electrode_rows(

    metadata: Dict[str, Any],

    record: Dict[str, Any],

) -> List[Dict[str, Any]]:

    rows = []



    for label in metadata[

        "channel_labels"

    ]:

        channel_type = channel_type_for(

            label,

            record["datatype"],

            record["recording_modality"],

        )



        if channel_type not in {

            "SEEG",

            "ECOG",

        }:

            continue



        rows.append({

            "name": label,

            "x": "n/a",

            "y": "n/a",

            "z": "n/a",

            "size": "n/a",

        })



    return rows





def load_metadata_validator() -> MetadataValidator:

    dictionary_path = active_metadata_dictionary()

    print(

        f"Using CoCANoT metadata dictionary: {dictionary_path.name}"

    )

    dictionary = load_dictionary(

        dictionary_path

    )

    return MetadataValidator(

        dictionary

    )





def validate_record(

    raw: Dict[str, Any],

    index: int,

    metadata_validator: MetadataValidator,

) -> Dict[str, Any]:

    path = Path(

        str(

            raw.get(

                "edf_path",

                "",

            )

        ).strip()

    ).expanduser().resolve()



    if (

        not path.is_file()

        or path.suffix.lower() != ".edf"

    ):

        raise ValueError(

            f"Record {index} has an invalid EDF path: {path}"

        )



    if raw.get(

        "metadata_confirmed"

    ) is not True:

        raise ValueError(

            f"Record {index} metadata was not confirmed."

        )



    metadata = raw.get(

        "cocanot_metadata"

    )



    if type(metadata) is not dict:

        raise ValueError(

            f"Record {index} is missing CoCANoT metadata."

        )



    validation = (

        metadata_validator.validate_record(

            "Electrophysiology",

            metadata,

        )

    )



    problems = [

        result

        for result in validation[

            "results"

        ]

        if result["status"] in {

            "invalid",

            "missing_required",

        }

    ]



    if problems:

        raise ValueError(

            f"Record {index} failed CoCANoT validation: "

            + "; ".join(

                result[

                    "message"

                ]

                for result in problems[:8]

            )

        )



    recording_modality = str(

        metadata.get(

            "Recording Modality"

        )

        or ""

    ).strip()



    datatype = (

        RECORDING_MODALITY_TO_DATATYPE.get(

            recording_modality

        )

    )



    if datatype is None:

        raise ValueError(

            f"Record {index} cannot map Recording Modality "

            f"{recording_modality!r} to a BIDS datatype."

        )



    if datatype == "meg":

        raise ValueError(

            "Raw BIDS MEG must remain in the native acquisition format. "

            "EDF files are not exported as raw BIDS MEG."

        )



    patient_id = str(

        metadata.get(

            "CoCANoT Patient ID"

        )

        or ""

    ).strip()



    record = {

        "edf_path": path,

        "site_id": str(

            raw.get(

                "site_id",

                "",

            )

        ).strip(),

        "project": clean_project(

            str(

                raw.get(

                    "project",

                    "",

                )

            )

        ),

        "project_description": str(

            raw.get(

                "project_description",

                "",

            )

        ).strip(),

        "participant": clean_label(

            patient_id,

            "participant_id",

        ),

        "session": clean_label(

            str(

                raw.get(

                    "session_id",

                    "",

                )

            ),

            "session_id",

        ),

        "recording_modality": recording_modality,

        "datatype": datatype,

        "cocanot_metadata": dict(

            metadata

        ),

        "derivatives_root": str(

            raw.get(

                "derivatives_root",

                "",

            )

            or ""

        ).strip(),

        "derivative_paths": [

            str(value).strip()

            for value in (

                raw.get(

                    "derivative_paths",

                    [],

                )

                or []

            )

            if str(value).strip()

        ],

    }



    if not record[

        "site_id"

    ]:

        raise ValueError(

            f"Record {index} is missing Site ID."

        )



    return record





def build_bids_base(

    record: Dict[str, Any],

    run_override: Optional[int] = None,

) -> str:

    parts = [

        f"sub-{record['participant']}",

        f"ses-{record['session']}",

        f"task-{TASK_NAME}",

    ]



    if run_override is not None:

        parts.append(

            f"run-{run_override:02d}"

        )



    parts.append(

        record["datatype"]

    )



    return "_".join(

        parts

    )





def choose_output_base(

    data_dir: Path,

    record: Dict[str, Any],

    overwrite: bool,

) -> str:

    base = build_bids_base(

        record

    )



    if (

        overwrite

        or not (

            data_dir

            / f"{base}.edf"

        ).exists()

    ):

        return base



    for run in range(

        2,

        10000,

    ):

        candidate = build_bids_base(

            record,

            run_override=run,

        )



        if not (

            data_dir

            / f"{candidate}.edf"

        ).exists():

            return candidate



    raise ValueError(

        f"Could not find an available run number for {base}"

    )





def make_recording_sidecar(

    metadata: Dict[str, Any],

    record: Dict[str, Any],

) -> Dict[str, Any]:

    sampling_frequency = (

        primary_sampling_frequency(

            metadata,

            record,

        )

    )



    sidecar: Dict[str, Any] = {

        "TaskName": TASK_NAME,

        "SamplingFrequency": sampling_frequency,

        "PowerLineFrequency": "n/a",

        "SoftwareFilters": "n/a",

        "RecordingDuration": float(

            metadata[

                "duration_seconds"

            ]

        ),

        "CoCANoTSiteID": record[

            "site_id"

        ],

        "CoCANoTMetadata": record[

            "cocanot_metadata"

        ],

    }



    if record[

        "datatype"

    ] == "eeg":

        sidecar[

            "EEGReference"

        ] = "n/a"

    else:

        sidecar[

            "iEEGReference"

        ] = "n/a"



    return sidecar





def copy_record(

    record: Dict[str, Any],

    output_root: Path,

    overwrite: bool,

) -> Dict[str, Any]:

    project_dir = (

        output_root

        / record["project"]

    )

    data_dir = (

        project_dir

        / f"sub-{record['participant']}"

        / f"ses-{record['session']}"

        / record["datatype"]

    )

    data_dir.mkdir(

        parents=True,

        exist_ok=True,

    )



    base = choose_output_base(

        data_dir,

        record,

        overwrite,

    )



    output_edf = (

        data_dir

        / f"{base}.edf"

    )

    output_json = (

        data_dir

        / f"{base}.json"

    )

    output_channels = (

        data_dir

        / f"{base}_channels.tsv"

    )

    output_metadata = (

        data_dir

        / f"{base}_cocanot.json"

    )



    if overwrite:

        output_edf.unlink(

            missing_ok=True

        )

        output_json.unlink(

            missing_ok=True

        )

        output_channels.unlink(

            missing_ok=True

        )

        output_metadata.unlink(

            missing_ok=True

        )



    metadata = read_edf_metadata(

        record["edf_path"]

    )



    shutil.copy2(

        record["edf_path"],

        output_edf,

    )



    write_json(

        output_json,

        make_recording_sidecar(

            metadata,

            record,

        ),

    )



    write_json(

        output_metadata,

        {

            "CoCANoTMetadata": record[

                "cocanot_metadata"

            ],

            "ScrubbedHeader": {

                "file_header": metadata.get(

                    "file_header",

                    {},

                ),

                "signal_headers": metadata.get(

                    "signal_headers",

                    [],

                ),

            },

        },

    )



    write_tsv(

        output_channels,

        make_channels_rows(

            metadata,

            record,

        ),

        [

            "name",

            "type",

            "units",

            "sampling_frequency",

            "status",

            "status_description",

        ],

    )



    shared_outputs: list[Path] = []



    if record[

        "datatype"

    ] == "ieeg":

        electrode_path = (

            data_dir

            / (

                f"sub-{record['participant']}"

                f"_ses-{record['session']}"

                "_electrodes.tsv"

            )

        )

        coordsystem_path = (

            data_dir

            / (

                f"sub-{record['participant']}"

                f"_ses-{record['session']}"

                "_coordsystem.json"

            )

        )



        write_tsv(

            electrode_path,

            make_ieeg_electrode_rows(

                metadata,

                record,

            ),

            [

                "name",

                "x",

                "y",

                "z",

                "size",

            ],

        )



        write_json(

            coordsystem_path,

            {

                "iEEGCoordinateSystem": "Other",

                "iEEGCoordinateUnits": "n/a",

                "iEEGCoordinateSystemDescription": (

                    "Electrode coordinates were not available in the "

                    "source EDF. Electrode names are retained and "

                    "coordinate values are reported as n/a."

                ),

            },

        )



        shared_outputs.extend(

            [

                electrode_path,

                coordsystem_path,

            ]

        )



    return {

        "output": output_edf,

        "sidecar": output_json,

        "channels": output_channels,

        "metadata": output_metadata,

        "shared_outputs": shared_outputs,

    }





def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(

        description=(

            "Convert approved EDF recordings into BIDS EEG/iEEG layouts."

        )

    )

    parser.add_argument(

        "--manifest",

        type=Path,

        required=True,

    )

    parser.add_argument(

        "--output-dir",

        type=Path,

        required=True,

    )

    parser.add_argument(

        "--overwrite",

        action="store_true",

    )

    return parser.parse_args()





def main() -> None:

    args = parse_args()



    manifest = load_json(

        args.manifest.expanduser().resolve()

    )

    output_root = (

        args.output_dir

        .expanduser()

        .resolve()

    )



    raw_records = manifest.get(

        "records"

    )



    if (

        type(raw_records) is not list

        or not raw_records

    ):

        raise SystemExit(

            "Manifest contains no selected electrophysiology records."

        )



    metadata_validator = (

        load_metadata_validator()

    )

    data_links = PatientDataLinkStore()



    records = [

        validate_record(

            raw,

            index,

            metadata_validator,

        )

        for index, raw in enumerate(

            raw_records,

            start=1,

        )

    ]



    project_descriptions: Dict[

        str,

        str,

    ] = {}



    for record in records:

        project = record[

            "project"

        ]

        description = record[

            "project_description"

        ]

        current = (

            project_descriptions.get(

                project

            )

        )



        if (

            current

            and description

            and current != description

        ):

            raise SystemExit(

                f"Project {project!r} has more than one Project Description."

            )



        if description:

            project_descriptions[

                project

            ] = description

        elif current is None:

            project_descriptions[

                project

            ] = ""



    output_root.mkdir(

        parents=True,

        exist_ok=True,

    )



    for index, record in enumerate(

        records,

        start=1,

    ):

        project_dir = (

            output_root

            / record["project"]

        )



        dataset_description = {

            "Name": record[

                "project"

            ],

            "BIDSVersion": str(

                manifest.get(

                    "bids_version"

                )

                or SUPPORTED_BIDS_VERSION

            ),

            "DatasetType": "raw",

        }



        description = (

            project_descriptions.get(

                record[

                    "project"

                ],

                "",

            )

        )



        if description:

            dataset_description[

                "Description"

            ] = description



        write_json(

            project_dir

            / "dataset_description.json",

            dataset_description,

        )



        print(

            f"[{index}/{len(records)}] "

            f"{record['edf_path']} -> "

            f"{record['project']} / "

            f"{record['datatype']}"

        )



        result = copy_record(

            record,

            output_root,

            args.overwrite,

        )



        output_edf = Path(

            result["output"]

        )

        base = output_edf.stem

        data_dir = output_edf.parent

        output_json = Path(

            result["sidecar"]

        )

        output_channels = Path(

            result["channels"]

        )

        output_metadata = Path(

            result["metadata"]

        )

        metadata = record[

            "cocanot_metadata"

        ]



        link = {

            "project": record[

                "project"

            ],

            "project_description": record[

                "project_description"

            ],

            "session_id": record[

                "session"

            ],

            "bids_data_path": str(

                output_edf.resolve()

            ),

            "bids_sidecar_path": str(

                output_json.resolve()

            ),

            "bids_channels_path": str(

                output_channels.resolve()

            ),

            "cocanot_metadata_path": str(

                output_metadata.resolve()

            ),

            "derivatives_root": record.get(

                "derivatives_root",

                "",

            ),

            "derivative_paths": record.get(

                "derivative_paths",

                [],

            ),

            "final_output_root": str(

                output_root.resolve()

            ),

            "final_paths": [

                str(output_edf.resolve()),

                str(output_json.resolve()),

                str(output_channels.resolve()),

                str(output_metadata.resolve()),

                *[

                    str(Path(path).resolve())

                    for path in result.get(

                        "shared_outputs",

                        [],

                    )

                ],

            ],

        }



        if record[

            "datatype"

        ] == "ieeg":

            link[

                "bids_electrodes_path"

            ] = str(

                (

                    data_dir

                    / (

                        f"sub-{record['participant']}"

                        f"_ses-{record['session']}"

                        "_electrodes.tsv"

                    )

                ).resolve()

            )

            link[

                "bids_coordsystem_path"

            ] = str(

                (

                    data_dir

                    / (

                        f"sub-{record['participant']}"

                        f"_ses-{record['session']}"

                        "_coordsystem.json"

                    )

                ).resolve()

            )



        data_links.save_link(

            record[

                "site_id"

            ],

            metadata[

                "CoCANoT Patient ID"

            ],

            "Electrophysiology",

            metadata[

                "Recording ID"

            ],

            link,

        )



        print(

            f"    -> {result['output']}"

        )



    print(

        "\nBIDS electrophysiology conversion complete."

    )

    print(

        f"Converted files: {len(records)}"

    )

    print(

        f"Output folder: {output_root}"

    )





if __name__ == "__main__":

    main()
