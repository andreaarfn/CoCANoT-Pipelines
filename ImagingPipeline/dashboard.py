#!/usr/bin/env python3

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable, Dict, List, Optional

import nibabel as nib
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


IMAGING_PIPELINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = IMAGING_PIPELINE_DIR.parent
SCRIPTS_DIR = IMAGING_PIPELINE_DIR / "scripts"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from MetadataPipeline.forms.clinical_assessment import (
    import_clinical_file,
    reconcile_clinical_assessment,
    review_clinical_batch,
)
from MetadataPipeline.storage import LocalMetadataStore
from MetadataPipeline.validation import MetadataValidator, load_dictionary
from MetadataPipeline.validation.conditions import condition_matches

from ImagingPipeline.views import ImagingHome

from pipeline_config import (
    ImagingPipelineConfig,
    PipelineConfigError,
    build_imaging_settings_dict,
    get_settings_path,
    load_imaging_config,
    load_settings_dict,
    save_settings_dict,
)

DICOM_CONVERTER_SCRIPT = SCRIPTS_DIR / "dicom_to_nifti.py"
HEADER_SCRUBBER_SCRIPT = SCRIPTS_DIR / "scrub_nifti_header.py"
DEFACER_SCRIPT = SCRIPTS_DIR / "deface_nifti_with_pydeface.py"
BIDS_CONVERTER_SCRIPT = SCRIPTS_DIR / "nifti_to_bids.py"
METADATA_DICTIONARY = (
    PROJECT_ROOT
    / "MetadataPipeline"
    / "dictionaries"
    / "CoCANoT_Metadata_Phase1.xlsx"
)

REVIEW_STATE_FILENAME = "imaging_review_state.json"
EDITABLE_HEADER_FIELDS = {"descrip", "aux_file", "intent_name"}

BIDS_MODALITY_DATATYPES = {
    "MRI": ("anat", "func", "dwi", "fmap", "perf"),
    "PET": ("pet",),
    "meeg": ("eeg", "meg", "ieeg"),
    "behavioral": ("beh",),
    "microscopy": ("micr",),
    "NIRS": ("nirs",),
    "motion": ("motion",),
    "MRS": ("mrs",),
}

BIDS_DATATYPE_SUFFIXES = {
    "anat": ("T1w", "T2w", "FLAIR", "PDw", "T2starw", "CT", "MEGRE", "MESE", "VFA", "IRT1", "MP2RAGE", "MPM", "MTS", "MTR"),
    "func": ("bold", "cbv", "sbref", "phase"),
    "dwi": ("dwi", "sbref"),
    "fmap": ("epi", "m0scan", "TB1DAM", "TB1EPI", "RB1COR", "TB1AFI", "TB1RFM", "TB1TFL", "TB1SRGE", "RB1map", "TB1map"),
    "perf": ("asl", "m0scan", "noRF"),
    "pet": ("pet",),
    "eeg": ("eeg",),
    "meg": ("meg",),
    "ieeg": ("ieeg",),
    "beh": ("beh",),
    "micr": ("micr",),
    "nirs": ("nirs",),
    "motion": ("motion",),
    "mrs": ("mrsi", "mrsref", "svs", "unloc"),
}

BIDS_REQUIRED_TASK_DATATYPES = {"func", "eeg", "meg", "ieeg", "beh", "nirs", "motion"}
BIDS_REQUIRED_FIELDS = {
    "micr": ("sample",),
    "motion": ("tracksys",),
}

MRI_SEQUENCE_FIELDS = (
    "MRI Sequence(s) (if applicable)",
    "MRI Sequence(s) - if MRI (multiselect)",
)


BIDS_FIELD_LABELS = {
    "task": "Task", "acq": "Acquisition", "ce": "Contrast agent", "trc": "Tracer",
    "stain": "Stain", "rec": "Reconstruction", "dir": "Direction", "run": "Run",
    "echo": "Echo", "flip": "Flip", "inv": "Inversion", "mt": "MT", "part": "Part",
    "chunk": "Chunk", "mod": "Modality label", "recording": "Recording", "proc": "Processing",
    "space": "Space", "split": "Split", "sample": "Sample", "tracksys": "Tracking system",
    "nuc": "Nucleus", "voi": "Volume of interest",
}



DATATYPE_MODALITY = {
    datatype: modality
    for modality, datatypes in BIDS_MODALITY_DATATYPES.items()
    for datatype in datatypes
}


def strip_nifti_suffix(path: Path) -> str:
    if path.name.endswith(".nii.gz"):
        return path.name[:-7]
    if path.name.endswith(".nii"):
        return path.name[:-4]
    return path.stem


def is_nifti(path: Path) -> bool:
    return path.is_file() and path.name.endswith((".nii", ".nii.gz"))


def matching_json_path(path: Path) -> Optional[Path]:
    candidate = path.with_name(f"{strip_nifti_suffix(path)}.json")
    return candidate if candidate.exists() else None


def matching_extra_sidecars(path: Path) -> list[Path]:
    base = strip_nifti_suffix(path)
    extras: list[Path] = []
    for extension in (".bval", ".bvec"):
        candidate = path.with_name(f"{base}{extension}")
        if candidate.exists():
            extras.append(candidate)
    return extras


class ExtendedSelectionController:
    """Add consistent keyboard range selection to Listbox and Treeview widgets."""

    def __init__(self, widget: tk.Widget) -> None:
        self.widget = widget
        self.anchor: object | None = None
        self._bind_events()

    def _bind_events(self) -> None:
        self.widget.configure(takefocus=True)
        self.widget.bind("<Button-1>", self._remember_pointer_anchor, add="+")
        self.widget.bind("<KeyPress-Up>", self._move_up)
        self.widget.bind("<KeyPress-Down>", self._move_down)
        self.widget.bind("<Shift-KeyPress-Up>", self._extend_up)
        self.widget.bind("<Shift-KeyPress-Down>", self._extend_down)
        self.widget.bind("<Control-a>", self._select_all)
        self.widget.bind("<Control-A>", self._select_all)
        self.widget.bind("<Command-a>", self._select_all)
        self.widget.bind("<Command-A>", self._select_all)
        self.widget.bind("<Home>", self._move_home)
        self.widget.bind("<End>", self._move_end)
        self.widget.bind("<Shift-Home>", self._extend_home)
        self.widget.bind("<Shift-End>", self._extend_end)

    def focus(self) -> None:
        self.widget.focus_set()

    def _items(self) -> list[object]:
        if isinstance(self.widget, tk.Listbox):
            return list(range(self.widget.size()))
        if isinstance(self.widget, ttk.Treeview):
            return list(self.widget.get_children(""))
        return []

    def _selected(self) -> list[object]:
        if isinstance(self.widget, tk.Listbox):
            return list(self.widget.curselection())
        if isinstance(self.widget, ttk.Treeview):
            return list(self.widget.selection())
        return []

    def _focused_item(self) -> object | None:
        items = self._items()
        if not items:
            return None
        if isinstance(self.widget, tk.Listbox):
            active = int(self.widget.index("active"))
            return active if 0 <= active < len(items) else items[0]
        focused = self.widget.focus() if isinstance(self.widget, ttk.Treeview) else ""
        if focused in items:
            return focused
        selected = self._selected()
        return selected[-1] if selected else items[0]

    def _remember_pointer_anchor(self, event: tk.Event) -> None:
        if isinstance(self.widget, tk.Listbox):
            self.anchor = int(self.widget.nearest(event.y))
        elif isinstance(self.widget, ttk.Treeview):
            item = self.widget.identify_row(event.y)
            if item:
                self.anchor = item
        self.widget.focus_set()

    def _set_single(self, item: object) -> None:
        if isinstance(self.widget, tk.Listbox):
            index = int(item)
            self.widget.selection_clear(0, "end")
            self.widget.selection_set(index)
            self.widget.activate(index)
            self.widget.see(index)
        elif isinstance(self.widget, ttk.Treeview):
            item_id = str(item)
            self.widget.selection_set(item_id)
            self.widget.focus(item_id)
            self.widget.see(item_id)
        self.anchor = item

    def _set_range(self, endpoint: object) -> None:
        items = self._items()
        if not items:
            return
        if self.anchor not in items:
            self.anchor = self._focused_item() or endpoint
        start = items.index(self.anchor)
        end = items.index(endpoint)
        selected = items[min(start, end): max(start, end) + 1]

        if isinstance(self.widget, tk.Listbox):
            self.widget.selection_clear(0, "end")
            for item in selected:
                self.widget.selection_set(int(item))
            self.widget.activate(int(endpoint))
            self.widget.see(int(endpoint))
        elif isinstance(self.widget, ttk.Treeview):
            self.widget.selection_set(tuple(str(item) for item in selected))
            self.widget.focus(str(endpoint))
            self.widget.see(str(endpoint))

    def _relative_item(self, offset: int) -> object | None:
        items = self._items()
        current = self._focused_item()
        if not items or current not in items:
            return None
        index = max(0, min(len(items) - 1, items.index(current) + offset))
        return items[index]

    def _move_up(self, _event: tk.Event) -> str:
        target = self._relative_item(-1)
        if target is not None:
            self._set_single(target)
        return "break"

    def _move_down(self, _event: tk.Event) -> str:
        target = self._relative_item(1)
        if target is not None:
            self._set_single(target)
        return "break"

    def _extend_up(self, _event: tk.Event) -> str:
        target = self._relative_item(-1)
        if target is not None:
            if self.anchor is None:
                self.anchor = self._focused_item()
            self._set_range(target)
        return "break"

    def _extend_down(self, _event: tk.Event) -> str:
        target = self._relative_item(1)
        if target is not None:
            if self.anchor is None:
                self.anchor = self._focused_item()
            self._set_range(target)
        return "break"

    def _move_home(self, _event: tk.Event) -> str:
        items = self._items()
        if items:
            self._set_single(items[0])
        return "break"

    def _move_end(self, _event: tk.Event) -> str:
        items = self._items()
        if items:
            self._set_single(items[-1])
        return "break"

    def _extend_home(self, _event: tk.Event) -> str:
        items = self._items()
        if items:
            if self.anchor is None:
                self.anchor = self._focused_item()
            self._set_range(items[0])
        return "break"

    def _extend_end(self, _event: tk.Event) -> str:
        items = self._items()
        if items:
            if self.anchor is None:
                self.anchor = self._focused_item()
            self._set_range(items[-1])
        return "break"

    def _select_all(self, _event: tk.Event) -> str:
        items = self._items()
        if isinstance(self.widget, tk.Listbox):
            if items:
                self.widget.selection_set(0, "end")
        elif isinstance(self.widget, ttk.Treeview):
            self.widget.selection_set(tuple(str(item) for item in items))
        return "break"


