#!/usr/bin/env python3

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping


PIPELINE_SECTIONS = {
    "electrophysiology",
    "imaging",
}


DEFAULT_SETTINGS: dict[str, Any] = {
    "electrophysiology": {
        "input_dirs": [],
        "derivatives_dir": "",
        "bids_output_dir": "",
    },
    "imaging": {
        "input_dirs": [],
        "derivatives_dir": "",
        "bids_output_dir": "",
    },
}


class PipelineConfigError(RuntimeError):
    """Raised when pipeline settings cannot be loaded or validated."""


@dataclass(frozen=True)
class ElectrophysiologyPaths:
    """Resolved paths used by the electrophysiology pipeline."""

    input_dirs: tuple[Path, ...]
    derivatives_dir: Path
    scrubbed_dir: Path
    reports_dir: Path
    logs_dir: Path
    bids_output_dir: Path

    @property
    def input_dir(self) -> Path:
        """
        Return the first configured electrophysiology input directory.

        New code should use input_dirs when multiple folders are supported.
        """
        if not self.input_dirs:
            raise PipelineConfigError(
                "No electrophysiology input directories are configured."
            )

        return self.input_dirs[0]


@dataclass(frozen=True)
class ImagingPaths:
    """Resolved paths used by the imaging pipeline."""

    input_dirs: tuple[Path, ...]
    derivatives_dir: Path
    converted_nifti_dir: Path
    scrubbed_header_dir: Path
    defaced_dir: Path
    scrubbed_defaced_dir: Path
    external_defaced_dir: Path
    pipeline_state_path: Path
    reports_dir: Path
    logs_dir: Path
    pydeface_logs_dir: Path
    bids_output_dir: Path

    @property
    def input_dir(self) -> Path:
        """
        Return the first configured imaging input directory.

        New code should use input_dirs when multiple folders are supported.
        """
        if not self.input_dirs:
            raise PipelineConfigError(
                "No imaging input directories are configured."
            )

        return self.input_dirs[0]


@dataclass(frozen=True)
class PipelineConfig:
    """
    Resolved electrophysiology configuration.

    This name is retained for compatibility with the existing EEG dashboard.
    """

    project_root: Path
    settings_path: Path
    electrophysiology: ElectrophysiologyPaths


@dataclass(frozen=True)
class ImagingPipelineConfig:
    """Resolved imaging configuration."""

    project_root: Path
    settings_path: Path
    imaging: ImagingPaths


def get_project_root() -> Path:
    """
    Return the shared project root.

    Expected structure:

        MockPipelines/
        ├── pipeline_config.py
        ├── pipeline_settings.json
        ├── EEGPipeline/
        └── ImagingPipeline-PyDeface/
    """
    return Path(__file__).resolve().parent


def get_settings_path() -> Path:
    """Return the shared pipeline settings path."""
    return get_project_root() / "pipeline_settings.json"


