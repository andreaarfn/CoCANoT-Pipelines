#!/usr/bin/env python3

from __future__ import annotations

import json
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

BIDS_OPTIONAL_FIELDS = {
    "anat": ("task", "acq", "ce", "rec", "run", "echo", "flip", "inv", "mt", "part", "chunk"),
    "func": ("acq", "ce", "rec", "dir", "run", "echo", "part", "chunk"),
    "dwi": ("acq", "rec", "dir", "run", "part", "chunk"),
    "fmap": ("acq", "ce", "rec", "dir", "run", "echo", "flip", "inv", "part", "chunk"),
    "perf": ("acq", "rec", "dir", "run", "echo", "part", "mod"),
    "pet": ("task", "trc", "rec", "run"),
    "eeg": ("acq", "run", "space", "recording"),
    "meg": ("acq", "run", "proc", "split", "space", "recording"),
    "ieeg": ("acq", "run", "space", "recording"),
    "beh": ("acq", "run", "recording"),
    "micr": ("acq", "stain", "run", "chunk"),
    "nirs": ("acq", "run", "space", "recording"),
    "motion": ("acq", "run", "recording"),
    "mrs": ("task", "acq", "nuc", "voi", "rec", "run", "echo", "inv"),
}

BIDS_FIELD_LABELS = {
    "task": "Task", "acq": "Acquisition", "ce": "Contrast agent", "trc": "Tracer",
    "stain": "Stain", "rec": "Reconstruction", "dir": "Direction", "run": "Run",
    "echo": "Echo", "flip": "Flip", "inv": "Inversion", "mt": "MT", "part": "Part",
    "chunk": "Chunk", "mod": "Modality label", "recording": "Recording", "proc": "Processing",
    "space": "Space", "split": "Split", "sample": "Sample", "tracksys": "Tracking system",
    "nuc": "Nucleus", "voi": "Volume of interest",
}

IMAGING_PURPOSE_OPTIONS = (
    "Diagnostic evaluation",
    "Presurgical evaluation",
    "Neuromodulation Planning",
    "Electrode Localization",
    "Postoperative Evaluation (<30 days)",
    "Follow-up Evaluation (>30 days after surgery)",
    "Other",
    "Unknown",
)

SURGERY_TIMING_OPTIONS = (
    "Preoperative",
    "Intraoperative",
    "Immediate Postoperative (<30 days after surgery)",
    "Follow-up (>30 days after surgery)",
    "Unknown",
)


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