class MultiFolderSelectionDialog(tk.Toplevel):
    """Navigate folders and select multiple sibling directories."""

    def __init__(self, parent: tk.Widget, title: str, initial_dir: Path) -> None:
        super().__init__(parent)
        self.result: List[str] = []
        self.current_dir = self._existing_directory(initial_dir)
        self.path_var = tk.StringVar(value=str(self.current_dir))

        self.title(title)
        self.geometry("820x560")
        self.minsize(620, 420)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self._build_interface()
        self._load_directory()
        self.grab_set()
        self.after_idle(self.folder_list.focus_set)

    @staticmethod
    def _existing_directory(path: Path) -> Path:
        candidate = path.expanduser()
        if candidate.is_dir():
            return candidate.resolve()
        if candidate.parent.is_dir():
            return candidate.parent.resolve()
        return Path.home().resolve()

    def _build_interface(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(2, weight=1)

        ttk.Label(
            root,
            text=(
                "Select one or more folders. Use Shift + Up/Down or Shift-click "
                "for a range, and Ctrl/Cmd-click for individual folders."
            ),
            wraplength=760,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Button(root, text="Up", command=self.go_up).grid(row=1, column=0, sticky="w")
        path_entry = ttk.Entry(root, textvariable=self.path_var)
        path_entry.grid(row=1, column=1, sticky="ew", padx=8)
        path_entry.bind("<Return>", self.go_to_typed_path)
        ttk.Button(root, text="Go", command=self.go_to_typed_path).grid(row=1, column=2)

        frame = ttk.Frame(root)
        frame.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.folder_list = tk.Listbox(frame, selectmode="extended", exportselection=False)
        self.folder_list.grid(row=0, column=0, sticky="nsew")
        self.folder_list.bind("<Double-1>", self.open_active_folder)
        self.folder_list.bind("<Return>", self.open_active_folder)
        self.selection = ExtendedSelectionController(self.folder_list)

        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.folder_list.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.folder_list.configure(yscrollcommand=scroll.set)

        actions = ttk.Frame(root)
        actions.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Add Current Folder", command=self.accept_current).pack(side="left")
        ttk.Button(actions, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(
            actions,
            text="Add Selected Folders",
            command=self.accept_selected,
        ).pack(side="right", padx=(0, 8))

    def _child_directories(self) -> List[Path]:
        try:
            return sorted(
                (path for path in self.current_dir.iterdir() if path.is_dir()),
                key=lambda path: path.name.casefold(),
            )
        except (OSError, PermissionError) as exc:
            messagebox.showerror(
                "Could not open folder",
                f"Unable to read:\n{self.current_dir}\n\n{exc}",
                parent=self,
            )
            return []

    def _load_directory(self) -> None:
        self.path_var.set(str(self.current_dir))
        self.child_folders = self._child_directories()
        self.folder_list.delete(0, "end")
        for folder in self.child_folders:
            self.folder_list.insert("end", folder.name)
        if self.child_folders:
            self.folder_list.selection_set(0)
            self.folder_list.activate(0)
            self.selection.anchor = 0

    def go_up(self) -> None:
        parent = self.current_dir.parent
        if parent != self.current_dir:
            self.current_dir = parent
            self._load_directory()

    def go_to_typed_path(self, _event: Optional[tk.Event] = None) -> str:
        candidate = Path(self.path_var.get().strip()).expanduser()
        if not candidate.is_dir():
            messagebox.showerror("Folder not found", f"This folder does not exist:\n{candidate}", parent=self)
            return "break"
        self.current_dir = candidate.resolve()
        self._load_directory()
        return "break"

    def open_active_folder(self, event: Optional[tk.Event] = None) -> str:
        index = self.folder_list.nearest(event.y) if event is not None and hasattr(event, "y") else int(self.folder_list.index("active"))
        if 0 <= index < len(self.child_folders):
            self.current_dir = self.child_folders[index]
            self._load_directory()
        return "break"

    def accept_selected(self) -> None:
        indices = list(self.folder_list.curselection())
        if not indices:
            messagebox.showinfo("No folders selected", "Select one or more folders first.", parent=self)
            return
        self.result = [str(self.child_folders[index].resolve()) for index in indices]
        self.destroy()

    def accept_current(self) -> None:
        self.result = [str(self.current_dir.resolve())]
        self.destroy()

    def cancel(self) -> None:
        self.result = []
        self.destroy()

    @classmethod
    def ask_folders(cls, parent: tk.Widget, title: str, initial_dir: Path) -> List[str]:
        dialog = cls(parent, title, initial_dir)
        parent.wait_window(dialog)
        return dialog.result


class FolderSelector(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        label_text: str,
        variable: tk.StringVar,
        dialog_title: str,
        default_initial_dir: Path,
    ) -> None:
        super().__init__(parent)
        self.variable = variable
        self.dialog_title = dialog_title
        self.default_initial_dir = default_initial_dir

        ttk.Label(self, text=label_text).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.entry = ttk.Entry(self, textvariable=self.variable)
        self.entry.grid(row=1, column=0, sticky="ew")
        self.browse_button = ttk.Button(self, text="Browse…", command=self.choose_folder)
        self.browse_button.grid(row=1, column=1, padx=(8, 0))
        self.columnconfigure(0, weight=1)

    def choose_folder(self) -> None:
        current = self.variable.get().strip()
        initial = self.default_initial_dir
        if current:
            candidate = Path(current).expanduser()
            if candidate.exists():
                initial = candidate
            elif candidate.parent.exists():
                initial = candidate.parent

        selected = filedialog.askdirectory(
            parent=self,
            title=self.dialog_title,
            initialdir=str(initial),
            mustexist=False,
        )
        if selected:
            self.variable.set(selected)

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.entry.configure(state=state)
        self.browse_button.configure(state=state)


class ImagingReviewWindow(ttk.Frame):
    """Embedded page for reviewing headers and raw/defaced NIfTI data."""

    def __init__(
        self,
        parent: "ImagingDashboard",
        prepared_dir: Path,
        scrubbed_dir: Path,
        defaced_dir: Path,
        state_path: Path,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.on_close = on_close
        self.prepared_dir = prepared_dir
        self.scrubbed_dir = scrubbed_dir
        self.defaced_dir = defaced_dir
        self.state_path = state_path
        self.items: list[dict[str, object]] = []
        self.current_index: Optional[int] = None
        self.review_state = self._load_state()

        self.raw_image = None
        self.defaced_image = None
        self.raw_data = None
        self.defaced_data = None
        self.axes = {}

        self.x_index = 0
        self.y_index = 0
        self.z_index = 0
        self.current_volume = 0
        self.intensity_limits = (0.0, 1.0)

        self.field_var = tk.StringVar()
        self.value_var = tk.StringVar()
        self.status_var = tk.StringVar(
            value="Select an image."
        )

        self.x_var = tk.DoubleVar(value=0)
        self.y_var = tk.DoubleVar(value=0)
        self.z_var = tk.DoubleVar(value=0)
        self.volume_var = tk.DoubleVar(value=0)

        self._build_items()
        self._build_interface()
        self._populate_file_list()

    def _close_page(self) -> None:
        if self.on_close is not None:
            self.on_close()
        else:
            self.destroy()

    def _load_state(self) -> dict[str, object]:
        if not self.state_path.exists():
            return {}

        try:
            payload = json.loads(
                self.state_path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return {}

        if type(payload) is not dict:
            return {}

        normalized = {}

        for key, value in payload.items():
            if type(value) is str:
                normalized[str(key)] = {
                    "status": value,
                    "accepted_defaced_path": "",
                    "defacing_source": (
                        "pydeface"
                        if value == "Accepted"
                        else ""
                    ),
                }
            elif type(value) is dict:
                normalized[str(key)] = {
                    "status": str(
                        value.get(
                            "status",
                            "Pending",
                        )
                    ),
                    "accepted_defaced_path": str(
                        value.get(
                            "accepted_defaced_path",
                            "",
                        )
                        or ""
                    ),
                    "defacing_source": str(
                        value.get(
                            "defacing_source",
                            "",
                        )
                        or ""
                    ),
                }

        return normalized

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.state_path.write_text(
            json.dumps(
                self.review_state,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _build_items(self) -> None:
        for prepared_path in sorted(
            path
            for path in self.prepared_dir.rglob("*")
            if is_nifti(path)
        ):
            relative = prepared_path.relative_to(
                self.prepared_dir
            )
            base = strip_nifti_suffix(
                prepared_path
            )

            scrubbed_candidates = [
                self.scrubbed_dir
                / relative.parent
                / f"{base}_scrubbed.nii.gz",
                self.scrubbed_dir
                / relative.parent
                / f"{base}_scrubbed.nii",
            ]
            scrubbed_path = next(
                (
                    path
                    for path in scrubbed_candidates
                    if path.exists()
                ),
                None,
            )

            if scrubbed_path is None:
                continue

            scrubbed_base = strip_nifti_suffix(
                scrubbed_path
            )
            defaced_candidates = [
                self.defaced_dir
                / relative.parent
                / f"{scrubbed_base}_defaced.nii.gz",
                self.defaced_dir
                / relative.parent
                / f"{scrubbed_base}_defaced.nii",
            ]
            automated_defaced = next(
                (
                    path
                    for path in defaced_candidates
                    if path.exists()
                ),
                None,
            )

            if automated_defaced is None:
                continue

            key = str(relative)
            saved = self.review_state.get(
                key,
                {},
            )

            if type(saved) is not dict:
                saved = {}

            accepted_path = str(
                saved.get(
                    "accepted_defaced_path",
                    "",
                )
                or ""
            )

            review_defaced = automated_defaced

            if accepted_path:
                candidate = Path(
                    accepted_path
                ).expanduser()

                if candidate.is_file():
                    review_defaced = candidate.resolve()

            self.items.append({
                "key": key,
                "prepared": prepared_path,
                "scrubbed": scrubbed_path,
                "automated_defaced": automated_defaced,
                "review_defaced": review_defaced,
                "accepted_defaced_path": accepted_path,
                "defacing_source": str(
                    saved.get(
                        "defacing_source",
                        "",
                    )
                    or ""
                ),
                "status": str(
                    saved.get(
                        "status",
                        "Pending",
                    )
                ),
            })

    def _build_interface(self) -> None:
        root = ttk.Frame(
            self,
            padding=12,
        )
        root.pack(
            fill="both",
            expand=True,
        )
        root.columnconfigure(
            1,
            weight=1,
        )
        root.rowconfigure(
            0,
            weight=1,
        )

        sidebar = ttk.LabelFrame(
            root,
            text="NIfTI files",
            padding=8,
        )
        sidebar.grid(
            row=0,
            column=0,
            sticky="nsw",
            padx=(0, 10),
        )
        sidebar.rowconfigure(
            0,
            weight=1,
        )

        self.file_list = tk.Listbox(
            sidebar,
            width=42,
            exportselection=False,
        )
        self.file_list.grid(
            row=0,
            column=0,
            sticky="ns",
        )
        self.file_list.bind(
            "<<ListboxSelect>>",
            self._on_file_selected,
        )

        scroll = ttk.Scrollbar(
            sidebar,
            orient="vertical",
            command=self.file_list.yview,
        )
        scroll.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        self.file_list.configure(
            yscrollcommand=scroll.set,
        )

        content = ttk.Frame(root)
        content.grid(
            row=0,
            column=1,
            sticky="nsew",
        )
        content.columnconfigure(
            0,
            weight=1,
        )
        content.rowconfigure(
            0,
            weight=1,
        )
        content.rowconfigure(
            1,
            weight=3,
        )

        header_frame = ttk.LabelFrame(
            content,
            text="Raw header versus scrubbed header",
            padding=8,
        )
        header_frame.grid(
            row=0,
            column=0,
            sticky="nsew",
        )
        header_frame.columnconfigure(
            0,
            weight=1,
        )
        header_frame.rowconfigure(
            0,
            weight=1,
        )

        self.header_tree = ttk.Treeview(
            header_frame,
            columns=(
                "field",
                "raw",
                "scrubbed",
                "editable",
            ),
            show="headings",
            selectmode="browse",
        )

        for column, heading, width in (
            ("field", "Field", 180),
            ("raw", "Raw", 390),
            ("scrubbed", "Scrubbed", 390),
            ("editable", "Editable", 80),
        ):
            self.header_tree.heading(
                column,
                text=heading,
            )
            self.header_tree.column(
                column,
                width=width,
                anchor="w",
            )

        self.header_tree.grid(
            row=0,
            column=0,
            sticky="nsew",
        )
        self.header_tree.bind(
            "<<TreeviewSelect>>",
            self._on_header_selected,
        )

        header_scroll = ttk.Scrollbar(
            header_frame,
            orient="vertical",
            command=self.header_tree.yview,
        )
        header_scroll.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        self.header_tree.configure(
            yscrollcommand=header_scroll.set,
        )

        edit = ttk.Frame(
            header_frame
        )
        edit.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )
        edit.columnconfigure(
            3,
            weight=1,
        )

        ttk.Label(
            edit,
            text="Selected field",
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Entry(
            edit,
            textvariable=self.field_var,
            state="readonly",
            width=22,
        ).grid(
            row=0,
            column=1,
            padx=(6, 14),
        )

        ttk.Label(
            edit,
            text="Scrubbed value",
        ).grid(
            row=0,
            column=2,
            sticky="w",
        )

        self.value_entry = ttk.Entry(
            edit,
            textvariable=self.value_var,
        )
        self.value_entry.grid(
            row=0,
            column=3,
            sticky="ew",
            padx=(6, 8),
        )

        ttk.Button(
            edit,
            text="Save Header Edit",
            command=self._save_header_edit,
        ).grid(
            row=0,
            column=4,
        )

        image_frame = ttk.LabelFrame(
            content,
            text="Interactive raw versus defaced image review",
            padding=8,
        )
        image_frame.grid(
            row=1,
            column=0,
            sticky="nsew",
            pady=(10, 0),
        )
        image_frame.columnconfigure(
            0,
            weight=1,
        )
        image_frame.rowconfigure(
            0,
            weight=1,
        )

        self.figure = Figure(
            figsize=(12, 7),
            dpi=100,
        )
        self.canvas = FigureCanvasTkAgg(
            self.figure,
            master=image_frame,
        )
        self.canvas.get_tk_widget().grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        self.canvas.mpl_connect(
            "scroll_event",
            self._on_figure_scroll,
        )
        self.canvas.mpl_connect(
            "button_press_event",
            self._on_figure_click,
        )

        controls = ttk.Frame(
            image_frame
        )
        controls.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(8, 0),
        )
        controls.columnconfigure(
            1,
            weight=1,
        )

        (
            self.x_scale,
            self.x_label,
        ) = self._build_axis_control(
            controls,
            row=0,
            label="Sagittal X",
            variable=self.x_var,
            command=self._x_changed,
        )
        (
            self.y_scale,
            self.y_label,
        ) = self._build_axis_control(
            controls,
            row=1,
            label="Coronal Y",
            variable=self.y_var,
            command=self._y_changed,
        )
        (
            self.z_scale,
            self.z_label,
        ) = self._build_axis_control(
            controls,
            row=2,
            label="Axial Z",
            variable=self.z_var,
            command=self._z_changed,
        )

        ttk.Label(
            controls,
            text="4D volume",
        ).grid(
            row=3,
            column=0,
            sticky="w",
        )

        self.volume_scale = ttk.Scale(
            controls,
            variable=self.volume_var,
            from_=0,
            to=0,
            orient="horizontal",
            command=self._volume_changed,
        )
        self.volume_scale.grid(
            row=3,
            column=1,
            sticky="ew",
            padx=(8, 8),
        )

        self.volume_label = ttk.Label(
            controls,
            text="0 / 0",
            width=14,
            anchor="e",
        )
        self.volume_label.grid(
            row=3,
            column=2,
            sticky="e",
        )

        ttk.Label(
            controls,
            text=(
                "Mouse wheel over Axial, Coronal, or Sagittal to move "
                "through the complete slice stack. Click inside a view "
                "to reposition the linked location in all six panels."
            ),
            wraplength=1100,
        ).grid(
            row=4,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(6, 0),
        )

        footer = ttk.Frame(root)
        footer.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(10, 0),
        )

        ttk.Label(
            footer,
            textvariable=self.status_var,
        ).pack(side="left")

        ttk.Button(
            footer,
            text="Back to Imaging",
            command=self._close_page,
        ).pack(side="right")

        ttk.Button(
            footer,
            text="Reject",
            command=self._reject_current,
        ).pack(
            side="right",
            padx=(0, 8),
        )

        ttk.Button(
            footer,
            text="Accept",
            command=lambda: self._set_status(
                "Accepted"
            ),
        ).pack(
            side="right",
            padx=(0, 8),
        )

    @staticmethod
    def _build_axis_control(
        parent,
        row,
        label,
        variable,
        command,
    ):
        ttk.Label(
            parent,
            text=label,
        ).grid(
            row=row,
            column=0,
            sticky="w",
        )

        scale = ttk.Scale(
            parent,
            variable=variable,
            from_=0,
            to=0,
            orient="horizontal",
            command=command,
        )
        scale.grid(
            row=row,
            column=1,
            sticky="ew",
            padx=(8, 8),
        )

        value_label = ttk.Label(
            parent,
            text="0 / 0",
            width=14,
            anchor="e",
        )
        value_label.grid(
            row=row,
            column=2,
            sticky="e",
        )

        return scale, value_label

    def _populate_file_list(self) -> None:
        self.file_list.delete(
            0,
            "end",
        )

        for item in self.items:
            self.file_list.insert(
                "end",
                f"[{item['status']}] {item['key']}",
            )

        if self.items:
            self.file_list.selection_set(
                0
            )
            self.file_list.activate(
                0
            )
            self._load_item(
                0
            )
        else:
            self.status_var.set(
                "No matching prepared, scrubbed, and defaced files were found."
            )

    def _on_file_selected(
        self,
        _event: tk.Event,
    ) -> None:
        selected = self.file_list.curselection()

        if selected:
            self._load_item(
                int(
                    selected[0]
                )
            )

    @staticmethod
    def _header_dict(
        path: Path,
    ) -> dict[str, str]:
        img = nib.load(
            str(path)
        )
        values: dict[str, str] = {}

        for key in img.header.keys():
            value = img.header[key]

            try:
                if hasattr(
                    value,
                    "tolist",
                ):
                    value = value.tolist()
            except Exception:
                pass

            if type(value) is bytes:
                value = value.decode(
                    "utf-8",
                    errors="replace",
                )

            values[
                str(key)
            ] = str(value)

        values["shape"] = str(
            tuple(
                int(value)
                for value in img.shape
            )
        )
        values["affine"] = np.array2string(
            img.affine,
            precision=5,
        )

        return values

    def _populate_header_tree(
        self,
        prepared: Path,
        scrubbed: Path,
    ) -> None:
        for item_id in (
            self.header_tree.get_children()
        ):
            self.header_tree.delete(
                item_id
            )

        raw = self._header_dict(
            prepared
        )
        clean = self._header_dict(
            scrubbed
        )

        for key in sorted(
            set(raw) | set(clean)
        ):
            self.header_tree.insert(
                "",
                "end",
                iid=f"field-{key}",
                values=(
                    key,
                    raw.get(
                        key,
                        "",
                    ),
                    clean.get(
                        key,
                        "",
                    ),
                    (
                        "Yes"
                        if key in EDITABLE_HEADER_FIELDS
                        else "No"
                    ),
                ),
            )

    def _on_header_selected(
        self,
        _event: tk.Event,
    ) -> None:
        selected = (
            self.header_tree.selection()
        )

        if not selected:
            return

        values = self.header_tree.item(
            selected[0],
            "values",
        )
        field = str(
            values[0]
        )

        self.field_var.set(
            field
        )
        self.value_var.set(
            str(
                values[2]
            )
        )
        self.value_entry.configure(
            state=(
                "normal"
                if field in EDITABLE_HEADER_FIELDS
                else "disabled"
            )
        )

    def _save_header_edit(self) -> None:
        if self.current_index is None:
            return

        field = self.field_var.get()

        if field not in EDITABLE_HEADER_FIELDS:
            messagebox.showinfo(
                "Read-only field",
                "Only NIfTI text fields are editable.",
                parent=self,
            )
            return

        item = self.items[
            self.current_index
        ]
        scrubbed_path = Path(
            item["scrubbed"]
        )
        image = nib.load(
            str(scrubbed_path)
        )
        header = image.header.copy()
        header[field] = (
            self.value_var.get().encode(
                "utf-8"
            )
        )
        updated = nib.Nifti1Image(
            np.asanyarray(
                image.dataobj
            ),
            image.affine,
            header,
        )

        qform, qform_code = (
            image.get_qform(
                coded=True
            )
        )
        sform, sform_code = (
            image.get_sform(
                coded=True
            )
        )
        updated.set_qform(
            qform,
            int(qform_code),
        )
        updated.set_sform(
            sform,
            int(sform_code),
        )
        nib.save(
            updated,
            str(scrubbed_path),
        )

        self._populate_header_tree(
            Path(
                item["prepared"]
            ),
            scrubbed_path,
        )
        self.status_var.set(
            "Header edit saved. Rerun defacing before accepting if this edit should be reflected in the defaced file."
        )

    def _load_item(
        self,
        index: int,
    ) -> None:
        self.current_index = index
        item = self.items[
            index
        ]

        prepared_path = Path(
            item["prepared"]
        )
        defaced_path = Path(
            item["review_defaced"]
        )

        self._populate_header_tree(
            prepared_path,
            Path(
                item["scrubbed"]
            ),
        )

        try:
            self.raw_image = nib.load(
                str(prepared_path)
            )
            self.defaced_image = nib.load(
                str(defaced_path)
            )

            if (
                self.raw_image.shape
                != self.defaced_image.shape
            ):
                raise ValueError(
                    "Image shape mismatch: "
                    f"{self.raw_image.shape} vs "
                    f"{self.defaced_image.shape}"
                )

            if len(
                self.raw_image.shape
            ) not in {
                3,
                4,
            }:
                raise ValueError(
                    "Only 3D and 4D NIfTI images are supported."
                )

            self.raw_data = (
                self.raw_image.dataobj
            )
            self.defaced_data = (
                self.defaced_image.dataobj
            )

            shape = self.raw_image.shape

            self.x_index = (
                shape[0] // 2
            )
            self.y_index = (
                shape[1] // 2
            )
            self.z_index = (
                shape[2] // 2
            )
            self.current_volume = 0

            self.x_scale.configure(
                to=max(
                    0,
                    shape[0] - 1,
                )
            )
            self.y_scale.configure(
                to=max(
                    0,
                    shape[1] - 1,
                )
            )
            self.z_scale.configure(
                to=max(
                    0,
                    shape[2] - 1,
                )
            )

            self.x_var.set(
                self.x_index
            )
            self.y_var.set(
                self.y_index
            )
            self.z_var.set(
                self.z_index
            )

            max_volume = (
                shape[3] - 1
                if len(shape) == 4
                else 0
            )
            self.volume_scale.configure(
                to=max(
                    0,
                    max_volume,
                ),
                state=(
                    "normal"
                    if len(shape) == 4
                    else "disabled"
                ),
            )
            self.volume_var.set(
                0
            )

            self._update_intensity_limits()
            self._refresh_coordinate_labels()
            self._draw_views()

        except Exception as exc:
            self.raw_image = None
            self.defaced_image = None
            self.raw_data = None
            self.defaced_data = None
            self.status_var.set(
                str(exc)
            )
            self.figure.clear()
            self.canvas.draw_idle()
            return

        self.status_var.set(
            f"{item['key']} | Review status: {item['status']}"
        )

    def _current_volume_data(
        self,
    ) -> tuple[
        np.ndarray,
        np.ndarray,
    ]:
        if (
            self.raw_data is None
            or self.defaced_data is None
        ):
            raise RuntimeError(
                "No image loaded."
            )

        if len(
            self.raw_image.shape
        ) == 4:
            raw = np.asanyarray(
                self.raw_data[
                    ...,
                    self.current_volume
                ]
            )
            clean = np.asanyarray(
                self.defaced_data[
                    ...,
                    self.current_volume
                ]
            )
        else:
            raw = np.asanyarray(
                self.raw_data
            )
            clean = np.asanyarray(
                self.defaced_data
            )

        return raw, clean

    def _update_intensity_limits(
        self,
    ) -> None:
        raw, clean = (
            self._current_volume_data()
        )

        raw_finite = raw[
            np.isfinite(raw)
        ]
        clean_finite = clean[
            np.isfinite(clean)
        ]

        if (
            raw_finite.size == 0
            and clean_finite.size == 0
        ):
            self.intensity_limits = (
                0.0,
                1.0,
            )
            return

        combined = np.concatenate(
            (
                raw_finite.ravel(),
                clean_finite.ravel(),
            )
        )

        low, high = np.percentile(
            combined,
            [
                1,
                99,
            ],
        )
        low = float(low)
        high = float(high)

        if high <= low:
            high = low + 1.0

        self.intensity_limits = (
            low,
            high,
        )

    @staticmethod
    def _clamp(
        value: int,
        size: int,
    ) -> int:
        return max(
            0,
            min(
                size - 1,
                value,
            ),
        )

    def _x_changed(
        self,
        value: str,
    ) -> None:
        if self.raw_image is None:
            return

        self.x_index = self._clamp(
            int(
                round(
                    float(value)
                )
            ),
            self.raw_image.shape[0],
        )
        self._refresh_coordinate_labels()
        self._draw_views()

    def _y_changed(
        self,
        value: str,
    ) -> None:
        if self.raw_image is None:
            return

        self.y_index = self._clamp(
            int(
                round(
                    float(value)
                )
            ),
            self.raw_image.shape[1],
        )
        self._refresh_coordinate_labels()
        self._draw_views()

    def _z_changed(
        self,
        value: str,
    ) -> None:
        if self.raw_image is None:
            return

        self.z_index = self._clamp(
            int(
                round(
                    float(value)
                )
            ),
            self.raw_image.shape[2],
        )
        self._refresh_coordinate_labels()
        self._draw_views()

    def _volume_changed(
        self,
        value: str,
    ) -> None:
        if (
            self.raw_image is None
            or len(
                self.raw_image.shape
            ) != 4
        ):
            return

        self.current_volume = self._clamp(
            int(
                round(
                    float(value)
                )
            ),
            self.raw_image.shape[3],
        )
        self._update_intensity_limits()
        self._refresh_coordinate_labels()
        self._draw_views()

    def _refresh_coordinate_labels(
        self,
    ) -> None:
        if self.raw_image is None:
            return

        shape = self.raw_image.shape

        self.x_label.configure(
            text=(
                f"{self.x_index} / "
                f"{shape[0] - 1}"
            )
        )
        self.y_label.configure(
            text=(
                f"{self.y_index} / "
                f"{shape[1] - 1}"
            )
        )
        self.z_label.configure(
            text=(
                f"{self.z_index} / "
                f"{shape[2] - 1}"
            )
        )

        max_volume = (
            shape[3] - 1
            if len(shape) == 4
            else 0
        )
        self.volume_label.configure(
            text=(
                f"{self.current_volume} / "
                f"{max_volume}"
            )
        )

    def _draw_views(self) -> None:
        if (
            self.raw_image is None
            or self.defaced_image is None
        ):
            return

        try:
            raw, clean = (
                self._current_volume_data()
            )
        except Exception as exc:
            self.status_var.set(
                str(exc)
            )
            return

        self.figure.clear()
        self.axes = {}

        views = (
            (
                "Axial",
                np.rot90(
                    raw[
                        :,
                        :,
                        self.z_index,
                    ]
                ),
                np.rot90(
                    clean[
                        :,
                        :,
                        self.z_index,
                    ]
                ),
                "axial",
            ),
            (
                "Coronal",
                np.rot90(
                    raw[
                        :,
                        self.y_index,
                        :,
                    ]
                ),
                np.rot90(
                    clean[
                        :,
                        self.y_index,
                        :,
                    ]
                ),
                "coronal",
            ),
            (
                "Sagittal",
                np.rot90(
                    raw[
                        self.x_index,
                        :,
                        :,
                    ]
                ),
                np.rot90(
                    clean[
                        self.x_index,
                        :,
                        :,
                    ]
                ),
                "sagittal",
            ),
        )

        low, high = (
            self.intensity_limits
        )

        for column, (
            name,
            raw_view,
            clean_view,
            plane,
        ) in enumerate(
            views
        ):
            raw_axis = (
                self.figure.add_subplot(
                    2,
                    3,
                    column + 1,
                )
            )
            raw_axis.imshow(
                raw_view,
                cmap="gray",
                origin="lower",
                vmin=low,
                vmax=high,
            )
            raw_axis.set_title(
                f"Raw {name}"
            )
            raw_axis.axis(
                "off"
            )

            clean_axis = (
                self.figure.add_subplot(
                    2,
                    3,
                    column + 4,
                )
            )
            clean_axis.imshow(
                clean_view,
                cmap="gray",
                origin="lower",
                vmin=low,
                vmax=high,
            )
            clean_axis.set_title(
                f"Defaced {name}"
            )
            clean_axis.axis(
                "off"
            )

            self.axes[
                raw_axis
            ] = plane
            self.axes[
                clean_axis
            ] = plane

        if len(
            self.raw_image.shape
        ) == 4:
            title = (
                f"Linked 3D navigation | "
                f"Volume {self.current_volume} / "
                f"{self.raw_image.shape[3] - 1}"
            )
        else:
            title = (
                "Linked 3D navigation"
            )

        self.figure.suptitle(
            title
        )
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _on_figure_scroll(
        self,
        event,
    ) -> None:
        if (
            self.raw_image is None
            or event.inaxes not in self.axes
        ):
            return

        if event.button == "up":
            direction = 1
        elif event.button == "down":
            direction = -1
        else:
            return

        plane = self.axes[
            event.inaxes
        ]

        if plane == "axial":
            self.z_index = self._clamp(
                self.z_index + direction,
                self.raw_image.shape[2],
            )
            self.z_var.set(
                self.z_index
            )

        elif plane == "coronal":
            self.y_index = self._clamp(
                self.y_index + direction,
                self.raw_image.shape[1],
            )
            self.y_var.set(
                self.y_index
            )

        elif plane == "sagittal":
            self.x_index = self._clamp(
                self.x_index + direction,
                self.raw_image.shape[0],
            )
            self.x_var.set(
                self.x_index
            )

        self._refresh_coordinate_labels()
        self._draw_views()

    def _on_figure_click(
        self,
        event,
    ) -> None:
        if (
            self.raw_image is None
            or event.inaxes not in self.axes
            or event.xdata is None
            or event.ydata is None
        ):
            return

        plane = self.axes[
            event.inaxes
        ]
        shape = self.raw_image.shape

        display_x = int(
            round(
                event.xdata
            )
        )
        display_y = int(
            round(
                event.ydata
            )
        )

        if plane == "axial":
            self.x_index = self._clamp(
                display_y,
                shape[0],
            )
            self.y_index = self._clamp(
                shape[1] - 1 - display_x,
                shape[1],
            )
            self.x_var.set(
                self.x_index
            )
            self.y_var.set(
                self.y_index
            )

        elif plane == "coronal":
            self.x_index = self._clamp(
                display_y,
                shape[0],
            )
            self.z_index = self._clamp(
                shape[2] - 1 - display_x,
                shape[2],
            )
            self.x_var.set(
                self.x_index
            )
            self.z_var.set(
                self.z_index
            )

        elif plane == "sagittal":
            self.y_index = self._clamp(
                display_y,
                shape[1],
            )
            self.z_index = self._clamp(
                shape[2] - 1 - display_x,
                shape[2],
            )
            self.y_var.set(
                self.y_index
            )
            self.z_var.set(
                self.z_index
            )

        self._refresh_coordinate_labels()
        self._draw_views()

    def _reject_current(self) -> None:
        if self.current_index is None:
            return

        choice = self._defacing_rejection_choice()

        if choice == "replace":
            self._choose_external_defaced()
            return

        if choice == "hold":
            self._set_status(
                "On Hold - Needs Defaced Replacement"
            )
            return

        if choice == "exclude":
            self._set_status(
                "Rejected - Not Included"
            )

    def _defacing_rejection_choice(self) -> str:
        dialog = tk.Toplevel(
            self
        )
        dialog.title(
            "Defacing Rejected"
        )
        dialog.transient(
            self
        )
        dialog.resizable(
            False,
            False,
        )

        result = tk.StringVar(
            value="cancel"
        )

        root = ttk.Frame(
            dialog,
            padding=16,
        )
        root.pack(
            fill="both",
            expand=True,
        )

        ttk.Label(
            root,
            text="The automated defacing result was rejected.",
            font=(
                "",
                13,
                "bold",
            ),
        ).pack(
            anchor="w",
        )

        ttk.Label(
            root,
            text=(
                "Choose what should happen to this image. "
                "Images placed on hold or rejected will not continue "
                "to Metadata & BIDS."
            ),
            wraplength=520,
        ).pack(
            anchor="w",
            pady=(6, 14),
        )

        buttons = ttk.Frame(
            root
        )
        buttons.pack(
            fill="x",
        )

        def finish(
            value: str,
        ) -> None:
            result.set(
                value
            )
            dialog.destroy()

        ttk.Button(
            buttons,
            text="Upload Replacement",
            command=lambda: finish(
                "replace"
            ),
        ).pack(
            fill="x",
            pady=(0, 6),
        )

        ttk.Button(
            buttons,
            text="Put on Hold",
            command=lambda: finish(
                "hold"
            ),
        ).pack(
            fill="x",
            pady=(0, 6),
        )

        ttk.Button(
            buttons,
            text="Reject / Do Not Include",
            command=lambda: finish(
                "exclude"
            ),
        ).pack(
            fill="x",
            pady=(0, 6),
        )

        ttk.Button(
            buttons,
            text="Cancel",
            command=lambda: finish(
                "cancel"
            ),
        ).pack(
            fill="x",
        )

        dialog.protocol(
            "WM_DELETE_WINDOW",
            lambda: finish(
                "cancel"
            ),
        )
        dialog.grab_set()
        dialog.wait_window()

        return result.get()

    def _choose_external_defaced(self) -> None:
        if self.current_index is None:
            return

        item = self.items[
            self.current_index
        ]

        selected = filedialog.askopenfilename(
            parent=self,
            title="Select externally defaced NIfTI",
            initialdir=str(
                Path(
                    item["prepared"]
                ).parent
            ),
        )

        if not selected:
            return

        selected_path = Path(
            selected
        ).expanduser().resolve()

        if not is_nifti(
            selected_path
        ):
            messagebox.showerror(
                "Invalid replacement",
                "Select a .nii or .nii.gz NIfTI file.",
                parent=self,
            )
            return

        prepared_path = Path(
            item["prepared"]
        )

        try:
            self._validate_external_defaced(
                prepared_path,
                selected_path,
            )
        except ValueError as exc:
            messagebox.showerror(
                "Replacement validation failed",
                str(exc),
                parent=self,
            )
            return

        relative = prepared_path.relative_to(
            self.prepared_dir
        )
        replacement_dir = (
            self.defaced_dir.parent
            / "external_defaced"
            / relative.parent
        )
        replacement_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        base = strip_nifti_suffix(
            prepared_path
        )
        extension = (
            ".nii.gz"
            if selected_path.name.endswith(
                ".nii.gz"
            )
            else ".nii"
        )
        destination = (
            replacement_dir
            / f"{base}_external_defaced{extension}"
        )

        shutil.copy2(
            selected_path,
            destination,
        )

        source_json = matching_json_path(
            selected_path
        )
        if source_json is not None:
            shutil.copy2(
                source_json,
                replacement_dir
                / f"{base}_external_defaced.json",
            )

        item[
            "review_defaced"
        ] = destination
        item[
            "accepted_defaced_path"
        ] = str(
            destination.resolve()
        )
        item[
            "defacing_source"
        ] = "external"
        item[
            "status"
        ] = "Pending External Review"

        self.review_state[
            str(
                item["key"]
            )
        ] = {
            "status": "Pending External Review",
            "accepted_defaced_path": str(
                destination.resolve()
            ),
            "defacing_source": "external",
        }
        self._save_state()
        self._refresh_file_list_row(
            self.current_index
        )
        self._load_item(
            self.current_index
        )

        self.status_var.set(
            (
                f"{item['key']} | External replacement passed "
                "geometry checks and is ready for review."
            )
        )

    @staticmethod
    def _validate_external_defaced(
        original_path: Path,
        replacement_path: Path,
    ) -> None:
        try:
            original = nib.load(
                str(
                    original_path
                )
            )
            replacement = nib.load(
                str(
                    replacement_path
                )
            )
        except Exception as exc:
            raise ValueError(
                f"Could not read the replacement NIfTI: {exc}"
            ) from exc

        if original.shape != replacement.shape:
            raise ValueError(
                (
                    "The replacement dimensions do not match the "
                    f"original image.\n\nOriginal: {original.shape}\n"
                    f"Replacement: {replacement.shape}"
                )
            )

        if len(
            original.shape
        ) not in {
            3,
            4,
        }:
            raise ValueError(
                "Only 3D and 4D NIfTI replacements are supported."
            )

        if not np.allclose(
            original.affine,
            replacement.affine,
            rtol=1e-5,
            atol=1e-6,
        ):
            raise ValueError(
                (
                    "The replacement affine does not match the original "
                    "image. The replacement must preserve the original "
                    "spatial geometry."
                )
            )

        original_zooms = tuple(
            float(value)
            for value in original.header.get_zooms()
        )
        replacement_zooms = tuple(
            float(value)
            for value in replacement.header.get_zooms()
        )

        if (
            len(
                original_zooms
            )
            != len(
                replacement_zooms
            )
            or not np.allclose(
                original_zooms,
                replacement_zooms,
                rtol=1e-5,
                atol=1e-6,
            )
        ):
            raise ValueError(
                "The replacement voxel sizes do not match the original image."
            )

    def _refresh_file_list_row(
        self,
        index: int,
    ) -> None:
        item = self.items[
            index
        ]

        self.file_list.delete(
            index
        )
        self.file_list.insert(
            index,
            f"[{item['status']}] {item['key']}",
        )
        self.file_list.selection_set(
            index
        )
        self.file_list.activate(
            index
        )

    def _set_status(
        self,
        status: str,
    ) -> None:
        if self.current_index is None:
            return

        item = self.items[
            self.current_index
        ]

        if status == "Accepted":
            if item.get(
                "defacing_source"
            ) == "external":
                visible_status = (
                    "Accepted - External"
                )
            else:
                visible_status = "Accepted"
                item[
                    "defacing_source"
                ] = "pydeface"
                item[
                    "accepted_defaced_path"
                ] = str(
                    Path(
                        item[
                            "automated_defaced"
                        ]
                    ).resolve()
                )
        else:
            visible_status = status

            if visible_status == (
                "On Hold - Needs Defaced Replacement"
            ):
                item[
                    "accepted_defaced_path"
                ] = ""
                item[
                    "defacing_source"
                ] = ""

        item[
            "status"
        ] = visible_status

        self.review_state[
            str(
                item["key"]
            )
        ] = {
            "status": visible_status,
            "accepted_defaced_path": str(
                item.get(
                    "accepted_defaced_path",
                    "",
                )
                or ""
            ),
            "defacing_source": str(
                item.get(
                    "defacing_source",
                    "",
                )
                or ""
            ),
        }
        self._save_state()

        index = self.current_index
        self._refresh_file_list_row(
            index
        )

        self.status_var.set(
            f"{item['key']} | Review status: {visible_status}"
        )

        if index + 1 < len(
            self.items
        ):
            self.file_list.selection_clear(
                0,
                "end",
            )
            self.file_list.selection_set(
                index + 1
            )
            self.file_list.activate(
                index + 1
            )
            self.file_list.see(
                index + 1
            )
            self._load_item(
                index + 1
            )



class MetadataConfirmationWindow(tk.Toplevel):
    """Require explicit confirmation of every included Image ID."""

    def __init__(
        self,
        parent: "BIDSMetadataWindow",
        records: list[Dict[str, object]],
        site_id: str,
        on_confirm: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.records = records
        self.site_id = site_id
        self.on_confirm = on_confirm
        self.confirmed: set[int] = set()

        self.title("Confirm Imaging Metadata")
        self.geometry("1120x760")
        self.minsize(900, 620)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self.status_var = tk.StringVar(
            value="Review each included image and confirm its metadata."
        )

        self._build_interface()
        self._populate_records()

    def _build_interface(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(
            root,
            text="Included images",
            padding=8,
        )
        left.grid(
            row=0,
            column=0,
            sticky="nsw",
            padx=(0, 10),
        )
        left.rowconfigure(0, weight=1)

        self.listbox = tk.Listbox(
            left,
            width=40,
            exportselection=False,
        )
        self.listbox.grid(
            row=0,
            column=0,
            sticky="ns",
        )
        self.listbox.bind(
            "<<ListboxSelect>>",
            self._selection_changed,
        )

        scroll = ttk.Scrollbar(
            left,
            orient="vertical",
            command=self.listbox.yview,
        )
        scroll.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        self.listbox.configure(
            yscrollcommand=scroll.set,
        )

        right = ttk.LabelFrame(
            root,
            text="Metadata review",
            padding=10,
        )
        right.grid(
            row=0,
            column=1,
            sticky="nsew",
        )
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.summary = tk.Text(
            right,
            wrap="word",
            state="disabled",
            font=("TkDefaultFont", 11),
        )
        self.summary.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        summary_scroll = ttk.Scrollbar(
            right,
            orient="vertical",
            command=self.summary.yview,
        )
        summary_scroll.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        self.summary.configure(
            yscrollcommand=summary_scroll.set,
        )

        actions = ttk.Frame(root)
        actions.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(10, 0),
        )

        ttk.Label(
            actions,
            textvariable=self.status_var,
        ).pack(side="left")

        ttk.Button(
            actions,
            text="Back to Edit",
            command=self.destroy,
        ).pack(side="right")

        self.convert_button = ttk.Button(
            actions,
            text="Confirm All & Convert",
            command=self._finish,
            state="disabled",
        )
        self.convert_button.pack(
            side="right",
            padx=(0, 8),
        )

        ttk.Button(
            actions,
            text="Confirm This Image",
            command=self._confirm_current,
        ).pack(
            side="right",
            padx=(0, 8),
        )

    def _populate_records(self) -> None:
        self.listbox.delete(0, "end")

        for record in self.records:
            metadata = record["cocanot_metadata"]
            image_id = metadata.get("Image ID") or "(no Image ID)"
            label = record.get("source_label") or record.get("nifti_path")

            self.listbox.insert(
                "end",
                f"[Pending] {image_id} | {label}",
            )

        if self.records:
            self.listbox.selection_set(0)
            self.listbox.activate(0)
            self._show_record(0)

    def _selection_changed(self, _event: tk.Event) -> None:
        selected = self.listbox.curselection()

        if selected:
            self._show_record(int(selected[0]))

    def _show_record(self, index: int) -> None:
        record = self.records[index]
        metadata = record["cocanot_metadata"]
        validation = record["metadata_validation"]

        lines = [
            f"Site: {self.site_id}",
            f"File: {record.get('source_label', '')}",
            f"Project: {record.get('project', '')}",
            (
                f"Project Description: "
                f"{record.get('project_description', '')}"
                if record.get("project_description")
                else ""
            ),
            "",
            "CoCANoT imaging metadata",
            "-" * 56,
        ]

        for rule in record["metadata_rules"]:
            field_name = rule["field_name"]
            value = metadata.get(field_name)

            if value in (None, "", []):
                shown = "(blank)"
            elif type(value) is list:
                shown = ", ".join(
                    str(item) for item in value
                )
            else:
                shown = str(value)

            lines.append(
                f"{field_name}: {shown}"
            )

        manual_review_fields = [
            result["field_name"]
            for result in validation["results"]
            if result["status"] == "manual_review"
            and metadata.get(result["field_name"])
        ]

        if manual_review_fields:
            lines.extend([
                "",
                "Free-text values requiring confirmation",
                "-" * 56,
            ])

            for field_name in manual_review_fields:
                lines.append(
                    f"{field_name}: "
                    f"{metadata.get(field_name)}"
                )

        self.summary.configure(state="normal")
        self.summary.delete("1.0", "end")
        self.summary.insert(
            "1.0",
            "\n".join(lines),
        )
        self.summary.configure(state="disabled")

    def _confirm_current(self) -> None:
        selected = self.listbox.curselection()

        if not selected:
            return

        index = int(selected[0])
        self.confirmed.add(index)

        record = self.records[index]
        metadata = record["cocanot_metadata"]
        image_id = metadata.get("Image ID") or "(no Image ID)"
        label = record.get("source_label") or record.get("nifti_path")

        self.listbox.delete(index)
        self.listbox.insert(
            index,
            f"[Confirmed] {image_id} | {label}",
        )
        self.listbox.selection_set(index)
        self.listbox.activate(index)

        if len(self.confirmed) == len(self.records):
            self.status_var.set(
                "All included images have been reviewed and confirmed."
            )
            self.convert_button.configure(
                state="normal"
            )
        else:
            self.status_var.set(
                f"Confirmed {len(self.confirmed)} "
                f"of {len(self.records)} images."
            )

        next_index = index + 1

        if next_index < len(self.records):
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(next_index)
            self.listbox.activate(next_index)
            self.listbox.see(next_index)
            self._show_record(next_index)

    def _finish(self) -> None:
        if len(self.confirmed) != len(self.records):
            return

        self.destroy()
        self.on_confirm()


def imaging_sequence_value(
    metadata: Dict[str, object],
) -> str:
    """Return the one MRI sequence assigned to this image."""

    for field_name in MRI_SEQUENCE_FIELDS:
        value = metadata.get(
            field_name
        )

        if type(value) is list:
            selected = [
                str(item).strip()
                for item in value
                if str(item).strip()
            ]

            if len(selected) == 1:
                return selected[0]

            if selected:
                return ""

            continue

        text = str(
            value
            or ""
        ).strip()

        if text:
            return text

    return ""


class BIDSMetadataWindow(ttk.Frame):
    """Embedded dictionary-driven CoCANoT Imaging metadata and BIDS page."""

    MRI_SEQUENCE_MAP = {
        "T1": ("anat", "T1w"),
        "T2": ("anat", "T2w"),
        "FLAIR": ("anat", "FLAIR"),
        "DWI": ("dwi", "dwi"),
        "SWI": ("anat", "T2starw"),
    }


    def __init__(
        self,
        parent: "ImagingDashboard",
        accepted_files: list[Path],
        output_dir: Path,
        overwrite: bool,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.parent_dashboard = parent
        self.on_close = on_close
        self.accepted_files = accepted_files
        self.output_dir = output_dir
        self.overwrite = overwrite

        self.metadata_dictionary = load_dictionary(
            METADATA_DICTIONARY
        )
        self.metadata_validator = MetadataValidator(
            self.metadata_dictionary
        )
        self.metadata_rules = (
            self.metadata_dictionary["tables"]["Imaging"][
                "fields"
            ]
        )

        self.metadata_store = LocalMetadataStore()
        self.site_id = self._require_site_id()

        if not self.site_id:
            self.after_idle(self.destroy)
            return

        self.records: Dict[str, Dict[str, object]] = {}
        self.metadata_controls: Dict[
            str,
            Dict[str, object],
        ] = {}

        self.project_var = tk.StringVar()
        self.project_description_var = tk.StringVar()
        self.session_var = tk.StringVar()
        self.existing_bids_by_size = self._index_existing_bids()
        self.site_var = tk.StringVar(
            value=f"Site: {self.site_id}"
        )

        self._build_interface()
        self._load_files()
        self._refresh_conditional_fields()

    def _close_page(self) -> None:
        if self.on_close is not None:
            self.on_close()
        else:
            self.destroy()

    def _scroll_metadata_with_wheel(
        self,
        event: tk.Event,
    ) -> Optional[str]:
        """Scroll the metadata form with a trackpad or mouse wheel."""
        pointer_widget = self.winfo_containing(
            self.winfo_pointerx(),
            self.winfo_pointery(),
        )

        if not self._widget_is_in_metadata_area(
            pointer_widget
        ):
            return None

        # Let controls that have their own scrolling keep their normal behavior.
        if type(pointer_widget) in {
            tk.Listbox,
            tk.Text,
        }:
            return None

        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            delta = getattr(event, "delta", 0)

            if delta == 0:
                return None

            # Windows commonly reports +/-120 per wheel notch.
            # macOS trackpads commonly report smaller continuous values.
            if abs(delta) >= 120:
                units = -int(delta / 120) * 3
            else:
                units = -1 if delta > 0 else 1

        self.metadata_canvas.yview_scroll(
            units,
            "units",
        )
        return "break"

    def _widget_is_in_metadata_area(
        self,
        widget: Optional[tk.Widget],
    ) -> bool:
        """Return True when a widget lives inside the metadata scroller."""
        current = widget

        while current is not None:
            if current in {
                self.metadata_canvas,
                self.metadata_body,
            }:
                return True

            parent_name = current.winfo_parent()

            if not parent_name:
                break

            try:
                current = current.nametowidget(
                    parent_name
                )
            except KeyError:
                break

        return False

    # ------------------------------------------------------------------
    # Site setup
    # ------------------------------------------------------------------

    def _require_site_id(self) -> str:
        site_id = self.metadata_store.get_site_id()

        if site_id:
            return site_id

        site_id = simpledialog.askstring(
            "CoCANoT Site Setup",
            (
                "Enter the Site ID for this local installation.\n\n"
                "This is stored locally and automatically attached "
                "to metadata records."
            ),
            parent=self,
        )

        if site_id is None:
            return ""

        site_id = site_id.strip()

        if not site_id:
            messagebox.showerror(
                "Site ID required",
                "Site ID cannot be blank.",
                parent=self,
            )
            return ""

        return self.metadata_store.set_site_id(
            site_id
        )

    def _change_site(self) -> None:
        value = simpledialog.askstring(
            "Change CoCANoT Site",
            (
                "Enter the Site ID for this local installation.\n\n"
                "Changing sites will clear unresolved Clinical "
                "Assessment IDs in this window."
            ),
            initialvalue=self.site_id,
            parent=self,
        )

        if value is None:
            return

        value = value.strip()

        if not value:
            messagebox.showerror(
                "Site ID required",
                "Site ID cannot be blank.",
                parent=self,
            )
            return

        self.site_id = self.metadata_store.set_site_id(
            value
        )
        self.site_var.set(
            f"Site: {self.site_id}"
        )

        for record in self.records.values():
            metadata = record.get(
                "cocanot_metadata",
                {},
            )
            metadata.pop(
                "Clinical Assessment ID",
                None,
            )
            record["metadata_confirmed"] = False
            record["status"] = self._record_status(
                record
            )
            self._refresh_row(
                self._item_id_for_record(record)
            )

    def _item_id_for_record(
        self,
        target: Dict[str, object],
    ) -> str:
        for item_id, record in self.records.items():
            if record is target:
                return item_id

        return ""

    # ------------------------------------------------------------------
    # Basic UI helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _add_entry(
        parent: tk.Widget,
        row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
        *,
        columnspan: int = 1,
    ) -> ttk.Entry:
        ttk.Label(
            parent,
            text=label,
        ).grid(
            row=row,
            column=column,
            sticky="w",
            pady=(4, 2),
        )

        widget = ttk.Entry(
            parent,
            textvariable=variable,
        )
        widget.grid(
            row=row,
            column=column + 1,
            columnspan=columnspan,
            sticky="ew",
            padx=(6, 14),
            pady=(4, 2),
        )
        return widget

    @staticmethod
    def _add_combo(
        parent: tk.Widget,
        row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
        values: tuple[str, ...],
    ) -> ttk.Combobox:
        ttk.Label(
            parent,
            text=label,
        ).grid(
            row=row,
            column=column,
            sticky="w",
            pady=(4, 2),
        )

        widget = ttk.Combobox(
            parent,
            textvariable=variable,
            values=values,
            state="readonly",
        )
        widget.grid(
            row=row,
            column=column + 1,
            sticky="ew",
            padx=(6, 14),
            pady=(4, 2),
        )
        return widget

    def _clear_frame(
        self,
        frame: tk.Widget,
    ) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _show_help(
        self,
        rule: Dict[str, object],
    ) -> None:
        help_text = str(
            rule.get("help_text") or ""
        ).strip()

        if help_text:
            messagebox.showinfo(
                str(rule["field_name"]),
                help_text,
                parent=self,
            )

    # ------------------------------------------------------------------
    # Main interface
    # ------------------------------------------------------------------

    def _build_interface(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1, minsize=190)
        root.rowconfigure(4, weight=3, minsize=420)

        header = ttk.Frame(root)
        header.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="Imaging Metadata & BIDS Review",
            font=("", 18, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        site = ttk.Frame(header)
        site.grid(
            row=0,
            column=1,
            sticky="e",
        )
        ttk.Label(
            site,
            textvariable=self.site_var,
        ).pack(side="left")
        ttk.Button(
            site,
            text="Change Site",
            command=self._change_site,
        ).pack(
            side="left",
            padx=(8, 0),
        )
        ttk.Button(
            site,
            text="Back to Imaging",
            command=self._close_page,
        ).pack(
            side="left",
            padx=(8, 0),
        )

        ttk.Label(
            root,
            text=(
                "CoCANoT fields below come from the active machine-readable "
                "dictionary. Project and Session ID are used only for dataset "
                "organization and can be applied to multiple selected images."
            ),
            wraplength=1500,
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=(4, 10),
        )

        table = ttk.Frame(root)
        table.grid(
            row=2,
            column=0,
            sticky="nsew",
        )
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)

        columns = (
            "include",
            "file",
            "project",
            "patient",
            "image_id",
            "surgery",
            "modality",
        )

        self.tree = ttk.Treeview(
            table,
            columns=columns,
            show="headings",
            selectmode="extended",
            height=10,
        )

        headings = {
            "include": "Include",
            "file": "File Name",
            "project": "Project",
            "patient": "CoCANoT Patient ID",
            "image_id": "Image Session ID",
            "surgery": "Surgery ID",
            "modality": "Imaging Modality",
        }

        widths = {
            "include": 70,
            "file": 420,
            "project": 170,
            "patient": 180,
            "image_id": 160,
            "surgery": 150,
            "modality": 150,
        }

        for column in columns:
            self.tree.heading(
                column,
                text=headings[column],
            )
            self.tree.column(
                column,
                width=widths[column],
                anchor="w",
            )

        self.tree.grid(
            row=0,
            column=0,
            sticky="nsew",
        )
        self.tree.bind(
            "<Double-1>",
            self._toggle_at_pointer,
        )
        self.tree.bind(
            "<<TreeviewSelect>>",
            self._selected_record_changed,
        )

        y_scroll = ttk.Scrollbar(
            table,
            orient="vertical",
            command=self.tree.yview,
        )
        y_scroll.grid(
            row=0,
            column=1,
            sticky="ns",
        )

        x_scroll = ttk.Scrollbar(
            table,
            orient="horizontal",
            command=self.tree.xview,
        )
        x_scroll.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        self.tree.configure(
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )
        self.selection = ExtendedSelectionController(
            self.tree
        )

        self.existing_metadata_frame = ttk.LabelFrame(
            root,
            text="Existing Metadata",
            padding=10,
        )
        self.existing_metadata_frame.grid(
            row=3,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )
        self.existing_metadata_frame.columnconfigure(
            0,
            weight=1,
        )

        self.existing_metadata_text = tk.Text(
            self.existing_metadata_frame,
            height=7,
            wrap="word",
            state="disabled",
        )
        self.existing_metadata_text.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        self.existing_metadata_frame.grid_remove()

        shell = ttk.Frame(root)
        shell.grid(
            row=4,
            column=0,
            sticky="nsew",
            pady=(10, 0),
        )
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        self.metadata_canvas = tk.Canvas(
            shell,
            highlightthickness=0,
        )
        self.metadata_canvas.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        scroll = ttk.Scrollbar(
            shell,
            orient="vertical",
            command=self.metadata_canvas.yview,
        )
        scroll.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        self.metadata_canvas.configure(
            yscrollcommand=scroll.set,
        )

        self.metadata_body = ttk.Frame(
            self.metadata_canvas
        )
        self.metadata_window_id = (
            self.metadata_canvas.create_window(
                (0, 0),
                window=self.metadata_body,
                anchor="nw",
            )
        )

        self.metadata_body.bind(
            "<Configure>",
            lambda _event: (
                self.metadata_canvas.configure(
                    scrollregion=(
                        self.metadata_canvas.bbox("all")
                    )
                )
            ),
        )

        self.metadata_canvas.bind(
            "<Configure>",
            lambda event: (
                self.metadata_canvas.itemconfigure(
                    self.metadata_window_id,
                    width=event.width,
                )
            ),
        )

        # Let users scroll this form naturally with a trackpad or mouse wheel.
        # The event is bound to this window and only moves the metadata canvas
        # when the pointer is actually over the scrollable metadata area.
        self.bind(
            "<MouseWheel>",
            self._scroll_metadata_with_wheel,
            add="+",
        )
        self.bind(
            "<Button-4>",
            self._scroll_metadata_with_wheel,
            add="+",
        )
        self.bind(
            "<Button-5>",
            self._scroll_metadata_with_wheel,
            add="+",
        )

        self.metadata_body.columnconfigure(
            0,
            weight=1,
        )

        cocanot = ttk.LabelFrame(
            self.metadata_body,
            text="CoCANoT Imaging Metadata",
            padding=12,
        )
        cocanot.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        cocanot.columnconfigure(0, weight=1)

        ttk.Label(
            cocanot,
            text=(
                "Requiredness, field type, allowed values, conditional fields, "
                "visible prompts, and help text come from MR Imaging. "
                "Clinical Assessment ID is assigned automatically later."
            ),
            wraplength=1450,
        ).grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 8),
        )

        self.cocanot_form = ttk.Frame(cocanot)
        self.cocanot_form.grid(
            row=1,
            column=0,
            sticky="ew",
        )
        self.cocanot_form.columnconfigure(
            0,
            weight=1,
        )

        self._build_cocanot_form()

        bids = ttk.LabelFrame(
            self.metadata_body,
            text="Dataset Organization",
            padding=12,
        )
        bids.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )
        bids.columnconfigure(1, weight=1)
        bids.columnconfigure(3, weight=1)

        self._add_entry(
            bids,
            0,
            0,
            "Project *",
            self.project_var,
        )

        self._add_entry(
            bids,
            0,
            2,
            "Session ID",
            self.session_var,
        )

        self._add_entry(
            bids,
            1,
            0,
            "Project Description",
            self.project_description_var,
            columnspan=3,
        )

        ttk.Label(
            bids,
            text=(
                "Project is required for output organization. Project Description "
                "and Session ID are optional. The BIDS subject label is derived "
                "internally from CoCANoT Patient ID."
            ),
            wraplength=1450,
        ).grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(8, 0),
        )


        actions = ttk.Frame(
            self.metadata_body
        )
        actions.grid(
            row=2,
            column=0,
            sticky="ew",
            pady=(12, 18),
        )

        ttk.Button(
            actions,
            text="Include Selected",
            command=lambda: self._set_included(
                True
            ),
        ).pack(side="left")

        ttk.Button(
            actions,
            text="Exclude Selected",
            command=lambda: self._set_included(
                False
            ),
        ).pack(
            side="left",
            padx=(6, 0),
        )

        ttk.Button(
            actions,
            text="Apply to Selected",
            command=self._apply_to_selected,
        ).pack(
            side="left",
            padx=(18, 0),
        )

        ttk.Button(
            actions,
            text="Review Metadata & Convert",
            command=self._review_and_convert,
        ).pack(side="right")

    # ------------------------------------------------------------------
    # Dictionary-driven CoCANoT form
    # ------------------------------------------------------------------

    def _build_cocanot_form(self) -> None:
        row_index = 0

        for rule in self.metadata_rules:
            if rule["system_generated"]:
                continue

            frame = ttk.Frame(
                self.cocanot_form
            )
            frame.grid(
                row=row_index,
                column=0,
                sticky="ew",
                pady=(3, 3),
            )
            frame.columnconfigure(
                1,
                weight=1,
            )
            row_index += 1

            if rule["required"]:
                marker = " *"
            elif rule.get("required_if_field"):
                marker = " * when applicable"
            else:
                marker = ""

            ttk.Label(
                frame,
                text=str(
                    rule["ui_prompt"]
                ) + marker,
                wraplength=430,
            ).grid(
                row=0,
                column=0,
                sticky="nw",
                padx=(0, 8),
            )

            help_text = str(
                rule.get("help_text") or ""
            ).strip()

            if help_text:
                ttk.Button(
                    frame,
                    text="?",
                    width=3,
                    command=lambda item=rule: (
                        self._show_help(item)
                    ),
                ).grid(
                    row=0,
                    column=2,
                    sticky="n",
                    padx=(6, 0),
                )

            field_name = str(
                rule["field_name"]
            )
            input_type = str(
                rule["input_type"]
            )

            control: Dict[str, object] = {
                "frame": frame,
                "rule": rule,
            }

            if input_type in {
                "identifier",
                "free_text",
            }:
                variable = tk.StringVar()
                widget = ttk.Entry(
                    frame,
                    textvariable=variable,
                )
                widget.grid(
                    row=0,
                    column=1,
                    sticky="ew",
                )
                variable.trace_add(
                    "write",
                    lambda *_args: (
                        self._metadata_value_changed()
                    ),
                )

                control["variable"] = variable
                control["widget"] = widget

            elif input_type == "single_select":
                variable = tk.StringVar()
                widget = ttk.Combobox(
                    frame,
                    textvariable=variable,
                    values=tuple(
                        rule.get(
                            "allowed_values",
                            [],
                        )
                    ),
                    state="readonly",
                )
                widget.grid(
                    row=0,
                    column=1,
                    sticky="ew",
                )
                widget.bind(
                    "<<ComboboxSelected>>",
                    self._metadata_selection_changed,
                )

                control["variable"] = variable
                control["widget"] = widget

            elif input_type == "multi_select":
                container = ttk.Frame(frame)
                container.grid(
                    row=0,
                    column=1,
                    sticky="ew",
                )
                container.columnconfigure(
                    0,
                    weight=1,
                )

                values = list(
                    rule.get(
                        "allowed_values",
                        [],
                    )
                )

                listbox = tk.Listbox(
                    container,
                    selectmode="extended",
                    exportselection=False,
                    height=min(
                        max(len(values), 4),
                        7,
                    ),
                )
                listbox.grid(
                    row=0,
                    column=0,
                    sticky="ew",
                )

                for value in values:
                    listbox.insert(
                        "end",
                        value,
                    )

                listbox.bind(
                    "<<ListboxSelect>>",
                    self._metadata_selection_changed,
                )

                bar = ttk.Scrollbar(
                    container,
                    orient="vertical",
                    command=listbox.yview,
                )
                bar.grid(
                    row=0,
                    column=1,
                    sticky="ns",
                )
                listbox.configure(
                    yscrollcommand=bar.set,
                )

                control["widget"] = listbox

            self.metadata_controls[
                field_name
            ] = control

    def _metadata_selection_changed(
        self,
        _event: Optional[tk.Event] = None,
    ) -> None:
        self._metadata_value_changed()

    def _metadata_value_changed(self) -> None:
        self._refresh_conditional_fields()

    def _refresh_conditional_fields(
        self,
    ) -> None:
        values = self._current_cocanot_metadata()

        for control in (
            self.metadata_controls.values()
        ):
            rule = control["rule"]
            parent = rule.get(
                "required_if_field"
            )
            frame = control["frame"]

            if not parent:
                frame.grid()
                continue

            applies = condition_matches(
                values,
                parent,
                rule["required_if_operator"],
                rule["required_if_value"],
            )

            if applies:
                frame.grid()
            else:
                frame.grid_remove()

    def _current_cocanot_metadata(
        self,
    ) -> Dict[str, object]:
        values: Dict[str, object] = {}

        for rule in self.metadata_rules:
            field_name = str(
                rule["field_name"]
            )

            if rule["system_generated"]:
                continue

            control = self.metadata_controls[
                field_name
            ]

            if rule["input_type"] == "multi_select":
                listbox = control["widget"]
                values[field_name] = [
                    str(listbox.get(index))
                    for index in listbox.curselection()
                ]
            else:
                values[field_name] = (
                    control["variable"].get().strip()
                )

        return values

    # ------------------------------------------------------------------
    # Existing BIDS records
    # ------------------------------------------------------------------

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as file:
            while True:
                chunk = file.read(1024 * 1024)

                if not chunk:
                    break

                digest.update(chunk)

        return digest.hexdigest()

    def _index_existing_bids(
        self,
    ) -> Dict[int, list[Dict[str, object]]]:
        index: Dict[
            int,
            list[Dict[str, object]],
        ] = {}

        if not self.output_dir.exists():
            return index

        for path in self.output_dir.rglob("*"):
            if not is_nifti(path):
                continue

            try:
                file_size = path.stat().st_size
            except OSError:
                continue

            json_path = matching_json_path(path)
            metadata: Dict[str, object] = {}

            if json_path is not None:
                try:
                    loaded = json.loads(
                        json_path.read_text(
                            encoding="utf-8"
                        )
                    )
                except (
                    OSError,
                    json.JSONDecodeError,
                ):
                    loaded = {}

                if type(loaded) is dict:
                    metadata = loaded

            index.setdefault(
                file_size,
                [],
            ).append({
                "nifti_path": str(
                    path.resolve()
                ),
                "json_path": (
                    str(json_path.resolve())
                    if json_path is not None
                    else ""
                ),
                "metadata": metadata,
                "sha256": "",
            })

        return index

    def _existing_export(
        self,
        path: Path,
    ) -> Optional[Dict[str, object]]:
        try:
            file_size = path.stat().st_size
        except OSError:
            return None

        candidates = (
            self.existing_bids_by_size.get(
                file_size,
                [],
            )
        )

        if not candidates:
            return None

        try:
            source_hash = self._file_hash(
                path
            )
        except OSError:
            return None

        for candidate in candidates:
            candidate_hash = str(
                candidate.get(
                    "sha256"
                )
                or ""
            )

            if not candidate_hash:
                try:
                    candidate_hash = (
                        self._file_hash(
                            Path(
                                str(
                                    candidate[
                                        "nifti_path"
                                    ]
                                )
                            )
                        )
                    )
                except OSError:
                    continue

                candidate[
                    "sha256"
                ] = candidate_hash

            if candidate_hash == source_hash:
                return candidate

        return None

    def _show_existing_metadata(
        self,
        existing: Optional[Dict[str, object]],
    ) -> None:
        if existing is None:
            self.existing_metadata_frame.grid_remove()
            return

        metadata = existing.get(
            "metadata",
            {},
        )
        path = Path(
            str(existing["nifti_path"])
        )

        try:
            shown_path = path.relative_to(
                self.output_dir
            )
        except ValueError:
            shown_path = path

        lines = [
            f"Output: {shown_path}",
        ]

        fields = (
            ("CoCANoTSiteID", "Site"),
            ("CoCANoTPatientID", "CoCANoT Patient ID"),
            ("ClinicalAssessmentID", "Clinical Assessment ID"),
            ("ImageID", "Image Session ID"),
            ("SurgeryID", "Surgery ID"),
            ("ImagingModality", "Imaging Modality"),
            ("PurposeOfImaging", "Purpose of Imaging"),
            ("ImagingFindings", "Imaging Findings"),
        )

        for key, label in fields:
            value = metadata.get(key)

            if value in (
                None,
                "",
                [],
            ):
                continue

            if type(value) is list:
                shown = ", ".join(
                    str(item)
                    for item in value
                )
            else:
                shown = str(value)

            lines.append(
                f"{label}: {shown}"
            )

        self.existing_metadata_text.configure(
            state="normal"
        )
        self.existing_metadata_text.delete(
            "1.0",
            "end",
        )
        self.existing_metadata_text.insert(
            "1.0",
            "\n".join(lines),
        )
        self.existing_metadata_text.configure(
            state="disabled"
        )
        self.existing_metadata_frame.grid()


    # ------------------------------------------------------------------
    # Per-image records
    # ------------------------------------------------------------------

    def _load_files(self) -> None:
        for index, path in enumerate(
            self.accepted_files,
            start=1,
        ):
            item_id = f"image-{index}"
            existing_export = (
                self._existing_export(path)
            )

            project = ""
            project_description = ""
            session_id = ""
            participant_id = ""
            cocanot_metadata: Dict[str, object] = {}

            if existing_export is not None:
                existing_path = Path(
                    str(
                        existing_export[
                            "nifti_path"
                        ]
                    )
                )
                existing_metadata = dict(
                    existing_export.get(
                        "metadata",
                        {},
                    )
                )

                try:
                    relative = existing_path.relative_to(
                        self.output_dir
                    )
                    parts = relative.parts

                    if parts:
                        project = parts[0]

                    session_part = next(
                        (
                            part
                            for part in parts
                            if part.startswith("ses-")
                        ),
                        "",
                    )
                    if session_part:
                        session_id = session_part[4:]
                except ValueError:
                    pass

                participant_id = str(
                    existing_metadata.get(
                        "CoCANoTPatientID"
                    )
                    or ""
                )

                cocanot_metadata = {
                    "CoCANoT Patient ID": participant_id,
                    "Clinical Assessment ID": str(
                        existing_metadata.get(
                            "ClinicalAssessmentID"
                        )
                        or ""
                    ),
                    "Image ID": str(
                        existing_metadata.get(
                            "ImageID"
                        )
                        or ""
                    ),
                    "Surgery ID": str(
                        existing_metadata.get(
                            "SurgeryID"
                        )
                        or ""
                    ),
                    "Imaging Modality": str(
                        existing_metadata.get(
                            "ImagingModality"
                        )
                        or ""
                    ),
                    "Purpose of Imaging (multiselect)": list(
                        existing_metadata.get(
                            "PurposeOfImaging"
                        )
                        or []
                    ),
                    "Timing Relative to Surgery": str(
                        existing_metadata.get(
                            "TimingRelativeToSurgery"
                        )
                        or ""
                    ),
                    "Imaging Findings (multiselect)": list(
                        existing_metadata.get(
                            "ImagingFindings"
                        )
                        or []
                    ),
                    "Other Purpose of Imaging (if applicable; free text)": str(
                        existing_metadata.get(
                            "OtherPurposeOfImaging"
                        )
                        or ""
                    ),
                    "Other Imaging Findings (if applicable; free text)": str(
                        existing_metadata.get(
                            "OtherImagingFindings"
                        )
                        or ""
                    ),
                    "Comments (free text)": str(
                        existing_metadata.get(
                            "Comments"
                        )
                        or ""
                    ),
                }

                if (
                    cocanot_metadata[
                        "Imaging Modality"
                    ]
                    == "MRI"
                ):
                    sequence_value = str(
                        existing_metadata.get(
                            "MRISequence"
                        )
                        or ""
                    ).strip()

                    for rule in self.metadata_rules:
                        field_name = str(
                            rule.get(
                                "field_name",
                                "",
                            )
                        )

                        if field_name not in MRI_SEQUENCE_FIELDS:
                            continue

                        if rule.get(
                            "input_type"
                        ) == "multi_select":
                            cocanot_metadata[
                                field_name
                            ] = (
                                [sequence_value]
                                if sequence_value
                                else []
                            )
                        else:
                            cocanot_metadata[
                                field_name
                            ] = sequence_value

                        break

                dataset_description = (
                    self.output_dir
                    / project
                    / "dataset_description.json"
                )

                if dataset_description.exists():
                    try:
                        dataset_payload = json.loads(
                            dataset_description.read_text(
                                encoding="utf-8"
                            )
                        )
                    except (
                        OSError,
                        json.JSONDecodeError,
                    ):
                        dataset_payload = {}

                    if type(dataset_payload) is dict:
                        project_description = str(
                            dataset_payload.get(
                                "Description"
                            )
                            or ""
                        )

            self.records[item_id] = {
                "nifti_path": str(
                    path.resolve()
                ),
                "source_label": path.name,
                "include": (
                    "No"
                    if existing_export is not None
                    else "Yes"
                ),
                "project": project,
                "project_description": project_description,
                "session_id": session_id,
                "participant_id": (
                    self._derive_bids_subject(
                        participant_id
                    )
                ),
                "cocanot_metadata": cocanot_metadata,
                "datatype": "",
                "suffix": "",
                "existing_export": existing_export,
                "metadata_confirmed": False,
                "status": (
                    "Already exported"
                    if existing_export is not None
                    else "Missing metadata"
                ),
            }

            self._refresh_row(
                item_id
            )

        if self.records:
            first = next(
                iter(self.records)
            )
            self.tree.selection_set(
                first
            )
            self.tree.focus(first)
            self.selection.anchor = first
            self._selected_record_changed()


    def _refresh_row(
        self,
        item_id: str,
    ) -> None:
        if not item_id:
            return

        record = self.records[item_id]
        metadata = record.get(
            "cocanot_metadata",
            {},
        )

        values = (
            record["include"],
            record["source_label"],
            record["project"],
            metadata.get(
                "CoCANoT Patient ID",
                "",
            ),
            metadata.get(
                "Image ID",
                "",
            ),
            metadata.get(
                "Surgery ID",
                "",
            ),
            metadata.get(
                "Imaging Modality",
                "",
            ),
        )

        if self.tree.exists(item_id):
            self.tree.item(
                item_id,
                values=values,
            )
        else:
            self.tree.insert(
                "",
                "end",
                iid=item_id,
                values=values,
            )


    def _selected_record_changed(
        self,
        _event: Optional[tk.Event] = None,
    ) -> None:
        selected = list(
            self.tree.selection()
        )

        if len(selected) != 1:
            return

        item_id = selected[0]

        record = self.records[item_id]

        self._load_record_into_form(
            record
        )
        self._show_existing_metadata(
            record.get("existing_export")
        )

    def _load_record_into_form(
        self,
        record: Dict[str, object],
    ) -> None:
        metadata = dict(
            record.get(
                "cocanot_metadata",
                {},
            )
        )

        self.project_var.set(
            str(record.get("project") or "")
        )
        self.project_description_var.set(
            str(
                record.get(
                    "project_description"
                )
                or ""
            )
        )
        self.session_var.set(
            str(record.get("session_id") or "")
        )

        for rule in self.metadata_rules:
            if rule["system_generated"]:
                continue

            field_name = rule["field_name"]
            control = self.metadata_controls[
                field_name
            ]
            value = metadata.get(
                field_name
            )

            if rule["input_type"] == "multi_select":
                listbox = control["widget"]
                listbox.selection_clear(
                    0,
                    "end",
                )

                selected_values = (
                    value
                    if type(value) is list
                    else []
                )

                for index in range(
                    listbox.size()
                ):
                    if (
                        listbox.get(index)
                        in selected_values
                    ):
                        listbox.selection_set(
                            index
                        )
            else:
                control[
                    "variable"
                ].set(
                    ""
                    if value is None
                    else str(value)
                )

        self._refresh_conditional_fields()


    @staticmethod
    def _derive_bids_subject(
        patient_id: str,
    ) -> str:
        return re.sub(
            r"[^A-Za-z0-9+]",
            "",
            patient_id,
        )

    def _current_values(
        self,
    ) -> Dict[str, object]:
        metadata = (
            self._current_cocanot_metadata()
        )

        patient_id = str(
            metadata.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()

        modality = str(
            metadata.get(
                "Imaging Modality"
            )
            or ""
        ).strip()

        sequence = imaging_sequence_value(
            metadata
        )

        if modality == "MRI":
            datatype, suffix = (
                self.MRI_SEQUENCE_MAP.get(
                    sequence,
                    ("", ""),
                )
            )
        elif modality == "CT":
            datatype, suffix = (
                "ct",
                "ct",
            )
        else:
            datatype, suffix = (
                "",
                "",
            )

        return {
            "project": (
                self.project_var.get().strip()
            ),
            "project_description": (
                self.project_description_var.get().strip()
            ),
            "participant_id": (
                self._derive_bids_subject(
                    patient_id
                )
            ),
            "session_id": (
                self.session_var.get().strip()
            ),
            "cocanot_metadata": metadata,
            "datatype": datatype,
            "suffix": suffix,
            "metadata_confirmed": False,
        }

    def _draft_metadata_for_validation(
        self,
        metadata: Dict[str, object],
    ) -> Dict[str, object]:
        draft = dict(metadata)

        if not draft.get(
            "Clinical Assessment ID"
        ):
            draft[
                "Clinical Assessment ID"
            ] = "PENDING"

        return draft

    def _record_status(
        self,
        record: Dict[str, object],
    ) -> str:
        if record.get("include") != "Yes":
            if record.get("existing_export"):
                return "Already exported"

            return "Excluded"

        if not str(
            record.get("project") or ""
        ).strip():
            return "Missing project"

        metadata = record.get(
            "cocanot_metadata",
            {},
        )

        validation = (
            self.metadata_validator.validate_record(
                "Imaging",
                self._draft_metadata_for_validation(
                    metadata
                ),
            )
        )

        for result in validation["results"]:
            if result["status"] in {
                "invalid",
                "missing_required",
            }:
                return (
                    f"{result['field_name']}: "
                    f"{result['message']}"
                )

        patient_id = str(
            metadata.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()

        if patient_id and not self._derive_bids_subject(
            patient_id
        ):
            return (
                "CoCANoT Patient ID cannot be converted "
                "to a BIDS subject label."
            )

        modality = str(
            metadata.get(
                "Imaging Modality"
            )
            or ""
        ).strip()

        if modality == "MRI":
            sequence = imaging_sequence_value(
                metadata
            )

            if sequence not in (
                self.MRI_SEQUENCE_MAP
            ):
                return "Select one MRI sequence"

        return "Ready for clinical check"

    def _apply_to_selected(
        self,
    ) -> None:
        selected = list(
            self.tree.selection()
        )

        if not selected:
            messagebox.showinfo(
                "No selection",
                "Select one or more images first.",
                parent=self,
            )
            return

        values = self._current_values()

        for item_id in selected:
            record = self.records[
                item_id
            ]

            previous_patient = str(
                record.get(
                    "cocanot_metadata",
                    {},
                ).get(
                    "CoCANoT Patient ID"
                )
                or ""
            ).strip()

            new_patient = str(
                values[
                    "cocanot_metadata"
                ].get(
                    "CoCANoT Patient ID"
                )
                or ""
            ).strip()

            record.update(
                copy.deepcopy(values)
            )
            record["metadata_confirmed"] = False

            if previous_patient != new_patient:
                record[
                    "cocanot_metadata"
                ].pop(
                    "Clinical Assessment ID",
                    None,
                )

            record["status"] = (
                self._record_status(
                    record
                )
            )
            self._refresh_row(
                item_id
            )

        messagebox.showinfo(
            "Metadata applied",
            (
                f"Applied the current metadata to "
                f"{len(selected)} selected image"
                f"{'' if len(selected) == 1 else 's'}."
            ),
            parent=self,
        )

    def _set_included(
        self,
        included: bool,
    ) -> None:
        selected = list(
            self.tree.selection()
        )

        if not selected:
            messagebox.showinfo(
                "No selection",
                "Select one or more images first.",
                parent=self,
            )
            return

        if included:
            existing_count = sum(
                1
                for item_id in selected
                if self.records[item_id].get(
                    "existing_export"
                )
            )

            if existing_count:
                confirmed = messagebox.askyesno(
                    "Existing BIDS record",
                    (
                        f"{existing_count} selected image"
                        f"{'' if existing_count == 1 else 's'} already "
                        "exist in the BIDS output. Include them anyway?"
                    ),
                    parent=self,
                )

                if not confirmed:
                    return

        for item_id in selected:
            self.records[item_id][
                "include"
            ] = (
                "Yes"
                if included
                else "No"
            )
            self.records[item_id][
                "metadata_confirmed"
            ] = False
            self.records[item_id][
                "status"
            ] = self._record_status(
                self.records[item_id]
            )
            self._refresh_row(
                item_id
            )

    def _toggle_at_pointer(
        self,
        event: tk.Event,
    ) -> None:
        item_id = self.tree.identify_row(
            event.y
        )

        if not item_id:
            return

        record = self.records[
            item_id
        ]
        current = record["include"]

        if (
            current == "No"
            and record.get(
                "existing_export"
            )
        ):
            confirmed = messagebox.askyesno(
                "Existing BIDS record",
                (
                    "This image already exists in the BIDS output. "
                    "Include it anyway?"
                ),
                parent=self,
            )

            if not confirmed:
                return

        record[
            "include"
        ] = (
            "No"
            if current == "Yes"
            else "Yes"
        )
        self.records[item_id][
            "metadata_confirmed"
        ] = False
        self.records[item_id][
            "status"
        ] = self._record_status(
            self.records[item_id]
        )
        self._refresh_row(
            item_id
        )

    # ------------------------------------------------------------------
    # Clinical reconciliation
    # ------------------------------------------------------------------

    def _resolve_clinical_assessments(
        self,
        included: list[
            Dict[str, object]
        ],
    ) -> bool:
        patient_ids = sorted({
            str(
                record["cocanot_metadata"].get(
                    "CoCANoT Patient ID"
                )
                or ""
            ).strip()
            for record in included
        })

        choice = review_clinical_batch(
            self,
            self.metadata_store,
            self.site_id,
            patient_ids,
        )

        if choice is None:
            return False

        resolved: Dict[str, str] = {}

        if choice == "upload":
            try:
                resolved = import_clinical_file(
                    self,
                    self.metadata_dictionary,
                    self.metadata_store,
                    self.site_id,
                    set(patient_ids),
                )
            except ValueError as exc:
                messagebox.showerror(
                    "Clinical upload error",
                    str(exc),
                    parent=self,
                )
                return False

            # An upload may intentionally contain only some patients from
            # the current batch. Review any remaining patients individually.
            if not resolved:
                return False

        for patient_id in patient_ids:
            if patient_id in resolved:
                continue

            assessment_id = (
                reconcile_clinical_assessment(
                    self,
                    self.metadata_dictionary,
                    self.metadata_store,
                    self.site_id,
                    patient_id,
                )
            )

            if assessment_id is None:
                return False

            resolved[patient_id] = assessment_id

        for record in included:
            metadata = record[
                "cocanot_metadata"
            ]
            patient_id = str(
                metadata.get(
                    "CoCANoT Patient ID"
                )
                or ""
            ).strip()
            metadata[
                "Clinical Assessment ID"
            ] = resolved[patient_id]

        return True

    # ------------------------------------------------------------------
    # Final validation -> confirmation -> conversion
    # ------------------------------------------------------------------

    def _review_and_convert(
        self,
    ) -> None:
        included = [
            record
            for record in self.records.values()
            if record["include"] == "Yes"
        ]

        if not included:
            messagebox.showerror(
                "Nothing included",
                "Include at least one image.",
                parent=self,
            )
            return

        existing_included = [
            record
            for record in included
            if record.get("existing_export")
        ]

        if existing_included and not self.overwrite:
            messagebox.showerror(
                "Existing BIDS records included",
                (
                    "One or more included images already exist in the "
                    "BIDS output. Exclude them or enable overwrite."
                ),
                parent=self,
            )
            return

        problems = []

        for record in included:
            status = self._record_status(
                record
            )

            if status != "Ready for clinical check":
                problems.append(
                    f"{record['source_label']}: "
                    f"{status}"
                )

        if problems:
            messagebox.showerror(
                "Metadata needs attention",
                "\n".join(
                    problems[:20]
                ),
                parent=self,
            )
            return

        if not self._resolve_clinical_assessments(
            included
        ):
            return

        problems = []

        for record in included:
            validation = (
                self.metadata_validator.validate_record(
                    "Imaging",
                    record["cocanot_metadata"],
                )
            )

            if not validation[
                "passes_automatic_validation"
            ]:
                for result in validation["results"]:
                    if result["status"] in {
                        "invalid",
                        "missing_required",
                    }:
                        problems.append(
                            f"{record['source_label']} — "
                            f"{result['field_name']}: "
                            f"{result['message']}"
                        )
                continue

            record[
                "metadata_validation"
            ] = validation
            record[
                "metadata_rules"
            ] = self.metadata_rules
            record[
                "status"
            ] = "Ready for confirmation"

        if problems:
            messagebox.showerror(
                "Metadata validation failed",
                "\n".join(
                    problems[:20]
                ),
                parent=self,
            )
            return

        for item_id, record in (
            self.records.items()
        ):
            self._refresh_row(item_id)

        MetadataConfirmationWindow(
            self,
            included,
            self.site_id,
            on_confirm=lambda: (
                self._convert_confirmed(
                    included
                )
            ),
        )

    def _convert_confirmed(
        self,
        included: list[
            Dict[str, object]
        ],
    ) -> None:
        for record in included:
            record[
                "metadata_confirmed"
            ] = True

        manifest_path = (
            Path(
                str(
                    included[0][
                        "nifti_path"
                    ]
                )
            ).parent.parent
            / "nifti_bids_manifest.json"
        )

        manifest = {
            "bids_version": "1.11.1",
            "dictionary_version": (
                self.metadata_rules[0].get(
                    "dictionary_version"
                )
            ),
            "site_id": self.site_id,
            "records": [
                {
                    "nifti_path": record[
                        "nifti_path"
                    ],
                    "project": record[
                        "project"
                    ],
                    "project_description": record[
                        "project_description"
                    ],
                    "participant_id": record[
                        "participant_id"
                    ],
                    "session_id": record[
                        "session_id"
                    ],
                    "cocanot_metadata": record[
                        "cocanot_metadata"
                    ],
                    "datatype": record[
                        "datatype"
                    ],
                    "suffix": record[
                        "suffix"
                    ],
                    "metadata_confirmed": True,
                    "defacing_source": (
                        "external"
                        if "external_defaced" in Path(
                            record["nifti_path"]
                        ).parts
                        else "pydeface"
                    ),
                }
                for record in included
            ],
        }

        manifest_path.write_text(
            json.dumps(
                manifest,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        command = [
            sys.executable,
            "-u",
            str(BIDS_CONVERTER_SCRIPT),
            "--manifest",
            str(manifest_path),
            "--output-dir",
            str(self.output_dir),
        ]

        if self.overwrite:
            command.append(
                "--overwrite"
            )

        self.parent_dashboard.run_command(
            command,
            "Imaging BIDS / CoCANoT conversion",
            on_success=self._close_page,
        )


class ImagingDashboard(ttk.Frame):
    def __init__(
        self,
        parent,
        site_id="",
        on_back=None,
        on_review_patients=None,
        initial_view="home",
        processing_return=None,
    ) -> None:
        super().__init__(parent)

        self.site_id = str(site_id or "").strip()
        self.on_back = on_back
        self.on_review_patients = on_review_patients
        self.initial_view = initial_view
        self.processing_return = processing_return

        self.output_queue: Queue[str] = Queue()
        self.running_process: subprocess.Popen[str] | None = None
        self.pipeline_busy = False

        saved = self._read_saved_settings()
        imaging = saved.get("imaging", {})

        saved_inputs = [
            str(Path(path).expanduser())
            for path in imaging.get("input_dirs", [])
            if path
        ]
        self.dicom_input_paths: List[str] = [
            path for path in imaging.get("dicom_input_dirs", saved_inputs) if path
        ]
        self.nifti_input_paths: List[str] = [
            path
            for path in imaging.get(
                "nifti_input_dirs",
                imaging.get("nifti_input_files", []),
            )
            if path
        ]
        self.derivatives_dir_var = tk.StringVar(value=str(imaging.get("derivatives_dir", "")))
        self.bids_output_dir_var = tk.StringVar(value=str(imaging.get("bids_output_dir", "")))
        self.overwrite_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")

        self.after(100, self._process_output_queue)

        if self.initial_view == "processing":
            self._show_processing()
        else:
            self._show_home()

    def _clear_window(self) -> None:
        for child in self.winfo_children():
            child.destroy()

    def _show_home(self) -> None:
        if self.pipeline_busy:
            messagebox.showwarning(
                "Pipeline busy",
                (
                    "Finish or stop the current operation before "
                    "leaving the processing screen."
                ),
                parent=self,
            )
            return

        self._clear_window()

        page = ttk.Frame(
            self,
            padding=(16, 12, 16, 16),
        )
        page.pack(
            fill="both",
            expand=True,
        )
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)

        if self.on_back is not None:
            navigation = ttk.Frame(page)
            navigation.grid(
                row=0,
                column=0,
                sticky="ew",
                pady=(0, 8),
            )

            ttk.Button(
                navigation,
                text="Back",
                command=self._return_to_cocanot,
            ).pack(side="left")

        home = ImagingHome(
            page,
            on_process=self._show_processing,
            on_review_patients=self._open_patient_explorer,
        )
        home.grid(
            row=1,
            column=0,
            sticky="nsew",
        )

    def _show_processing(self) -> None:
        self._clear_window()
        self._build_interface()
        self._refresh_all_input_lists()

    def _leave_processing(self) -> None:
        if self.pipeline_busy:
            messagebox.showwarning(
                "Pipeline busy",
                (
                    "Finish or stop the current operation before "
                    "leaving the processing screen."
                ),
                parent=self,
            )
            return

        if self.processing_return is not None:
            self.processing_return()
            return

        self._show_home()

    def _open_patient_explorer(self) -> None:
        if self.pipeline_busy:
            messagebox.showwarning(
                "Pipeline busy",
                (
                    "Finish or stop the current operation before "
                    "opening Patient Data Review."
                ),
                parent=self,
            )
            return

        if self.on_review_patients is not None:
            self.on_review_patients()
            return

        metadata_dashboard = (
            PROJECT_ROOT
            / "MetadataPipeline"
            / "dashboard.py"
        )

        if not metadata_dashboard.is_file():
            messagebox.showerror(
                "Patient Explorer unavailable",
                f"Could not find:\n{metadata_dashboard}",
                parent=self,
            )
            return

        try:
            subprocess.Popen(
                [
                    sys.executable,
                    str(metadata_dashboard),
                    "--patient-explorer",
                ],
                cwd=str(PROJECT_ROOT),
            )
        except OSError as exc:
            messagebox.showerror(
                "Patient Explorer unavailable",
                str(exc),
                parent=self,
            )

    def _return_to_cocanot(self) -> None:
        if self.pipeline_busy:
            messagebox.showwarning(
                "Pipeline busy",
                (
                    "Finish or stop the current operation before "
                    "leaving Imaging."
                ),
                parent=self,
            )
            return

        if self.on_back is not None:
            self.on_back()

    def _read_saved_settings(self) -> dict:
        try:
            return load_settings_dict()
        except PipelineConfigError as exc:
            messagebox.showwarning("Settings warning", str(exc))
            return {"imaging": {}}

    def _build_interface(self) -> None:
        outer = ttk.Frame(self)
        outer.pack(
            fill="both",
            expand=True,
        )
        outer.columnconfigure(
            0,
            weight=1,
        )
        outer.rowconfigure(
            0,
            weight=1,
        )

        self.main_canvas = tk.Canvas(
            outer,
            highlightthickness=0,
        )
        self.main_canvas.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        main_scroll = ttk.Scrollbar(
            outer,
            orient="vertical",
            command=self.main_canvas.yview,
        )
        main_scroll.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        self.main_canvas.configure(
            yscrollcommand=main_scroll.set,
        )

        root = ttk.Frame(
            self.main_canvas,
            padding=16,
        )
        self.main_window_id = (
            self.main_canvas.create_window(
                (0, 0),
                window=root,
                anchor="nw",
            )
        )
        root.columnconfigure(
            0,
            weight=1,
        )

        root.bind(
            "<Configure>",
            lambda _event: self.main_canvas.configure(
                scrollregion=self.main_canvas.bbox(
                    "all"
                )
            ),
        )
        self.main_canvas.bind(
            "<Configure>",
            lambda event: self.main_canvas.itemconfigure(
                self.main_window_id,
                width=event.width,
            ),
        )

        self.bind(
            "<MouseWheel>",
            self._scroll_main_dashboard,
            add="+",
        )
        self.bind(
            "<Button-4>",
            self._scroll_main_dashboard,
            add="+",
        )
        self.bind(
            "<Button-5>",
            self._scroll_main_dashboard,
            add="+",
        )

        ttk.Label(
            root,
            text="Imaging DeID Dashboard",
            font=("", 22, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Button(
            root,
            text="Back",
            command=self._leave_processing,
        ).grid(
            row=0,
            column=1,
            sticky="e",
            padx=(12, 0),
        )

        ttk.Label(
            root,
            text=(
                "Select DICOM or NIfTI files and folders, prepare NIfTI inputs, "
                "scrub headers, deface, review, and convert accepted files to BIDS."
            ),
            wraplength=1100,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(4, 12),
        )

        folders = ttk.LabelFrame(
            root,
            text="Source and output folders",
            padding=12,
        )
        folders.grid(
            row=2,
            column=0,
            sticky="ew",
        )
        folders.columnconfigure(
            0,
            weight=1,
        )

        source_frame = ttk.Frame(
            folders
        )
        source_frame.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 10),
        )
        source_frame.columnconfigure(
            0,
            weight=1,
        )
        source_frame.columnconfigure(
            1,
            weight=1,
        )

        (
            self.dicom_input_list,
            self.dicom_input_selection,
            self.add_dicom_files_button,
            self.add_dicom_folders_button,
            self.remove_dicom_button,
        ) = self._build_input_panel(
            source_frame,
            column=0,
            title="DICOM sources",
            add_file_text="Add DICOM Files…",
            add_file_command=self._add_dicom_files,
            add_folder_text="Add DICOM Folders…",
            add_folder_command=self._add_dicom_folders,
            remove_command=lambda: self._remove_selected_inputs(
                self.dicom_input_list,
                self.dicom_input_paths,
            ),
        )

        (
            self.nifti_input_list,
            self.nifti_input_selection,
            self.add_nifti_files_button,
            self.add_nifti_folders_button,
            self.remove_nifti_button,
        ) = self._build_input_panel(
            source_frame,
            column=1,
            title="NIfTI sources",
            add_file_text="Add NIfTI Files…",
            add_file_command=self._add_nifti_files,
            add_folder_text="Add NIfTI Folders…",
            add_folder_command=self._add_nifti_folders,
            remove_command=lambda: self._remove_selected_inputs(
                self.nifti_input_list,
                self.nifti_input_paths,
            ),
        )

        self.raw_dicom_tree = self._build_raw_file_viewer(
            source_frame,
            row=1,
            column=0,
            title="Raw DICOM Files",
        )
        self.raw_nifti_tree = self._build_raw_file_viewer(
            source_frame,
            row=1,
            column=1,
            title="Raw NIfTI Files",
        )

        self.derivatives_selector = FolderSelector(
            folders,
            "Derivatives output folder",
            self.derivatives_dir_var,
            "Select the imaging derivatives output folder",
            PROJECT_ROOT,
        )
        self.derivatives_selector.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(0, 4),
        )

        ttk.Label(
            folders,
            text=(
                "The dashboard creates converted_nifti, scrubbed_header, "
                "scrubbed_defaced, logs, and imaging_review_state.json inside this folder."
            ),
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=(0, 10),
        )

        self.bids_selector = FolderSelector(
            folders,
            "BIDS output folder",
            self.bids_output_dir_var,
            "Select the imaging BIDS output folder",
            PROJECT_ROOT,
        )
        self.bids_selector.grid(
            row=3,
            column=0,
            sticky="ew",
        )

        operations = ttk.LabelFrame(
            root,
            text="Pipeline Operations",
            padding=12,
        )
        operations.grid(
            row=3,
            column=0,
            sticky="ew",
            pady=(12, 0),
        )

        for index in range(5):
            operations.columnconfigure(
                index,
                weight=1,
            )

        self.prepare_button = ttk.Button(
            operations,
            text="1. Prepare NIfTI",
            command=self._prepare_nifti,
        )
        self.prepare_button.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(0, 5),
        )

        self.scrub_button = ttk.Button(
            operations,
            text="2. Scrub Headers",
            command=self._run_scrubber,
        )
        self.scrub_button.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=5,
        )

        self.deface_button = ttk.Button(
            operations,
            text="3. Deface",
            command=self._run_defacer,
        )
        self.deface_button.grid(
            row=0,
            column=2,
            sticky="ew",
            padx=5,
        )

        self.review_button = ttk.Button(
            operations,
            text="4. Review",
            command=self._open_review,
        )
        self.review_button.grid(
            row=0,
            column=3,
            sticky="ew",
            padx=5,
        )

        self.bids_button = ttk.Button(
            operations,
            text="5. Metadata & BIDS",
            command=self._open_bids,
        )
        self.bids_button.grid(
            row=0,
            column=4,
            sticky="ew",
            padx=(5, 0),
        )

        self.stop_button = ttk.Button(
            operations,
            text="Stop Current Operation",
            command=self._stop_current_operation,
            state="disabled",
        )
        self.stop_button.grid(
            row=1,
            column=0,
            columnspan=5,
            sticky="ew",
            pady=(8, 0),
        )

        self.overwrite_checkbox = ttk.Checkbutton(
            operations,
            text="Overwrite existing stage outputs or exact BIDS outputs",
            variable=self.overwrite_var,
        )
        self.overwrite_checkbox.grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(8, 0),
        )

        self.save_settings_button = ttk.Button(
            operations,
            text="Save Folder Settings",
            command=self._save_folder_settings,
        )
        self.save_settings_button.grid(
            row=2,
            column=4,
            sticky="e",
            pady=(8, 0),
        )

        log_frame = ttk.LabelFrame(
            root,
            text="Pipeline Log",
            padding=8,
        )
        log_frame.grid(
            row=4,
            column=0,
            sticky="ew",
            pady=(10, 10),
        )
        log_frame.columnconfigure(
            0,
            weight=1,
        )

        ttk.Label(
            log_frame,
            textvariable=self.status_var,
        ).grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 4),
        )

        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            height=12,
            state="disabled",
        )
        self.log_text.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        scroll = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log_text.yview,
        )
        scroll.grid(
            row=1,
            column=1,
            sticky="ns",
        )
        self.log_text.configure(
            yscrollcommand=scroll.set,
        )

        self._append_log(
            f"Dashboard ready. Settings file: {get_settings_path()}"
        )

    def _scroll_main_dashboard(
        self,
        event: tk.Event,
    ) -> Optional[str]:
        pointer = self.winfo_containing(
            self.winfo_pointerx(),
            self.winfo_pointery(),
        )

        if pointer in {
            self.dicom_input_list,
            self.nifti_input_list,
            self.raw_dicom_tree,
            self.raw_nifti_tree,
            self.log_text,
        }:
            return None

        if getattr(
            event,
            "num",
            None,
        ) == 4:
            units = -3
        elif getattr(
            event,
            "num",
            None,
        ) == 5:
            units = 3
        else:
            delta = getattr(
                event,
                "delta",
                0,
            )

            if delta == 0:
                return None

            if abs(delta) >= 120:
                units = -int(
                    delta / 120
                ) * 3
            else:
                units = (
                    -1
                    if delta > 0
                    else 1
                )

        self.main_canvas.yview_scroll(
            units,
            "units",
        )
        return "break"

    def _build_input_panel(
        self,
        parent: tk.Widget,
        column: int,
        title: str,
        add_file_text: str,
        add_file_command: Callable[[], None],
        add_folder_text: str,
        add_folder_command: Callable[[], None],
        remove_command: Callable[[], None],
    ) -> tuple[
        tk.Listbox,
        ExtendedSelectionController,
        ttk.Button,
        ttk.Button,
        ttk.Button,
    ]:
        panel = ttk.LabelFrame(
            parent,
            text=title,
            padding=8,
        )
        panel.grid(
            row=0,
            column=column,
            sticky="nsew",
            padx=(
                (0, 5)
                if column == 0
                else (5, 0)
            ),
        )
        panel.columnconfigure(
            0,
            weight=1,
        )

        listbox = tk.Listbox(
            panel,
            height=6,
            selectmode="extended",
            exportselection=False,
        )
        listbox.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        selection = ExtendedSelectionController(
            listbox
        )

        buttons = ttk.Frame(panel)
        buttons.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(6, 0),
        )

        add_file_button = ttk.Button(
            buttons,
            text=add_file_text,
            command=add_file_command,
        )
        add_file_button.pack(
            side="left",
        )

        add_folder_button = ttk.Button(
            buttons,
            text=add_folder_text,
            command=add_folder_command,
        )
        add_folder_button.pack(
            side="left",
            padx=(6, 0),
        )

        remove_button = ttk.Button(
            buttons,
            text="Remove Selected",
            command=remove_command,
        )
        remove_button.pack(
            side="right",
        )

        return (
            listbox,
            selection,
            add_file_button,
            add_folder_button,
            remove_button,
        )

    def _build_raw_file_viewer(
        self,
        parent: tk.Widget,
        row: int,
        column: int,
        title: str,
    ) -> ttk.Treeview:
        panel = ttk.LabelFrame(
            parent,
            text=title,
            padding=8,
        )
        panel.grid(
            row=row,
            column=column,
            sticky="nsew",
            padx=(
                (0, 5)
                if column == 0
                else (5, 0)
            ),
            pady=(10, 0),
        )
        panel.columnconfigure(
            0,
            weight=1,
        )

        tree = ttk.Treeview(
            panel,
            columns=(
                "file",
                "source",
            ),
            show="headings",
            height=5,
        )
        tree.heading(
            "file",
            text="File Name",
        )
        tree.heading(
            "source",
            text="Source",
        )
        tree.column(
            "file",
            width=360,
            anchor="w",
        )
        tree.column(
            "source",
            width=220,
            anchor="w",
        )
        tree.grid(
            row=0,
            column=0,
            sticky="ew",
        )

        scroll = ttk.Scrollbar(
            panel,
            orient="vertical",
            command=tree.yview,
        )
        scroll.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        tree.configure(
            yscrollcommand=scroll.set,
        )

        return tree

    @staticmethod
    def _refresh_input_list(
        listbox: tk.Listbox,
        selection: ExtendedSelectionController,
        paths: List[str],
    ) -> None:
        listbox.delete(0, "end")
        for path in paths:
            listbox.insert("end", path)
        if paths:
            listbox.selection_set(0)
            listbox.activate(0)
            selection.anchor = 0

    def _refresh_all_input_lists(self) -> None:
        self._refresh_input_list(
            self.dicom_input_list,
            self.dicom_input_selection,
            self.dicom_input_paths,
        )
        self._refresh_raw_file_viewers()
        self._refresh_input_list(
            self.nifti_input_list,
            self.nifti_input_selection,
            self.nifti_input_paths,
        )
        self._refresh_raw_file_viewers()
        self._refresh_raw_file_viewers()

    def _refresh_raw_file_viewers(
        self,
    ) -> None:
        self._fill_raw_file_viewer(
            self.raw_dicom_tree,
            self._raw_dicom_files(),
        )
        self._fill_raw_file_viewer(
            self.raw_nifti_tree,
            self._raw_nifti_files(),
        )

    @staticmethod
    def _fill_raw_file_viewer(
        tree: ttk.Treeview,
        rows: List[
            tuple[
                str,
                str,
            ]
        ],
    ) -> None:
        for item_id in tree.get_children():
            tree.delete(
                item_id
            )

        for index, (
            file_name,
            source_name,
        ) in enumerate(
            rows,
            start=1,
        ):
            tree.insert(
                "",
                "end",
                iid=f"file-{index}",
                values=(
                    file_name,
                    source_name,
                ),
            )

    def _raw_dicom_files(
        self,
    ) -> List[
        tuple[
            str,
            str,
        ]
    ]:
        rows = []
        seen = set()

        for source_text in self.dicom_input_paths:
            source = Path(
                source_text
            ).expanduser()

            if source.is_file():
                files = [
                    source
                ]
                source_name = source.parent.name
            elif source.is_dir():
                files = sorted(
                    path
                    for path in source.rglob(
                        "*"
                    )
                    if path.is_file()
                    and not path.name.startswith(
                        "."
                    )
                )
                source_name = source.name
            else:
                continue

            for path in files:
                resolved = str(
                    path.resolve()
                )

                if resolved in seen:
                    continue

                seen.add(
                    resolved
                )
                rows.append(
                    (
                        path.name,
                        source_name,
                    )
                )

        return rows

    def _raw_nifti_files(
        self,
    ) -> List[
        tuple[
            str,
            str,
        ]
    ]:
        rows = []
        seen = set()

        for source_text in self.nifti_input_paths:
            source = Path(
                source_text
            ).expanduser()

            if source.is_file():
                files = (
                    [source]
                    if is_nifti(
                        source
                    )
                    else []
                )
                source_name = source.parent.name
            elif source.is_dir():
                files = sorted(
                    path
                    for path in source.rglob(
                        "*"
                    )
                    if is_nifti(
                        path
                    )
                )
                source_name = source.name
            else:
                continue

            for path in files:
                resolved = str(
                    path.resolve()
                )

                if resolved in seen:
                    continue

                seen.add(
                    resolved
                )
                rows.append(
                    (
                        path.name,
                        source_name,
                    )
                )

        return rows

    @staticmethod
    def _append_unique_paths(target: List[str], selected: List[str]) -> None:
        existing = set(target)
        for path in selected:
            resolved = str(Path(path).expanduser().resolve())
            if resolved not in existing:
                target.append(resolved)
                existing.add(resolved)

    def _input_initial_dir(
        self,
        paths: List[str],
    ) -> Path:
        if not paths:
            return PROJECT_ROOT

        first = Path(
            paths[0]
        ).expanduser()

        if first.is_dir():
            return first

        return first.parent

    def _add_dicom_files(self) -> None:
        selected = list(
            filedialog.askopenfilenames(
                parent=self,
                title="Add DICOM files",
                initialdir=str(
                    self._input_initial_dir(
                        self.dicom_input_paths
                    )
                ),
                filetypes=(
                    ("DICOM files", "*.dcm"),
                    ("All files", "*"),
                ),
            )
        )
        self._append_unique_paths(
            self.dicom_input_paths,
            selected,
        )
        self._refresh_input_list(
            self.dicom_input_list,
            self.dicom_input_selection,
            self.dicom_input_paths,
        )
        self._refresh_raw_file_viewers()

    def _add_dicom_folders(self) -> None:
        selected = (
            MultiFolderSelectionDialog.ask_folders(
                self,
                "Add DICOM source folders",
                self._input_initial_dir(
                    self.dicom_input_paths
                ),
            )
        )
        self._append_unique_paths(
            self.dicom_input_paths,
            selected,
        )
        self._refresh_input_list(
            self.dicom_input_list,
            self.dicom_input_selection,
            self.dicom_input_paths,
        )
        self._refresh_raw_file_viewers()

    def _add_nifti_files(self) -> None:
        selected = list(
            filedialog.askopenfilenames(
                parent=self,
                title="Add NIfTI files",
                initialdir=str(
                    self._input_initial_dir(
                        self.nifti_input_paths
                    )
                ),
            )
        )

        invalid = [
            path
            for path in selected
            if not is_nifti(
                Path(path)
            )
        ]

        if invalid:
            messagebox.showwarning(
                "Unsupported files skipped",
                (
                    "Only .nii and .nii.gz files can be added. "
                    f"Skipped {len(invalid)} unsupported file"
                    f"{'' if len(invalid) == 1 else 's'}."
                ),
                parent=self,
            )

        selected = [
            path
            for path in selected
            if is_nifti(
                Path(path)
            )
        ]
        self._append_unique_paths(
            self.nifti_input_paths,
            selected,
        )
        self._refresh_input_list(
            self.nifti_input_list,
            self.nifti_input_selection,
            self.nifti_input_paths,
        )
        self._refresh_raw_file_viewers()

    def _add_nifti_folders(self) -> None:
        selected = (
            MultiFolderSelectionDialog.ask_folders(
                self,
                "Add NIfTI source folders",
                self._input_initial_dir(
                    self.nifti_input_paths
                ),
            )
        )
        self._append_unique_paths(
            self.nifti_input_paths,
            selected,
        )
        self._refresh_input_list(
            self.nifti_input_list,
            self.nifti_input_selection,
            self.nifti_input_paths,
        )
        self._refresh_raw_file_viewers()

    def _remove_selected_inputs(self, listbox: tk.Listbox, paths: List[str]) -> None:
        for index in reversed(listbox.curselection()):
            del paths[index]
        self._refresh_all_input_lists()

    def _selected_settings_dict(self) -> dict:
        config_inputs = []

        for source_text in (
            self.dicom_input_paths
            + self.nifti_input_paths
        ):
            source = Path(
                source_text
            ).expanduser()

            if source.is_file():
                source = source.parent

            resolved = str(
                source.resolve()
            )

            if resolved not in config_inputs:
                config_inputs.append(
                    resolved
                )

        settings = build_imaging_settings_dict(
            input_dirs=config_inputs,
            derivatives_dir=self.derivatives_dir_var.get().strip(),
            bids_output_dir=self.bids_output_dir_var.get().strip(),
        )
        imaging = settings.setdefault(
            "imaging",
            {},
        )
        imaging[
            "dicom_input_dirs"
        ] = list(
            self.dicom_input_paths
        )
        imaging[
            "nifti_input_dirs"
        ] = list(
            self.nifti_input_paths
        )
        imaging.pop(
            "nifti_input_files",
            None,
        )
        return settings

    def _save_folder_settings(self, show_confirmation: bool = True) -> Optional[ImagingPipelineConfig]:
        if not self.dicom_input_paths and not self.nifti_input_paths:
            messagebox.showerror("Missing inputs", "Add at least one DICOM or NIfTI file/folder.")
            return None
        if not self.derivatives_dir_var.get().strip() or not self.bids_output_dir_var.get().strip():
            messagebox.showerror("Missing folders", "Select derivatives and BIDS output folders.")
            return None

        try:
            save_settings_dict(self._selected_settings_dict())
            config = load_imaging_config()
            self._create_stage_dirs(config)
        except PipelineConfigError as exc:
            messagebox.showerror("Folder settings error", str(exc))
            return None

        if show_confirmation:
            messagebox.showinfo("Settings saved", "Imaging folder settings were saved successfully.")
        return config

    def _require_config(self) -> Optional[ImagingPipelineConfig]:
        return self._save_folder_settings(show_confirmation=False)

    @staticmethod
    def _stage_paths(config: ImagingPipelineConfig) -> dict[str, Path]:
        derivatives = config.imaging.derivatives_dir
        return {
            "converted": derivatives / "converted_nifti",
            "scrubbed": derivatives / "scrubbed_header",
            "defaced": derivatives / "scrubbed_defaced",
            "external_defaced": derivatives / "external_defaced",
            "logs": derivatives / "logs",
            "review_state": derivatives / REVIEW_STATE_FILENAME,
        }

    def _create_stage_dirs(self, config: ImagingPipelineConfig) -> None:
        stages = self._stage_paths(config)
        for name, path in stages.items():
            if name == "review_state":
                path.parent.mkdir(parents=True, exist_ok=True)
            else:
                path.mkdir(parents=True, exist_ok=True)
        config.imaging.bids_output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _verify_script(path: Path, description: str) -> bool:
        if path.is_file():
            return True
        messagebox.showerror("Missing script", f"Could not find the {description}:\n\n{path}")
        return False

    def _prepare_nifti(self) -> None:
        config = self._require_config()
        if config is None:
            return
        stages = self._stage_paths(config)

        if self.dicom_input_paths:
            if not self._verify_script(
                DICOM_CONVERTER_SCRIPT,
                "DICOM converter script",
            ):
                return

            dicom_dirs = []
            dicom_files = []

            for source_text in self.dicom_input_paths:
                source = Path(
                    source_text
                ).expanduser()

                if source.is_file():
                    dicom_files.append(
                        source
                    )
                elif source.is_dir():
                    dicom_dirs.append(
                        source
                    )
                else:
                    messagebox.showerror(
                        "Invalid DICOM source",
                        f"Path does not exist:\n{source}",
                    )
                    return

            if dicom_files:
                staged_dir = (
                    config.imaging.derivatives_dir
                    / "selected_dicom_files"
                )

                if (
                    staged_dir.exists()
                    and self.overwrite_var.get()
                ):
                    shutil.rmtree(
                        staged_dir
                    )

                staged_dir.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                for index, source in enumerate(
                    dicom_files,
                    start=1,
                ):
                    destination = (
                        staged_dir
                        / f"{index:05d}_{source.name}"
                    )

                    if (
                        destination.exists()
                        and not self.overwrite_var.get()
                    ):
                        continue

                    shutil.copy2(
                        source,
                        destination,
                    )

                dicom_dirs.append(
                    staged_dir
                )

            command = [
                sys.executable,
                "-u",
                str(DICOM_CONVERTER_SCRIPT),
            ]

            for input_dir in dicom_dirs:
                command.extend([
                    "--input-dir",
                    str(input_dir),
                ])

            command.extend([
                "--output-dir",
                str(stages["converted"]),
            ])

            if self.overwrite_var.get():
                command.append(
                    "--overwrite"
                )

            self.run_command(
                command,
                "DICOM to NIfTI conversion",
                on_success=lambda: (
                    self._prepare_selected_nifti_files(
                        stages["converted"]
                    )
                ),
            )
            return

        self._prepare_selected_nifti_files(stages["converted"])

    def _prepare_selected_nifti_files(
        self,
        converted_dir: Path,
    ) -> None:
        copied = 0

        for source_index, source_text in enumerate(
            self.nifti_input_paths,
            start=1,
        ):
            source = Path(
                source_text
            ).expanduser()

            if source.is_file():
                if not is_nifti(source):
                    messagebox.showerror(
                        "Invalid NIfTI file",
                        f"Not a NIfTI file:\n{source}",
                    )
                    return

                nifti_files = [
                    source
                ]
                source_dir = source.parent
                source_root = (
                    converted_dir
                    / f"nifti-file-{source_index:03d}"
                )
                keep_relative_parent = False

            elif source.is_dir():
                nifti_files = sorted(
                    path
                    for path in source.rglob("*")
                    if is_nifti(path)
                )
                source_dir = source
                source_root = (
                    converted_dir
                    / f"nifti-source-{source_index:03d}"
                )
                keep_relative_parent = True

            else:
                messagebox.showerror(
                    "Invalid NIfTI source",
                    f"Path does not exist:\n{source}",
                )
                return

            if not nifti_files:
                self._append_log(
                    f"No NIfTI files found in: {source}"
                )
                continue

            for nifti_path in nifti_files:
                if keep_relative_parent:
                    relative_parent = (
                        nifti_path.relative_to(
                            source_dir
                        ).parent
                    )
                else:
                    relative_parent = Path()

                destination_dir = (
                    source_root
                    / relative_parent
                )
                destination_dir.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                destination = (
                    destination_dir
                    / nifti_path.name
                )

                if (
                    destination.exists()
                    and not self.overwrite_var.get()
                ):
                    self._append_log(
                        "Skipping existing prepared NIfTI: "
                        f"{destination}"
                    )
                    continue

                shutil.copy2(
                    nifti_path,
                    destination,
                )

                sidecar = matching_json_path(
                    nifti_path
                )
                if sidecar is not None:
                    shutil.copy2(
                        sidecar,
                        destination_dir
                        / sidecar.name,
                    )

                for extra in matching_extra_sidecars(
                    nifti_path
                ):
                    shutil.copy2(
                        extra,
                        destination_dir
                        / extra.name,
                    )

                copied += 1
                self._append_log(
                    f"Prepared NIfTI: {nifti_path} -> {destination}"
                )

        self.status_var.set(
            "Completed: NIfTI preparation"
        )
        self._append_log(
            f"Prepared {copied} NIfTI file(s)."
        )

    def _run_scrubber(self) -> None:
        config = self._require_config()
        if config is None or not self._verify_script(HEADER_SCRUBBER_SCRIPT, "NIfTI header scrubber script"):
            return
        stages = self._stage_paths(config)
        command = [
            sys.executable,
            "-u",
            str(HEADER_SCRUBBER_SCRIPT),
            "--input-dir",
            str(stages["converted"]),
            "--output-dir",
            str(stages["scrubbed"]),
        ]
        if self.overwrite_var.get():
            command.append("--overwrite")
        self.run_command(command, "NIfTI header scrubbing")

    def _run_defacer(self) -> None:
        config = self._require_config()
        if config is None or not self._verify_script(DEFACER_SCRIPT, "PyDeface script"):
            return
        stages = self._stage_paths(config)
        command = [
            sys.executable,
            "-u",
            str(DEFACER_SCRIPT),
            "--input-dir",
            str(stages["scrubbed"]),
            "--output-dir",
            str(stages["defaced"]),
            "--log-dir",
            str(stages["logs"] / "pydeface"),
        ]
        if self.overwrite_var.get():
            command.append("--overwrite")
        self.run_command(command, "NIfTI defacing")

    def _open_review(self) -> None:
        config = self._require_config()
        if config is None:
            return
        stages = self._stage_paths(config)
        self._clear_window()
        review = ImagingReviewWindow(
            self,
            stages["converted"],
            stages["scrubbed"],
            stages["defaced"],
            stages["review_state"],
            on_close=self._show_processing,
        )
        review.pack(fill="both", expand=True)

        if not review.items:
            review.destroy()
            self._show_processing()
            messagebox.showerror(
                "No reviewable images",
                "Run preparation, header scrubbing, and defacing first.",
                parent=self,
            )

    def _accepted_files(
        self,
        config: ImagingPipelineConfig,
    ) -> list[Path]:
        stages = self._stage_paths(
            config
        )

        if not stages[
            "review_state"
        ].exists():
            return []

        try:
            state = json.loads(
                stages[
                    "review_state"
                ].read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return []

        accepted: list[Path] = []

        for relative_text, saved in state.items():
            if type(saved) is str:
                status = saved
                accepted_path = ""
            elif type(saved) is dict:
                status = str(
                    saved.get(
                        "status",
                        "",
                    )
                )
                accepted_path = str(
                    saved.get(
                        "accepted_defaced_path",
                        "",
                    )
                    or ""
                )
            else:
                continue

            if status not in {
                "Accepted",
                "Accepted - External",
            }:
                continue

            if accepted_path:
                path = Path(
                    accepted_path
                ).expanduser()

                if path.is_file():
                    accepted.append(
                        path.resolve()
                    )
                    continue

            relative = Path(
                relative_text
            )
            base = strip_nifti_suffix(
                relative
            )
            candidates = [
                stages["defaced"]
                / relative.parent
                / f"{base}_scrubbed_defaced.nii.gz",
                stages["defaced"]
                / relative.parent
                / f"{base}_scrubbed_defaced.nii",
            ]
            match = next(
                (
                    path
                    for path in candidates
                    if path.exists()
                ),
                None,
            )

            if match is not None:
                accepted.append(
                    match
                )

        return sorted(
            accepted
        )

    def _open_bids(self) -> None:
        config = self._require_config()
        if config is None or not self._verify_script(BIDS_CONVERTER_SCRIPT, "NIfTI to BIDS converter script"):
            return
        accepted = self._accepted_files(
            config
        )

        stages = self._stage_paths(
            config
        )
        held_count = 0

        if stages[
            "review_state"
        ].exists():
            try:
                review_state = json.loads(
                    stages[
                        "review_state"
                    ].read_text(
                        encoding="utf-8"
                    )
                )
            except (
                OSError,
                json.JSONDecodeError,
            ):
                review_state = {}

            for saved in review_state.values():
                if type(saved) is str:
                    status = saved
                elif type(saved) is dict:
                    status = str(
                        saved.get(
                            "status",
                            "",
                        )
                    )
                else:
                    status = ""

                if status == (
                    "On Hold - Needs Defaced Replacement"
                ):
                    held_count += 1

        if not accepted:
            messagebox.showerror(
                "No accepted images",
                "Accept at least one image in the review window first.",
            )
            return

        if held_count:
            if not messagebox.askyesno(
                "Images on hold",
                (
                    f"{len(accepted)} accepted image"
                    f"{'' if len(accepted) == 1 else 's'} can continue, "
                    f"and {held_count} image"
                    f"{'' if held_count == 1 else 's'} remain on hold "
                    "because defacing needs replacement.\n\n"
                    "Continue with the accepted images?"
                ),
                parent=self,
            ):
                return

        self._clear_window()
        page = BIDSMetadataWindow(
            self,
            accepted,
            config.imaging.bids_output_dir,
            self.overwrite_var.get(),
            on_close=self._show_processing,
        )
        page.pack(fill="both", expand=True)

    def run_command(
        self,
        command: List[str],
        operation_name: str,
        on_success: Optional[Callable[[], None]] = None,
    ) -> None:
        if self.pipeline_busy:
            messagebox.showwarning("Pipeline busy", "Another pipeline operation is already running.")
            return
        self.pipeline_busy = True
        self._set_controls_enabled(False)
        self.stop_button.configure(state="normal")
        self.status_var.set(f"Running: {operation_name}")
        self._append_log("\n" + "=" * 72)
        self._append_log(f"Starting {operation_name}")
        self._append_log("Command: " + " ".join(self._format_argument(arg) for arg in command))
        threading.Thread(
            target=self._command_worker,
            args=(command, operation_name, on_success),
            daemon=True,
        ).start()

    def _command_worker(
        self,
        command: List[str],
        operation_name: str,
        on_success: Optional[Callable[[], None]],
    ) -> None:
        try:
            self.running_process = subprocess.Popen(
                command,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            if self.running_process.stdout is not None:
                for line in self.running_process.stdout:
                    self.output_queue.put(line.rstrip("\n"))
            return_code = self.running_process.wait()
        except OSError as exc:
            self.output_queue.put(f"ERROR: Could not start {operation_name}: {exc}")
            return_code = 1
        finally:
            self.running_process = None
        self.after(0, lambda: self._command_finished(operation_name, return_code, on_success))

    def _command_finished(
        self,
        operation_name: str,
        return_code: int,
        on_success: Optional[Callable[[], None]],
    ) -> None:
        self.pipeline_busy = False
        self._set_controls_enabled(True)
        self.stop_button.configure(state="disabled")
        if return_code == 0:
            self.status_var.set(f"Completed: {operation_name}")
            self._append_log(f"{operation_name} completed successfully.")
            if on_success:
                on_success()
        else:
            self.status_var.set(f"Failed: {operation_name}")
            self._append_log(f"{operation_name} exited with code {return_code}.")
            messagebox.showerror("Pipeline operation failed", "See the pipeline log for details.")

    def _stop_current_operation(self) -> None:
        if self.running_process is not None and self.running_process.poll() is None:
            self.running_process.terminate()

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.derivatives_selector.set_enabled(enabled)
        self.bids_selector.set_enabled(enabled)
        for widget in (
            self.add_dicom_files_button,
            self.add_dicom_folders_button,
            self.remove_dicom_button,
            self.add_nifti_files_button,
            self.add_nifti_folders_button,
            self.remove_nifti_button,
            self.prepare_button,
            self.scrub_button,
            self.deface_button,
            self.review_button,
            self.bids_button,
            self.save_settings_button,
            self.overwrite_checkbox,
        ):
            widget.configure(state=state)

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _process_output_queue(self) -> None:
        while True:
            try:
                message = self.output_queue.get_nowait()
            except Empty:
                break
            self._append_log(message)
        self.after(100, self._process_output_queue)

    @staticmethod
    def _format_argument(argument: str) -> str:
        return f'"{argument}"' if " " in argument else argument

    def _close_dashboard(self) -> None:
        if (
            self.running_process is not None
            and self.running_process.poll() is None
        ):
            if not messagebox.askyesno(
                "Operation running",
                "Stop the current operation and close?",
                parent=self,
            ):
                return

            self.running_process.terminate()

        self.winfo_toplevel().destroy()


def main() -> None:
    root = tk.Tk()
    root.title("Imaging DeID Dashboard")
    root.geometry("1180x860")
    root.minsize(980, 720)

    app = ImagingDashboard(root)
    app.pack(fill="both", expand=True)

    root.protocol(
        "WM_DELETE_WINDOW",
        app._close_dashboard,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