def merge_settings(
    defaults: Mapping[str, Any],
    loaded: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge loaded settings into the default structure."""
    merged = deepcopy(dict(defaults))

    for section_name, section_value in loaded.items():
        if (
            section_name in merged
            and isinstance(merged[section_name], dict)
            and isinstance(section_value, dict)
        ):
            merged[section_name].update(section_value)
        else:
            merged[section_name] = deepcopy(section_value)

    return merged


def normalize_input_directory_values(
    values: Iterable[str | Path] | str | Path | None,
) -> list[str]:
    """
    Normalize input directory values for saving.

    Empty values and duplicates are removed while order is preserved.
    """
    if values is None:
        return []

    if isinstance(values, (str, Path)):
        raw_values: Iterable[str | Path] = [values]
    else:
        raw_values = values

    normalized: list[str] = []
    seen: set[str] = set()

    for value in raw_values:
        text = str(value).strip()

        if not text:
            continue

        path_text = str(Path(text).expanduser())

        if path_text in seen:
            continue

        seen.add(path_text)
        normalized.append(path_text)

    return normalized


def normalize_legacy_settings(
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Convert legacy input_dir keys into input_dirs.

    The old input_dir key is removed from every supported pipeline section.
    """
    normalized = deepcopy(dict(settings))

    for section_name in PIPELINE_SECTIONS:
        section = normalized.get(section_name)

        if not isinstance(section, dict):
            continue

        input_dirs = section.get("input_dirs")
        legacy_input_dir = section.get("input_dir")

        if not input_dirs and legacy_input_dir:
            section["input_dirs"] = [legacy_input_dir]

        section.pop("input_dir", None)

    return normalized


def load_settings_dict(
    settings_path: Path | None = None,
) -> dict[str, Any]:
    """
    Load the complete settings dictionary.

    Missing settings files return a copy of DEFAULT_SETTINGS.
    """
    path = Path(
        settings_path or get_settings_path()
    ).expanduser()

    if not path.exists():
        return deepcopy(DEFAULT_SETTINGS)

    try:
        with path.open("r", encoding="utf-8") as file:
            loaded = json.load(file)

    except json.JSONDecodeError as exc:
        raise PipelineConfigError(
            "The settings file contains invalid JSON:\n"
            f"{path}\n\n"
            f"{exc}"
        ) from exc

    except OSError as exc:
        raise PipelineConfigError(
            "Could not read the settings file:\n"
            f"{path}\n\n"
            f"{exc}"
        ) from exc

    if not isinstance(loaded, dict):
        raise PipelineConfigError(
            "The settings file must contain a JSON object:\n"
            f"{path}"
        )

    merged = merge_settings(
        DEFAULT_SETTINGS,
        loaded,
    )

    return normalize_legacy_settings(merged)


def save_settings_dict(
    settings: Mapping[str, Any],
    settings_path: Path | None = None,
) -> Path:
    """
    Save the complete settings dictionary atomically.

    Atomic replacement helps prevent a partially written JSON file from
    replacing a valid settings file.
    """
    path = Path(
        settings_path or get_settings_path()
    ).expanduser()

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    normalized = normalize_legacy_settings(settings)
    merged = merge_settings(
        DEFAULT_SETTINGS,
        normalized,
    )

    temporary_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=".pipeline_settings_",
        suffix=".json.tmp",
        dir=path.parent,
        delete=False,
    )

    temporary_path = Path(temporary_file.name)

    try:
        with temporary_file:
            json.dump(
                merged,
                temporary_file,
                indent=2,
                sort_keys=False,
            )
            temporary_file.write("\n")

        os.replace(
            temporary_path,
            path,
        )

    except Exception as exc:
        temporary_path.unlink(
            missing_ok=True,
        )

        raise PipelineConfigError(
            "Could not save the settings file:\n"
            f"{path}\n\n"
            f"{exc}"
        ) from exc

    return path


def get_settings_section(
    settings: Mapping[str, Any],
    section_name: str,
) -> dict[str, Any]:
    """Return and validate one pipeline settings section."""
    section = settings.get(section_name)

    if not isinstance(section, dict):
        raise PipelineConfigError(
            f"The settings section {section_name!r} must be a JSON object."
        )

    return dict(section)


def build_pipeline_section(
    input_dirs: Iterable[str | Path] | str | Path | None,
    derivatives_dir: str | Path,
    bids_output_dir: str | Path,
) -> dict[str, Any]:
    """Build one normalized pipeline settings section."""
    return {
        "input_dirs": normalize_input_directory_values(input_dirs),
        "derivatives_dir": normalize_path_for_saving(derivatives_dir),
        "bids_output_dir": normalize_path_for_saving(bids_output_dir),
    }


def normalize_path_for_saving(
    value: str | Path | None,
) -> str:
    """Normalize one path for storage while preserving empty values."""
    if value is None:
        return ""

    text = str(value).strip()

    if not text:
        return ""

    return str(Path(text).expanduser())


def update_settings_section(
    section_name: str,
    section: Mapping[str, Any],
    settings_path: Path | None = None,
) -> dict[str, Any]:
    """
    Update one pipeline section while preserving all other sections.

    The updated complete dictionary is returned but not automatically saved.
    """
    if section_name not in PIPELINE_SECTIONS:
        raise PipelineConfigError(
            f"Unsupported pipeline section: {section_name}"
        )

    settings = load_settings_dict(settings_path)
    settings[section_name] = dict(section)

    return normalize_legacy_settings(settings)


def build_settings_dict(
    input_dirs: Iterable[str | Path] | str | Path | None = None,
    derivatives_dir: str | Path = "",
    bids_output_dir: str | Path = "",
    *,
    input_dir: str | Path | None = None,
    settings_path: Path | None = None,
) -> dict[str, Any]:
    """
    Update the electrophysiology section while preserving imaging settings.

    input_dir is retained only for compatibility with older dashboard code.
    New code should use input_dirs.
    """
    selected_inputs = input_dirs

    if selected_inputs is None and input_dir is not None:
        selected_inputs = [input_dir]

    section = build_pipeline_section(
        input_dirs=selected_inputs,
        derivatives_dir=derivatives_dir,
        bids_output_dir=bids_output_dir,
    )

    return update_settings_section(
        section_name="electrophysiology",
        section=section,
        settings_path=settings_path,
    )