class ImagingReviewWindow(tk.Toplevel):
    """Review headers and images, edit safe text fields, and accept/reject files."""

    def __init__(
        self,
        parent: "ImagingDashboard",
        prepared_dir: Path,
        scrubbed_dir: Path,
        defaced_dir: Path,
        state_path: Path,
    ) -> None:
        super().__init__(parent)
        self.prepared_dir = prepared_dir
        self.scrubbed_dir = scrubbed_dir
        self.defaced_dir = defaced_dir
        self.state_path = state_path
        self.items: list[dict[str, object]] = []
        self.current_index: Optional[int] = None
        self.review_state = self._load_state()

        self.title("Imaging Header and Defacing Review")
        self.geometry("1550x930")
        self.minsize(1120, 760)
        self.transient(parent)

        self.field_var = tk.StringVar()
        self.value_var = tk.StringVar()
        self.volume_var = tk.IntVar(value=0)
        self.status_var = tk.StringVar(value="Select an image.")

        self._build_items()
        self._build_interface()
        self._populate_file_list()

    def _load_state(self) -> dict[str, str]:
        if not self.state_path.exists():
            return {}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.review_state, indent=2) + "\n", encoding="utf-8")

    def _build_items(self) -> None:
        for prepared_path in sorted(path for path in self.prepared_dir.rglob("*") if is_nifti(path)):
            relative = prepared_path.relative_to(self.prepared_dir)
            base = strip_nifti_suffix(prepared_path)
            scrubbed_candidates = [
                self.scrubbed_dir / relative.parent / f"{base}_scrubbed.nii.gz",
                self.scrubbed_dir / relative.parent / f"{base}_scrubbed.nii",
            ]
            scrubbed_path = next((path for path in scrubbed_candidates if path.exists()), None)
            if scrubbed_path is None:
                continue

            scrubbed_base = strip_nifti_suffix(scrubbed_path)
            defaced_candidates = [
                self.defaced_dir / relative.parent / f"{scrubbed_base}_defaced.nii.gz",
                self.defaced_dir / relative.parent / f"{scrubbed_base}_defaced.nii",
            ]
            defaced_path = next((path for path in defaced_candidates if path.exists()), None)
            if defaced_path is None:
                continue

            key = str(relative)
            self.items.append(
                {
                    "key": key,
                    "prepared": prepared_path,
                    "scrubbed": scrubbed_path,
                    "defaced": defaced_path,
                    "status": self.review_state.get(key, "Pending"),
                }
            )

    def _build_interface(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        sidebar = ttk.LabelFrame(root, text="NIfTI files", padding=8)
        sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        sidebar.rowconfigure(0, weight=1)

        self.file_list = tk.Listbox(sidebar, width=42, exportselection=False)
        self.file_list.grid(row=0, column=0, sticky="ns")
        self.file_list.bind("<<ListboxSelect>>", self._on_file_selected)
        scroll = ttk.Scrollbar(sidebar, orient="vertical", command=self.file_list.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.file_list.configure(yscrollcommand=scroll.set)

        content = ttk.Frame(root)
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        content.rowconfigure(1, weight=3)

        header_frame = ttk.LabelFrame(content, text="Raw header versus scrubbed header", padding=8)
        header_frame.grid(row=0, column=0, sticky="nsew")
        header_frame.columnconfigure(0, weight=1)
        header_frame.rowconfigure(0, weight=1)

        self.header_tree = ttk.Treeview(
            header_frame,
            columns=("field", "raw", "scrubbed", "editable"),
            show="headings",
            selectmode="browse",
        )
        for column, heading, width in (
            ("field", "Field", 180),
            ("raw", "Raw", 390),
            ("scrubbed", "Scrubbed", 390),
            ("editable", "Editable", 80),
        ):
            self.header_tree.heading(column, text=heading)
            self.header_tree.column(column, width=width, anchor="w")
        self.header_tree.grid(row=0, column=0, sticky="nsew")
        self.header_tree.bind("<<TreeviewSelect>>", self._on_header_selected)

        header_scroll = ttk.Scrollbar(header_frame, orient="vertical", command=self.header_tree.yview)
        header_scroll.grid(row=0, column=1, sticky="ns")
        self.header_tree.configure(yscrollcommand=header_scroll.set)

        edit = ttk.Frame(header_frame)
        edit.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        edit.columnconfigure(3, weight=1)
        ttk.Label(edit, text="Selected field").grid(row=0, column=0, sticky="w")
        ttk.Entry(edit, textvariable=self.field_var, state="readonly", width=22).grid(row=0, column=1, padx=(6, 14))
        ttk.Label(edit, text="Scrubbed value").grid(row=0, column=2, sticky="w")
        self.value_entry = ttk.Entry(edit, textvariable=self.value_var)
        self.value_entry.grid(row=0, column=3, sticky="ew", padx=(6, 8))
        ttk.Button(edit, text="Save Header Edit", command=self._save_header_edit).grid(row=0, column=4)

        image_frame = ttk.LabelFrame(content, text="Raw versus defaced image", padding=8)
        image_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        image_frame.columnconfigure(0, weight=1)
        image_frame.rowconfigure(0, weight=1)

        self.figure = Figure(figsize=(12, 7), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=image_frame)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        volume_controls = ttk.Frame(image_frame)
        volume_controls.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(volume_controls, text="4D volume").pack(side="left")
        self.volume_scale = ttk.Scale(
            volume_controls,
            from_=0,
            to=0,
            orient="horizontal",
            command=self._volume_changed,
        )
        self.volume_scale.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.volume_label = ttk.Label(volume_controls, text="0")
        self.volume_label.pack(side="right")

        footer = ttk.Frame(root)
        footer.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Label(footer, textvariable=self.status_var).pack(side="left")
        ttk.Button(footer, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(footer, text="Reject", command=lambda: self._set_status("Rejected")).pack(side="right", padx=(0, 8))
        ttk.Button(footer, text="Accept", command=lambda: self._set_status("Accepted")).pack(side="right", padx=(0, 8))

    def _populate_file_list(self) -> None:
        self.file_list.delete(0, "end")
        for item in self.items:
            self.file_list.insert("end", f"[{item['status']}] {item['key']}")
        if self.items:
            self.file_list.selection_set(0)
            self.file_list.activate(0)
            self._load_item(0)
        else:
            self.status_var.set("No matching prepared, scrubbed, and defaced files were found.")

    def _on_file_selected(self, _event: tk.Event) -> None:
        selected = self.file_list.curselection()
        if selected:
            self._load_item(int(selected[0]))

    @staticmethod
    def _header_dict(path: Path) -> dict[str, str]:
        img = nib.load(str(path))
        values: dict[str, str] = {}
        for key in img.header.keys():
            value = img.header[key]
            try:
                if hasattr(value, "tolist"):
                    value = value.tolist()
            except Exception:
                pass
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            values[str(key)] = str(value)
        values["shape"] = str(tuple(int(value) for value in img.shape))
        values["affine"] = np.array2string(img.affine, precision=5)
        return values

    def _populate_header_tree(self, prepared: Path, scrubbed: Path) -> None:
        for item_id in self.header_tree.get_children():
            self.header_tree.delete(item_id)

        raw = self._header_dict(prepared)
        clean = self._header_dict(scrubbed)

        for key in sorted(set(raw) | set(clean)):
            self.header_tree.insert(
                "",
                "end",
                iid=f"field-{key}",
                values=(
                    key,
                    raw.get(key, ""),
                    clean.get(key, ""),
                    "Yes" if key in EDITABLE_HEADER_FIELDS else "No",
                ),
            )

    def _on_header_selected(self, _event: tk.Event) -> None:
        selected = self.header_tree.selection()
        if not selected:
            return
        values = self.header_tree.item(selected[0], "values")
        field = str(values[0])
        self.field_var.set(field)
        self.value_var.set(str(values[2]))
        self.value_entry.configure(state="normal" if field in EDITABLE_HEADER_FIELDS else "disabled")

    def _save_header_edit(self) -> None:
        if self.current_index is None:
            return
        field = self.field_var.get()
        if field not in EDITABLE_HEADER_FIELDS:
            messagebox.showinfo("Read-only field", "Only NIfTI text fields are editable.", parent=self)
            return

        item = self.items[self.current_index]
        scrubbed_path = Path(item["scrubbed"])
        image = nib.load(str(scrubbed_path))
        header = image.header.copy()
        header[field] = self.value_var.get().encode("utf-8")
        updated = nib.Nifti1Image(np.asanyarray(image.dataobj), image.affine, header)

        qform, qform_code = image.get_qform(coded=True)
        sform, sform_code = image.get_sform(coded=True)
        updated.set_qform(qform, int(qform_code))
        updated.set_sform(sform, int(sform_code))
        nib.save(updated, str(scrubbed_path))

        self._populate_header_tree(Path(item["prepared"]), scrubbed_path)
        self.status_var.set("Header edit saved. Rerun defacing before accepting if this edit should be reflected in the defaced file.")

    def _load_item(self, index: int) -> None:
        self.current_index = index
        item = self.items[index]
        self._populate_header_tree(Path(item["prepared"]), Path(item["scrubbed"]))

        raw_image = nib.load(str(item["prepared"]))
        max_volume = max(0, raw_image.shape[3] - 1) if len(raw_image.shape) == 4 else 0
        self.volume_scale.configure(to=max_volume)
        self.volume_scale.set(0)
        self.volume_label.configure(text=f"0 / {max_volume}")
        self._plot_images(Path(item["prepared"]), Path(item["defaced"]), 0)
        self.status_var.set(f"{item['key']} | Review status: {item['status']}")

    def _volume_changed(self, value: str) -> None:
        if self.current_index is None:
            return
        volume = int(round(float(value)))
        item = self.items[self.current_index]
        self.volume_label.configure(text=f"{volume} / {int(float(self.volume_scale.cget('to')))}")
        self._plot_images(Path(item["prepared"]), Path(item["defaced"]), volume)

    @staticmethod
    def _get_volume(path: Path, volume_index: int) -> tuple[np.ndarray, str]:
        image = nib.load(str(path))
        data = np.asanyarray(image.dataobj)
        if data.ndim == 3:
            return data, "3D"
        if data.ndim == 4:
            index = min(max(volume_index, 0), data.shape[3] - 1)
            return data[..., index], f"4D volume {index}"
        raise ValueError(f"Only 3D and 4D NIfTI images are supported: {path}")

    @staticmethod
    def _normalize(data: np.ndarray) -> np.ndarray:
        finite = data[np.isfinite(data)]
        if finite.size == 0:
            return np.zeros_like(data, dtype=float)
        low, high = np.percentile(finite, [1, 99])
        if high <= low:
            return data.astype(float)
        return np.clip((data - low) / (high - low), 0, 1)

    def _plot_images(self, prepared: Path, defaced: Path, volume_index: int) -> None:
        self.figure.clear()
        try:
            raw, raw_label = self._get_volume(prepared, volume_index)
            clean, clean_label = self._get_volume(defaced, volume_index)
        except Exception as exc:
            self.status_var.set(str(exc))
            self.canvas.draw_idle()
            return

        if raw.shape != clean.shape:
            self.status_var.set(f"Image shape mismatch: {raw.shape} vs {clean.shape}")
            self.canvas.draw_idle()
            return

        raw = self._normalize(raw)
        clean = self._normalize(clean)

        x, y, z = raw.shape[0] // 2, raw.shape[1] // 2, raw.shape[2] // 2
        raw_views = (np.rot90(raw[:, :, z]), np.rot90(raw[:, y, :]), np.rot90(raw[x, :, :]))
        clean_views = (np.rot90(clean[:, :, z]), np.rot90(clean[:, y, :]), np.rot90(clean[x, :, :]))
        names = ("Axial", "Coronal", "Sagittal")

        for column, (name, raw_view, clean_view) in enumerate(zip(names, raw_views, clean_views)):
            axis = self.figure.add_subplot(2, 3, column + 1)
            axis.imshow(raw_view, cmap="gray", origin="lower")
            axis.set_title(f"Raw {name}")
            axis.axis("off")

            axis = self.figure.add_subplot(2, 3, column + 4)
            axis.imshow(clean_view, cmap="gray", origin="lower")
            axis.set_title(f"Defaced {name}")
            axis.axis("off")

        self.figure.suptitle(f"Raw: {raw_label} | Defaced: {clean_label}")
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _set_status(self, status: str) -> None:
        if self.current_index is None:
            return
        item = self.items[self.current_index]
        item["status"] = status
        self.review_state[str(item["key"])] = status
        self._save_state()

        index = self.current_index
        self.file_list.delete(index)
        self.file_list.insert(index, f"[{status}] {item['key']}")
        self.file_list.selection_set(index)
        self.file_list.activate(index)
        self.status_var.set(f"{item['key']} | Review status: {status}")

        if index + 1 < len(self.items):
            self.file_list.selection_clear(0, "end")
            self.file_list.selection_set(index + 1)
            self.file_list.activate(index + 1)
            self.file_list.see(index + 1)
            self._load_item(index + 1)



class CollapsibleSection(ttk.Frame):
    """Simple expand/collapse section for optional metadata."""

    def __init__(self, parent: tk.Widget, title: str, *, expanded: bool = False) -> None:
        super().__init__(parent)
        self.title_text = title
        self.expanded = expanded

        self.columnconfigure(0, weight=1)

        self.toggle_button = ttk.Button(
            self,
            command=self.toggle,
        )
        self.toggle_button.grid(row=0, column=0, sticky="ew")

        self.body = ttk.Frame(self, padding=(10, 8, 10, 4))
        self.body.columnconfigure(1, weight=1)
        self.body.columnconfigure(3, weight=1)

        self._refresh()

    def _refresh(self) -> None:
        marker = "▼" if self.expanded else "▶"
        self.toggle_button.configure(text=f"{marker} {self.title_text}")
        if self.expanded:
            self.body.grid(row=1, column=0, sticky="ew")
        else:
            self.body.grid_remove()

    def toggle(self) -> None:
        self.expanded = not self.expanded
        self._refresh()


class BIDSMetadataWindow(tk.Toplevel):
    """
    Collect CoCANoT-required imaging metadata and MRI/CT organization metadata.

    Scope of this version:
    - MRI: T1, T2, FLAIR, DWI, SWI
    - CT: CoCANoT extension (CT is not a core BIDS raw datatype in BIDS 1.11.1)

    Legend:
      ** = required by CoCANoT
       * = required for BIDS organization / the selected BIDS file type
      no marker = optional / recommended
    """

    IMAGING_MODALITIES = ("MRI", "CT")

    MRI_SEQUENCE_MAP = {
        "T1": ("anat", "T1w"),
        "T2": ("anat", "T2w"),
        "FLAIR": ("anat", "FLAIR"),
        "DWI": ("dwi", "dwi"),
        # Core BIDS 1.11.1 has no dedicated SWI suffix. CoCANoT stores an
        # SWI acquisition as a T2*-weighted anatomical image and identifies
        # the acquisition with acq-swi.
        "SWI": ("anat", "T2starw"),
    }

    MRI_OPTIONAL_FIELDS = (
        ("acq", "Acquisition label", "entry"),
        ("rec", "Reconstruction label", "entry"),
        ("run", "Run", "entry"),
        ("part", "Part", "combo", ("", "mag", "phase", "real", "imag")),
        ("manufacturer", "Manufacturer", "entry"),
        ("model_name", "Manufacturer's Model Name", "entry"),
        ("software_versions", "Software Versions", "entry"),
        ("magnetic_field_strength", "Magnetic Field Strength (T)", "entry"),
        ("receive_coil_name", "Receive Coil Name", "entry"),
        ("sequence_name", "Sequence Name", "entry"),
        ("pulse_sequence_details", "Pulse Sequence Details", "entry"),
        ("echo_time", "Echo Time (seconds)", "entry"),
        ("repetition_time_excitation", "Repetition Time Excitation (seconds)", "entry"),
        ("inversion_time", "Inversion Time (seconds)", "entry"),
        ("flip_angle", "Flip Angle (degrees)", "entry"),
        ("phase_encoding_direction", "Phase Encoding Direction", "entry"),
        ("effective_echo_spacing", "Effective Echo Spacing (seconds)", "entry"),
        ("total_readout_time", "Total Readout Time (seconds)", "entry"),
    )

    CT_OPTIONAL_FIELDS = (
        ("acq", "Acquisition label", "entry"),
        ("rec", "Reconstruction label", "entry"),
        ("run", "Run", "entry"),
        ("manufacturer", "Manufacturer", "entry"),
        ("model_name", "Manufacturer's Model Name", "entry"),
        ("software_versions", "Software Versions", "entry"),
        ("kvp", "KVP", "entry"),
        ("slice_thickness", "Slice Thickness (mm)", "entry"),
        ("convolution_kernel", "Convolution Kernel", "entry"),
        ("pixel_spacing", "Pixel Spacing (mm; JSON array)", "entry"),
        ("reconstruction_diameter", "Reconstruction Diameter (mm)", "entry"),
    )

    def __init__(
        self,
        parent: "ImagingDashboard",
        accepted_files: list[Path],
        output_dir: Path,
        overwrite: bool,
    ) -> None:
        super().__init__(parent)
        self.parent_dashboard = parent
        self.accepted_files = accepted_files
        self.output_dir = output_dir
        self.overwrite = overwrite
        self.records: Dict[str, Dict[str, object]] = {}
        self.optional_vars: Dict[str, tk.StringVar] = {}

        self.title("Imaging BIDS / CoCANoT Metadata Entry")
        self.geometry("1600x1000")
        self.minsize(1200, 760)
        self.transient(parent)

        # CoCANoT metadata.
        self.cocanot_patient_id_var = tk.StringVar()
        self.surgery_id_var = tk.StringVar()
        self.image_id_var = tk.StringVar()
        self.imaging_modality_var = tk.StringVar(value="MRI")
        self.mri_sequence_var = tk.StringVar(value="T1")
        self.surgery_timing_var = tk.StringVar(value="Unknown")
        self.comments_var = tk.StringVar()

        # BIDS / dataset organization.
        self.project_var = tk.StringVar()
        self.participant_var = tk.StringVar()
        self.session_var = tk.StringVar()

        self._build_interface()
        self._load_files()
        self._modality_changed()

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _optional_var(self, key: str, default: str = "") -> tk.StringVar:
        if key not in self.optional_vars:
            self.optional_vars[key] = tk.StringVar(value=default)
        return self.optional_vars[key]

    @staticmethod
    def _add_entry(
        parent: tk.Widget,
        row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
        *,
        columnspan: int = 1,
        readonly: bool = False,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(
            row=row, column=column, sticky="w", pady=(4, 2)
        )
        widget = ttk.Entry(
            parent,
            textvariable=variable,
            state="readonly" if readonly else "normal",
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
        ttk.Label(parent, text=label).grid(
            row=row, column=column, sticky="w", pady=(4, 2)
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

    @staticmethod
    def _selected_values(listbox: tk.Listbox) -> list[str]:
        return [str(listbox.get(index)) for index in listbox.curselection()]

    def _clear_frame(self, frame: tk.Widget) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _build_interface(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        ttk.Label(
            root,
            text="Imaging BIDS / CoCANoT Metadata Review",
            font=("", 18, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            root,
            text=(
                "** Required by CoCANoT     * Required for BIDS organization / "
                "the selected BIDS file type     Fields without a marker are optional "
                "or recommended. Comments are optional."
            ),
            wraplength=1500,
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        # --------------------------------------------------------------
        # File table
        # --------------------------------------------------------------

        table = ttk.Frame(root)
        table.grid(row=2, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)

        columns = (
            "include",
            "file",
            "project",
            "participant",
            "cocanot_patient",
            "surgery",
            "image_id",
            "modality",
            "sequence",
            "datatype",
            "status",
        )
        self.tree = ttk.Treeview(
            table,
            columns=columns,
            show="headings",
            selectmode="extended",
            height=8,
        )
        headings = {
            "include": "Include",
            "file": "Accepted NIfTI",
            "project": "Project*",
            "participant": "Subject ID*",
            "cocanot_patient": "CoCANoT Patient ID**",
            "surgery": "Surgery ID**",
            "image_id": "Image ID**",
            "modality": "Imaging Modality**",
            "sequence": "MRI Sequence**",
            "datatype": "Output Data Type",
            "status": "Status",
        }
        widths = {
            "include": 60,
            "file": 300,
            "project": 120,
            "participant": 110,
            "cocanot_patient": 140,
            "surgery": 110,
            "image_id": 110,
            "modality": 100,
            "sequence": 100,
            "datatype": 100,
            "status": 190,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w")

        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", self._toggle_at_pointer)
        y_scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )
        self.selection = ExtendedSelectionController(self.tree)

        # --------------------------------------------------------------
        # Scrollable metadata body
        # --------------------------------------------------------------

        shell = ttk.Frame(root)
        shell.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        self.metadata_canvas = tk.Canvas(shell, height=510, highlightthickness=0)
        self.metadata_canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(
            shell,
            orient="vertical",
            command=self.metadata_canvas.yview,
        )
        scroll.grid(row=0, column=1, sticky="ns")
        self.metadata_canvas.configure(yscrollcommand=scroll.set)

        self.metadata_body = ttk.Frame(self.metadata_canvas)
        self.metadata_window_id = self.metadata_canvas.create_window(
            (0, 0),
            window=self.metadata_body,
            anchor="nw",
        )
        self.metadata_body.bind(
            "<Configure>",
            lambda _event: self.metadata_canvas.configure(
                scrollregion=self.metadata_canvas.bbox("all")
            ),
        )
        self.metadata_canvas.bind(
            "<Configure>",
            lambda event: self.metadata_canvas.itemconfigure(
                self.metadata_window_id,
                width=event.width,
            ),
        )
        self.metadata_body.columnconfigure(0, weight=1)

        # --------------------------------------------------------------
        # CoCANoT required metadata
        # --------------------------------------------------------------

        cocanot = ttk.LabelFrame(
            self.metadata_body,
            text="CoCANoT Metadata — fields marked ** are required",
            padding=12,
        )
        cocanot.grid(row=0, column=0, sticky="ew")
        cocanot.columnconfigure(1, weight=1)
        cocanot.columnconfigure(3, weight=1)

        self._add_entry(
            cocanot, 0, 0, "CoCANoT Patient ID**", self.cocanot_patient_id_var
        )
        self._add_entry(
            cocanot, 0, 2, "Surgery ID**", self.surgery_id_var
        )
        self._add_entry(
            cocanot, 1, 0, "Image ID**", self.image_id_var
        )

        modality_combo = self._add_combo(
            cocanot,
            1,
            2,
            "Imaging Modality**",
            self.imaging_modality_var,
            self.IMAGING_MODALITIES,
        )
        modality_combo.bind("<<ComboboxSelected>>", self._modality_changed)

        ttk.Label(cocanot, text="MRI Sequence**").grid(
            row=2, column=0, sticky="w", pady=(4, 2)
        )
        self.mri_sequence_combo = ttk.Combobox(
            cocanot,
            textvariable=self.mri_sequence_var,
            values=tuple(self.MRI_SEQUENCE_MAP),
            state="readonly",
        )
        self.mri_sequence_combo.grid(
            row=2, column=1, sticky="ew", padx=(6, 14), pady=(4, 2)
        )
        self.mri_sequence_combo.bind(
            "<<ComboboxSelected>>",
            self._sequence_changed,
        )

        ttk.Label(
            cocanot,
            text="Purpose of Imaging** (select one or more)",
        ).grid(row=3, column=0, sticky="nw", pady=(8, 2))
        purpose_frame = ttk.Frame(cocanot)
        purpose_frame.grid(
            row=3,
            column=1,
            sticky="nsew",
            padx=(6, 14),
            pady=(8, 2),
        )
        purpose_frame.columnconfigure(0, weight=1)
        self.purpose_list = tk.Listbox(
            purpose_frame,
            selectmode="extended",
            exportselection=False,
            height=6,
        )
        self.purpose_list.grid(row=0, column=0, sticky="ew")
        for option in IMAGING_PURPOSE_OPTIONS:
            self.purpose_list.insert("end", option)
        purpose_scroll = ttk.Scrollbar(
            purpose_frame,
            orient="vertical",
            command=self.purpose_list.yview,
        )
        purpose_scroll.grid(row=0, column=1, sticky="ns")
        self.purpose_list.configure(yscrollcommand=purpose_scroll.set)
        self.purpose_selection = ExtendedSelectionController(self.purpose_list)

        ttk.Label(cocanot, text="Timing Relative to Surgery**").grid(
            row=3, column=2, sticky="nw", pady=(8, 2)
        )
        ttk.Combobox(
            cocanot,
            textvariable=self.surgery_timing_var,
            values=SURGERY_TIMING_OPTIONS,
            state="readonly",
        ).grid(
            row=3,
            column=3,
            sticky="ew",
            padx=(6, 14),
            pady=(8, 2),
        )

        ttk.Label(cocanot, text="Comments").grid(
            row=4, column=0, sticky="w", pady=(8, 2)
        )
        ttk.Entry(
            cocanot,
            textvariable=self.comments_var,
        ).grid(
            row=4,
            column=1,
            columnspan=3,
            sticky="ew",
            padx=(6, 14),
            pady=(8, 2),
        )
        ttk.Label(
            cocanot,
            text="Optional. Do not include protected health information (PHI).",
        ).grid(row=5, column=1, columnspan=3, sticky="w", padx=(6, 14))

        # --------------------------------------------------------------
        # BIDS / organization required fields
        # --------------------------------------------------------------

        required = ttk.LabelFrame(
            self.metadata_body,
            text="BIDS Required Metadata / Dataset Organization",
            padding=12,
        )
        required.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        required.columnconfigure(1, weight=1)
        required.columnconfigure(3, weight=1)

        self._add_entry(required, 0, 0, "Project*", self.project_var)
        self._add_entry(required, 0, 2, "Subject ID*", self.participant_var)
        self._add_entry(required, 1, 0, "Session ID", self.session_var)

        self.output_profile_var = tk.StringVar()
        self._add_entry(
            required,
            1,
            2,
            "Output profile",
            self.output_profile_var,
            readonly=True,
        )

        self.required_note_var = tk.StringVar()
        ttk.Label(
            required,
            textvariable=self.required_note_var,
            wraplength=1450,
        ).grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(8, 0),
        )

        # --------------------------------------------------------------
        # Optional metadata
        # --------------------------------------------------------------

        self.optional_section = CollapsibleSection(
            self.metadata_body,
            "BIDS Optional / Recommended Metadata",
            expanded=False,
        )
        self.optional_section.grid(
            row=2, column=0, sticky="ew", pady=(10, 0)
        )
        self.optional_body = self.optional_section.body

        self.ct_optional_section = CollapsibleSection(
            self.metadata_body,
            "CoCANoT CT Extension Metadata (optional; not core BIDS)",
            expanded=False,
        )
        self.ct_optional_section.grid(
            row=3, column=0, sticky="ew", pady=(10, 0)
        )
        self.ct_optional_body = self.ct_optional_section.body

        # --------------------------------------------------------------
        # Actions
        # --------------------------------------------------------------

        actions = ttk.Frame(root)
        actions.grid(row=4, column=0, sticky="ew", pady=(10, 0))

        ttk.Button(
            actions,
            text="Include Selected",
            command=lambda: self._set_included(True),
        ).pack(side="left")

        ttk.Button(
            actions,
            text="Exclude Selected",
            command=lambda: self._set_included(False),
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            actions,
            text="Apply to Selected",
            command=self._apply_to_selected,
        ).pack(side="left", padx=(18, 0))

        ttk.Button(
            actions,
            text="Convert Included Files",
            command=self._convert,
        ).pack(side="right")

    def _add_optional_fields(
        self,
        parent: tk.Widget,
        configs: tuple[tuple, ...],
    ) -> None:
        self._clear_frame(parent)
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(3, weight=1)

        for index, config in enumerate(configs):
            key, label, field_type, *rest = config
            row, pair = divmod(index, 2)
            column = pair * 2
            variable = self._optional_var(key)

            if field_type == "combo":
                values = tuple(rest[0])
                self._add_combo(
                    parent,
                    row,
                    column,
                    label,
                    variable,
                    values,
                )
            else:
                self._add_entry(
                    parent,
                    row,
                    column,
                    label,
                    variable,
                )

    # ------------------------------------------------------------------
    # Modality / sequence behavior
    # ------------------------------------------------------------------

    def _modality_changed(self, _event: Optional[tk.Event] = None) -> None:
        modality = self.imaging_modality_var.get().strip()

        if modality == "MRI":
            self.mri_sequence_combo.configure(state="readonly")
            if self.mri_sequence_var.get() not in self.MRI_SEQUENCE_MAP:
                self.mri_sequence_var.set("T1")

            self.optional_section.grid()
            self.ct_optional_section.grid_remove()
            self._add_optional_fields(
                self.optional_body,
                self.MRI_OPTIONAL_FIELDS,
            )
            self._sequence_changed()
        else:
            self.mri_sequence_combo.configure(state="disabled")
            self.mri_sequence_var.set("")

            self.optional_section.grid_remove()
            self.ct_optional_section.grid()
            self._add_optional_fields(
                self.ct_optional_body,
                self.CT_OPTIONAL_FIELDS,
            )
            self.output_profile_var.set("ct / *_ct (CoCANoT extension)")
            self.required_note_var.set(
                "CT is intentionally stored as a CoCANoT extension because BIDS 1.11.1 "
                "does not define a core raw CT datatype. It is not mislabeled as MRI."
            )

    def _sequence_changed(self, _event: Optional[tk.Event] = None) -> None:
        sequence = self.mri_sequence_var.get().strip()
        profile = self.MRI_SEQUENCE_MAP.get(sequence)
        if profile is None:
            self.output_profile_var.set("")
            return

        datatype, suffix = profile
        if sequence == "SWI":
            self._optional_var("acq").set(
                self._optional_var("acq").get() or "swi"
            )
            self.output_profile_var.set(
                f"{datatype} / acq-swi_{suffix}"
            )
            self.required_note_var.set(
                "Core BIDS 1.11.1 has no dedicated SWI suffix. CoCANoT maps SWI "
                "to a T2*-weighted anatomical image with the acquisition label 'swi'. "
                "Use this only for an SWI image appropriately represented as T2starw."
            )
        elif sequence == "DWI":
            self.output_profile_var.set("dwi / *_dwi")
            self.required_note_var.set(
                "DWI conversion requires matching .bval and .bvec gradient files. "
                "The converter will stop rather than create an incomplete DWI dataset."
            )
        else:
            self.output_profile_var.set(f"{datatype} / *_{suffix}")
            self.required_note_var.set(
                "T1, T2, and FLAIR structural MRI do not require additional "
                "modality-specific JSON fields solely to name the raw BIDS image. "
                "Recommended scanner/acquisition metadata are available below."
            )

    # ------------------------------------------------------------------
    # Records
    # ------------------------------------------------------------------

    def _load_files(self) -> None:
        for index, path in enumerate(self.accepted_files, start=1):
            item_id = f"image-{index}"
            self.records[item_id] = {
                "nifti_path": str(path.resolve()),
                "source_label": path.name,
                "include": "Yes",
                "project": "",
                "participant_id": "",
                "session_id": "",
                "cocanot_patient_id": "",
                "surgery_id": "",
                "image_id": "",
                "imaging_modality": "",
                "mri_sequence": "",
                "datatype": "",
                "suffix": "",
                "imaging_purpose": [],
                "timing_relative_to_surgery": "",
                "comments": "",
                "optional_metadata": {},
                "status": "Missing required metadata",
            }
            self._refresh_row(item_id)

        if self.records:
            first = next(iter(self.records))
            self.tree.selection_set(first)
            self.tree.focus(first)
            self.selection.anchor = first

    def _refresh_row(self, item_id: str) -> None:
        record = self.records[item_id]
        self.tree_values = (
            record["include"],
            record["source_label"],
            record["project"],
            record["participant_id"],
            record["cocanot_patient_id"],
            record["surgery_id"],
            record["image_id"],
            record["imaging_modality"],
            record["mri_sequence"],
            record["datatype"],
            record["status"],
        )
        if self.tree.exists(item_id):
            self.tree.item(item_id, values=self.tree_values)
        else:
            self.tree.insert("", "end", iid=item_id, values=self.tree_values)

    def _current_values(self) -> Dict[str, object]:
        modality = self.imaging_modality_var.get().strip()
        sequence = (
            self.mri_sequence_var.get().strip()
            if modality == "MRI"
            else ""
        )

        if modality == "MRI":
            datatype, suffix = self.MRI_SEQUENCE_MAP.get(
                sequence,
                ("", ""),
            )
            allowed_optional = {
                config[0] for config in self.MRI_OPTIONAL_FIELDS
            }
        else:
            datatype, suffix = "ct", "ct"
            allowed_optional = {
                config[0] for config in self.CT_OPTIONAL_FIELDS
            }

        optional_metadata = {
            key: variable.get().strip()
            for key, variable in self.optional_vars.items()
            if key in allowed_optional and variable.get().strip()
        }

        if modality == "MRI" and sequence == "SWI":
            optional_metadata.setdefault("acq", "swi")

        return {
            "project": self.project_var.get().strip(),
            "participant_id": self.participant_var.get().strip(),
            "session_id": self.session_var.get().strip(),
            "cocanot_patient_id": self.cocanot_patient_id_var.get().strip(),
            "surgery_id": self.surgery_id_var.get().strip(),
            "image_id": self.image_id_var.get().strip(),
            "imaging_modality": modality,
            "mri_sequence": sequence,
            "datatype": datatype,
            "suffix": suffix,
            "imaging_purpose": self._selected_values(self.purpose_list),
            "timing_relative_to_surgery": self.surgery_timing_var.get().strip(),
            "comments": self.comments_var.get().strip(),
            "optional_metadata": optional_metadata,
        }

    @staticmethod
    def _record_status(record: Dict[str, object]) -> str:
        if record.get("include") != "Yes":
            return "Excluded"

        for key, label in (
            ("project", "project"),
            ("participant_id", "subject ID"),
            ("cocanot_patient_id", "CoCANoT Patient ID"),
            ("surgery_id", "Surgery ID"),
            ("image_id", "Image ID"),
            ("imaging_modality", "imaging modality"),
        ):
            if not str(record.get(key, "")).strip():
                return f"Missing {label}"

        if not record.get("imaging_purpose"):
            return "Missing purpose of imaging"

        if record.get("timing_relative_to_surgery") not in SURGERY_TIMING_OPTIONS:
            return "Missing timing relative to surgery"

        if record.get("imaging_modality") == "MRI":
            if record.get("mri_sequence") not in BIDSMetadataWindow.MRI_SEQUENCE_MAP:
                return "Missing MRI sequence"

        return "Ready"

    def _apply_to_selected(self) -> None:
        selected = list(self.tree.selection())
        if not selected:
            messagebox.showinfo(
                "No selection",
                "Select one or more images first.",
                parent=self,
            )
            return

        values = self._current_values()
        test_record = {"include": "Yes", **values}
        status = self._record_status(test_record)
        if status != "Ready":
            messagebox.showerror(
                "Incomplete metadata",
                status,
                parent=self,
            )
            return

        for item_id in selected:
            record = self.records[item_id]
            record.update(values)
            record["status"] = self._record_status(record)
            self._refresh_row(item_id)

    def _set_included(self, included: bool) -> None:
        selected = list(self.tree.selection())
        if not selected:
            messagebox.showinfo(
                "No selection",
                "Select one or more images first.",
                parent=self,
            )
            return

        for item_id in selected:
            self.records[item_id]["include"] = "Yes" if included else "No"
            self.records[item_id]["status"] = self._record_status(
                self.records[item_id]
            )
            self._refresh_row(item_id)

    def _toggle_at_pointer(self, event: tk.Event) -> None:
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        current = self.records[item_id]["include"]
        self.records[item_id]["include"] = (
            "No" if current == "Yes" else "Yes"
        )
        self.records[item_id]["status"] = self._record_status(
            self.records[item_id]
        )
        self._refresh_row(item_id)

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    def _convert(self) -> None:
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

        problems: list[str] = []
        for record in included:
            record["status"] = self._record_status(record)
            if record["status"] != "Ready":
                problems.append(
                    f"{record['source_label']}: {record['status']}"
                )

        if problems:
            messagebox.showerror(
                "Incomplete metadata",
                "\n".join(problems[:20]),
                parent=self,
            )
            return

        manifest_path = (
            Path(str(included[0]["nifti_path"])).parent.parent
            / "nifti_bids_manifest.json"
        )

        manifest = {
            "bids_version": "1.11.1",
            "records": [
                {
                    "nifti_path": record["nifti_path"],
                    "project": record["project"],
                    "participant_id": record["participant_id"],
                    "session_id": record["session_id"],
                    "cocanot_patient_id": record["cocanot_patient_id"],
                    "surgery_id": record["surgery_id"],
                    "image_id": record["image_id"],
                    "imaging_modality": record["imaging_modality"],
                    "mri_sequence": record["mri_sequence"],
                    "datatype": record["datatype"],
                    "suffix": record["suffix"],
                    "imaging_purpose": record["imaging_purpose"],
                    "timing_relative_to_surgery": record[
                        "timing_relative_to_surgery"
                    ],
                    "comments": record["comments"],
                    "optional_metadata": record["optional_metadata"],
                }
                for record in included
            ],
        }

        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n",
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
            command.append("--overwrite")

        self.parent_dashboard.run_command(
            command,
            "Imaging BIDS / CoCANoT conversion",
            on_success=self.destroy,
        )



class ImagingDashboard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Imaging DeID Dashboard")
        self.geometry("1180x860")
        self.minsize(980, 720)

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

        self._build_interface()
        self._refresh_all_input_lists()
        self.after(100, self._process_output_queue)
        self.protocol("WM_DELETE_WINDOW", self._close_dashboard)

    def _read_saved_settings(self) -> dict:
        try:
            return load_settings_dict()
        except PipelineConfigError as exc:
            messagebox.showwarning("Settings warning", str(exc))
            return {"imaging": {}}

    def _build_interface(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        ttk.Label(root, text="Imaging DeID Dashboard", font=("", 22, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            root,
            text=(
                "Select DICOM folders or NIfTI files, prepare NIfTI inputs, scrub headers, "
                "deface, review, and convert accepted files to BIDS."
            ),
            wraplength=1100,
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))

        folders = ttk.LabelFrame(root, text="Source and output folders", padding=12)
        folders.grid(row=2, column=0, sticky="ew")
        folders.columnconfigure(0, weight=1)

        source_frame = ttk.Frame(folders)
        source_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        source_frame.columnconfigure(0, weight=1)
        source_frame.columnconfigure(1, weight=1)

        self.dicom_input_list, self.dicom_input_selection, self.add_dicom_button, self.remove_dicom_button = self._build_input_panel(
            source_frame,
            column=0,
            title="DICOM source folders",
            add_text="Add DICOM Folders…",
            add_command=self._add_dicom_inputs,
            remove_command=lambda: self._remove_selected_inputs(self.dicom_input_list, self.dicom_input_paths),
        )
        self.nifti_input_list, self.nifti_input_selection, self.add_nifti_button, self.remove_nifti_button = self._build_input_panel(
            source_frame,
            column=1,
            title="NIfTI source folders",
            add_text="Add NIfTI Folders…",
            add_command=self._add_nifti_inputs,
            remove_command=lambda: self._remove_selected_inputs(self.nifti_input_list, self.nifti_input_paths),
        )

        self.derivatives_selector = FolderSelector(
            folders,
            "Derivatives output folder",
            self.derivatives_dir_var,
            "Select the imaging derivatives output folder",
            PROJECT_ROOT,
        )
        self.derivatives_selector.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        ttk.Label(
            folders,
            text=(
                "The dashboard creates converted_nifti, scrubbed_header, "
                "scrubbed_defaced, logs, and imaging_review_state.json inside this folder."
            ),
        ).grid(row=2, column=0, sticky="w", pady=(0, 10))

        self.bids_selector = FolderSelector(
            folders,
            "BIDS output folder",
            self.bids_output_dir_var,
            "Select the imaging BIDS output folder",
            PROJECT_ROOT,
        )
        self.bids_selector.grid(row=3, column=0, sticky="ew")

        content = ttk.Frame(root)
        content.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)

        operations = ttk.LabelFrame(content, text="Pipeline Operations", padding=12)
        operations.grid(row=0, column=0, sticky="ew")
        for index in range(5):
            operations.columnconfigure(index, weight=1)

        self.prepare_button = ttk.Button(operations, text="1. Prepare NIfTI", command=self._prepare_nifti)
        self.prepare_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.scrub_button = ttk.Button(operations, text="2. Scrub Headers", command=self._run_scrubber)
        self.scrub_button.grid(row=0, column=1, sticky="ew", padx=5)
        self.deface_button = ttk.Button(operations, text="3. Deface", command=self._run_defacer)
        self.deface_button.grid(row=0, column=2, sticky="ew", padx=5)
        self.review_button = ttk.Button(operations, text="4. Review", command=self._open_review)
        self.review_button.grid(row=0, column=3, sticky="ew", padx=5)
        self.bids_button = ttk.Button(operations, text="5. Convert to BIDS", command=self._open_bids)
        self.bids_button.grid(row=0, column=4, sticky="ew", padx=(5, 0))

        self.stop_button = ttk.Button(
            operations,
            text="Stop Current Operation",
            command=self._stop_current_operation,
            state="disabled",
        )
        self.stop_button.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(8, 0))

        self.overwrite_checkbox = ttk.Checkbutton(
            operations,
            text="Overwrite existing stage outputs or exact BIDS outputs",
            variable=self.overwrite_var,
        )
        self.overwrite_checkbox.grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        self.save_settings_button = ttk.Button(
            operations,
            text="Save Folder Settings",
            command=self._save_folder_settings,
        )
        self.save_settings_button.grid(row=2, column=4, sticky="e", pady=(8, 0))

        log_frame = ttk.LabelFrame(content, text="Pipeline Log", padding=8)
        log_frame.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        ttk.Label(log_frame, textvariable=self.status_var).grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.log_text = tk.Text(log_frame, wrap="word", height=12, state="disabled")
        self.log_text.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

        self._append_log(f"Dashboard ready. Settings file: {get_settings_path()}")

    def _build_input_panel(
        self,
        parent: tk.Widget,
        column: int,
        title: str,
        add_text: str,
        add_command: Callable[[], None],
        remove_command: Callable[[], None],
    ) -> tuple[tk.Listbox, ExtendedSelectionController, ttk.Button, ttk.Button]:
        panel = ttk.LabelFrame(parent, text=title, padding=8)
        panel.grid(row=0, column=column, sticky="nsew", padx=(0, 5) if column == 0 else (5, 0))
        panel.columnconfigure(0, weight=1)

        listbox = tk.Listbox(panel, height=5, selectmode="extended", exportselection=False)
        listbox.grid(row=0, column=0, sticky="ew")
        selection = ExtendedSelectionController(listbox)

        buttons = ttk.Frame(panel)
        buttons.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        add_button = ttk.Button(buttons, text=add_text, command=add_command)
        add_button.pack(side="left")
        remove_button = ttk.Button(buttons, text="Remove Selected", command=remove_command)
        remove_button.pack(side="right")
        return listbox, selection, add_button, remove_button

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
        self._refresh_input_list(self.dicom_input_list, self.dicom_input_selection, self.dicom_input_paths)
        self._refresh_input_list(self.nifti_input_list, self.nifti_input_selection, self.nifti_input_paths)

    @staticmethod
    def _append_unique_paths(target: List[str], selected: List[str]) -> None:
        existing = set(target)
        for path in selected:
            resolved = str(Path(path).expanduser().resolve())
            if resolved not in existing:
                target.append(resolved)
                existing.add(resolved)

    def _add_dicom_inputs(self) -> None:
        initial = Path(self.dicom_input_paths[0]).parent if self.dicom_input_paths else PROJECT_ROOT
        selected = MultiFolderSelectionDialog.ask_folders(self, "Add DICOM source folders", initial)
        self._append_unique_paths(self.dicom_input_paths, selected)
        self._refresh_input_list(self.dicom_input_list, self.dicom_input_selection, self.dicom_input_paths)

    def _add_nifti_inputs(self) -> None:
        initial = Path(self.nifti_input_paths[0]).parent if self.nifti_input_paths else PROJECT_ROOT
        selected = MultiFolderSelectionDialog.ask_folders(self, "Add NIfTI source folders", initial)
        self._append_unique_paths(self.nifti_input_paths, selected)
        self._refresh_input_list(self.nifti_input_list, self.nifti_input_selection, self.nifti_input_paths)

    def _remove_selected_inputs(self, listbox: tk.Listbox, paths: List[str]) -> None:
        for index in reversed(listbox.curselection()):
            del paths[index]
        self._refresh_all_input_lists()

    def _selected_settings_dict(self) -> dict:
        settings = build_imaging_settings_dict(
            input_dirs=self.dicom_input_paths + self.nifti_input_paths,
            derivatives_dir=self.derivatives_dir_var.get().strip(),
            bids_output_dir=self.bids_output_dir_var.get().strip(),
        )
        imaging = settings.setdefault("imaging", {})
        imaging["dicom_input_dirs"] = list(self.dicom_input_paths)
        imaging["nifti_input_dirs"] = list(self.nifti_input_paths)
        imaging.pop("nifti_input_files", None)
        return settings

    def _save_folder_settings(self, show_confirmation: bool = True) -> Optional[ImagingPipelineConfig]:
        if not self.dicom_input_paths and not self.nifti_input_paths:
            messagebox.showerror("Missing inputs", "Add at least one DICOM folder or NIfTI folder.")
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
            if not self._verify_script(DICOM_CONVERTER_SCRIPT, "DICOM converter script"):
                return
            command = [sys.executable, "-u", str(DICOM_CONVERTER_SCRIPT)]
            for input_path in self.dicom_input_paths:
                command.extend(["--input-dir", input_path])
            command.extend(["--output-dir", str(stages["converted"])])
            if self.overwrite_var.get():
                command.append("--overwrite")
            self.run_command(
                command,
                "DICOM to NIfTI conversion",
                on_success=lambda: self._prepare_selected_nifti_files(stages["converted"]),
            )
            return

        self._prepare_selected_nifti_files(stages["converted"])

    def _prepare_selected_nifti_files(self, converted_dir: Path) -> None:
        copied = 0
        for source_index, source_text in enumerate(self.nifti_input_paths, start=1):
            source_dir = Path(source_text).expanduser()
            if not source_dir.is_dir():
                messagebox.showerror("Invalid NIfTI folder", f"Not a folder:\n{source_dir}")
                return

            nifti_files = sorted(path for path in source_dir.rglob("*") if is_nifti(path))
            if not nifti_files:
                self._append_log(f"No NIfTI files found in: {source_dir}")
                continue

            source_root = converted_dir / f"nifti-source-{source_index:03d}"
            for source in nifti_files:
                relative_parent = source.relative_to(source_dir).parent
                destination_dir = source_root / relative_parent
                destination_dir.mkdir(parents=True, exist_ok=True)
                destination = destination_dir / source.name

                if destination.exists() and not self.overwrite_var.get():
                    self._append_log(f"Skipping existing prepared NIfTI: {destination}")
                    continue

                shutil.copy2(source, destination)
                sidecar = matching_json_path(source)
                if sidecar is not None:
                    shutil.copy2(sidecar, destination_dir / sidecar.name)
                for extra in matching_extra_sidecars(source):
                    shutil.copy2(extra, destination_dir / extra.name)
                copied += 1
                self._append_log(f"Prepared NIfTI: {source} -> {destination}")

        self.status_var.set("Completed: NIfTI preparation")
        self._append_log(f"Prepared {copied} NIfTI file(s).")

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
        review = ImagingReviewWindow(
            self,
            stages["converted"],
            stages["scrubbed"],
            stages["defaced"],
            stages["review_state"],
        )
        if not review.items:
            review.destroy()
            messagebox.showerror("No reviewable images", "Run preparation, header scrubbing, and defacing first.")

    def _accepted_files(self, config: ImagingPipelineConfig) -> list[Path]:
        stages = self._stage_paths(config)
        if not stages["review_state"].exists():
            return []
        try:
            state = json.loads(stages["review_state"].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        accepted: list[Path] = []
        for relative_text, status in state.items():
            if status != "Accepted":
                continue
            relative = Path(relative_text)
            base = strip_nifti_suffix(relative)
            candidates = [
                stages["defaced"] / relative.parent / f"{base}_scrubbed_defaced.nii.gz",
                stages["defaced"] / relative.parent / f"{base}_scrubbed_defaced.nii",
            ]
            match = next((path for path in candidates if path.exists()), None)
            if match is not None:
                accepted.append(match)
        return sorted(accepted)

    def _open_bids(self) -> None:
        config = self._require_config()
        if config is None or not self._verify_script(BIDS_CONVERTER_SCRIPT, "NIfTI to BIDS converter script"):
            return
        accepted = self._accepted_files(config)
        if not accepted:
            messagebox.showerror("No accepted images", "Accept at least one image in the review window first.")
            return
        BIDSMetadataWindow(self, accepted, config.imaging.bids_output_dir, self.overwrite_var.get())

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
            self.add_dicom_button,
            self.remove_dicom_button,
            self.add_nifti_button,
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
        if self.running_process is not None and self.running_process.poll() is None:
            if not messagebox.askyesno("Operation running", "Stop the current operation and close?"):
                return
            self.running_process.terminate()
        self.destroy()


def main() -> None:
    app = ImagingDashboard()
    app.mainloop()


if __name__ == "__main__":
    main()