def build_imaging_settings_dict(
    input_dirs: Iterable[str | Path] | str | Path | None = None,
    derivatives_dir: str | Path = "",
    bids_output_dir: str | Path = "",
    *,
    input_dir: str | Path | None = None,
    settings_path: Path | None = None,
) -> dict[str, Any]:
    """
    Update the imaging section while preserving electrophysiology settings.

    input_dir is accepted for compatibility, but input_dirs is preferred.
    """
    selected_inputs = input_dirs

    if selected_inputs is None and input_dir is not None:
        selected_inputs = [input_dir]

    section = build_pipeline_section(
        input_dirs=selected_inputs,
        derivatives_dir=derivatives_dir,
        bids_output_dir=bids_output_dir,
    )

    return update_settings_section(
        section_name="imaging",
        section=section,
        settings_path=settings_path,
    )


def resolve_config_path(
    value: Any,
    project_root: Path,
    setting_name: str,
) -> Path:
    """
    Resolve one required configured path.

    Relative paths are interpreted relative to the shared project root.
    """
    if value is None:
        raise PipelineConfigError(
            f"Missing required setting: {setting_name}"
        )

    text = str(value).strip()

    if not text:
        raise PipelineConfigError(
            f"Missing required setting: {setting_name}"
        )

    path = Path(text).expanduser()

    if not path.is_absolute():
        path = project_root / path

    return path.resolve()


def resolve_config_paths(
    values: Any,
    project_root: Path,
    setting_name: str,
) -> tuple[Path, ...]:
    """
    Resolve a required list of configured paths.

    Duplicate paths are removed while order is preserved.
    """
    if values is None:
        raise PipelineConfigError(
            f"Missing required setting: {setting_name}"
        )

    if not isinstance(values, (list, tuple)):
        raise PipelineConfigError(
            f"The setting {setting_name} must be a JSON array."
        )

    if not values:
        raise PipelineConfigError(
            f"Add at least one folder to {setting_name}."
        )

    resolved_paths: list[Path] = []
    seen: set[Path] = set()

    for index, value in enumerate(values):
        resolved = resolve_config_path(
            value=value,
            project_root=project_root,
            setting_name=f"{setting_name}[{index}]",
        )

        if resolved in seen:
            continue

        seen.add(resolved)
        resolved_paths.append(resolved)

    if not resolved_paths:
        raise PipelineConfigError(
            f"Add at least one valid folder to {setting_name}."
        )

    return tuple(resolved_paths)


def load_pipeline_config(
    settings_path: Path | None = None,
) -> PipelineConfig:
    """
    Load the electrophysiology configuration.

    This function does not require imaging settings to be complete.
    """
    path = Path(
        settings_path or get_settings_path()
    ).expanduser().resolve()

    project_root = path.parent
    settings = load_settings_dict(path)

    section = get_settings_section(
        settings,
        "electrophysiology",
    )

    input_dirs = resolve_config_paths(
        values=section.get("input_dirs"),
        project_root=project_root,
        setting_name="electrophysiology.input_dirs",
    )

    derivatives_dir = resolve_config_path(
        value=section.get("derivatives_dir"),
        project_root=project_root,
        setting_name="electrophysiology.derivatives_dir",
    )

    bids_output_dir = resolve_config_path(
        value=section.get("bids_output_dir"),
        project_root=project_root,
        setting_name="electrophysiology.bids_output_dir",
    )

    return PipelineConfig(
        project_root=project_root,
        settings_path=path,
        electrophysiology=ElectrophysiologyPaths(
            input_dirs=input_dirs,
            derivatives_dir=derivatives_dir,
            scrubbed_dir=derivatives_dir / "scrubbed",
            reports_dir=derivatives_dir / "reports",
            logs_dir=derivatives_dir / "logs",
            bids_output_dir=bids_output_dir,
        ),
    )


def load_imaging_config(
    settings_path: Path | None = None,
) -> ImagingPipelineConfig:
    """
    Load the imaging configuration.

    This function does not require electrophysiology settings to be complete.
    """
    path = Path(
        settings_path or get_settings_path()
    ).expanduser().resolve()

    project_root = path.parent
    settings = load_settings_dict(path)

    section = get_settings_section(
        settings,
        "imaging",
    )

    input_dirs = resolve_config_paths(
        values=section.get("input_dirs"),
        project_root=project_root,
        setting_name="imaging.input_dirs",
    )

    derivatives_dir = resolve_config_path(
        value=section.get("derivatives_dir"),
        project_root=project_root,
        setting_name="imaging.derivatives_dir",
    )

    bids_output_dir = resolve_config_path(
        value=section.get("bids_output_dir"),
        project_root=project_root,
        setting_name="imaging.bids_output_dir",
    )

    return ImagingPipelineConfig(
        project_root=project_root,
        settings_path=path,
        imaging=ImagingPaths(
            input_dirs=input_dirs,
            derivatives_dir=derivatives_dir,
            converted_nifti_dir=(
                derivatives_dir / "converted_nifti"
            ),
            scrubbed_header_dir=(
                derivatives_dir / "scrubbed_header"
            ),
            defaced_dir=(
                derivatives_dir / "scrubbed_defaced"
            ),
            scrubbed_defaced_dir=(
                derivatives_dir / "scrubbed_defaced"
            ),
            external_defaced_dir=(
                derivatives_dir / "external_defaced"
            ),
            pipeline_state_path=(
                derivatives_dir / "imaging_pipeline_state.json"
            ),
            reports_dir=(
                derivatives_dir / "logs" / "reports"
            ),
            logs_dir=(
                derivatives_dir / "logs"
            ),
            pydeface_logs_dir=(
                derivatives_dir
                / "logs"
                / "pydeface"
            ),
            bids_output_dir=bids_output_dir,
        ),
    )


def ensure_distinct_paths(
    input_dirs: Iterable[Path],
    derivatives_dir: Path,
    bids_output_dir: Path,
    pipeline_label: str,
) -> None:
    """Ensure input and output directories do not resolve to the same path."""
    resolved_derivatives = derivatives_dir.resolve()
    resolved_bids = bids_output_dir.resolve()

    if resolved_derivatives == resolved_bids:
        raise PipelineConfigError(
            f"The {pipeline_label} derivatives folder and BIDS output "
            "folder must be different."
        )

    for input_dir in input_dirs:
        resolved_input = input_dir.resolve()

        if resolved_input == resolved_derivatives:
            raise PipelineConfigError(
                f"A {pipeline_label} input folder and the derivatives "
                "folder must be different:\n"
                f"{resolved_input}"
            )

        if resolved_input == resolved_bids:
            raise PipelineConfigError(
                f"A {pipeline_label} input folder and the BIDS output "
                "folder must be different:\n"
                f"{resolved_input}"
            )


def validate_input_directories(
    input_dirs: Iterable[Path],
    description: str,
) -> None:
    """Validate that every configured input directory exists."""
    paths = tuple(input_dirs)

    if not paths:
        raise PipelineConfigError(
            f"Add at least one {description} input folder."
        )

    for input_dir in paths:
        if not input_dir.exists():
            raise PipelineConfigError(
                f"The {description} input folder does not exist:\n"
                f"{input_dir}"
            )

        if not input_dir.is_dir():
            raise PipelineConfigError(
                f"The {description} input path is not a directory:\n"
                f"{input_dir}"
            )


def create_output_directories(
    config: PipelineConfig,
) -> None:
    """Create electrophysiology output directories."""
    paths = config.electrophysiology

    for path in (
        paths.derivatives_dir,
        paths.scrubbed_dir,
        paths.reports_dir,
        paths.logs_dir,
        paths.bids_output_dir,
    ):
        path.mkdir(
            parents=True,
            exist_ok=True,
        )


def create_imaging_output_directories(
    config: ImagingPipelineConfig,
) -> None:
    """Create imaging output directories."""
    paths = config.imaging

    for path in (
        paths.derivatives_dir,
        paths.converted_nifti_dir,
        paths.scrubbed_header_dir,
        paths.scrubbed_defaced_dir,
        paths.external_defaced_dir,
        paths.logs_dir,
        paths.pydeface_logs_dir,
        paths.bids_output_dir,
    ):
        path.mkdir(
            parents=True,
            exist_ok=True,
        )


def validate_pipeline_config(
    config: PipelineConfig,
    create_outputs: bool = True,
) -> None:
    """Validate the electrophysiology configuration."""
    paths = config.electrophysiology

    validate_input_directories(
        input_dirs=paths.input_dirs,
        description="raw EDF",
    )

    ensure_distinct_paths(
        input_dirs=paths.input_dirs,
        derivatives_dir=paths.derivatives_dir,
        bids_output_dir=paths.bids_output_dir,
        pipeline_label="electrophysiology",
    )

    if create_outputs:
        create_output_directories(config)


def validate_imaging_config(
    config: ImagingPipelineConfig,
    create_outputs: bool = True,
) -> None:
    """Validate the imaging configuration."""
    paths = config.imaging

    validate_input_directories(
        input_dirs=paths.input_dirs,
        description="imaging",
    )

    ensure_distinct_paths(
        input_dirs=paths.input_dirs,
        derivatives_dir=paths.derivatives_dir,
        bids_output_dir=paths.bids_output_dir,
        pipeline_label="imaging",
    )

    if create_outputs:
        create_imaging_output_directories(config)