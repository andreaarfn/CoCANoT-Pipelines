#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable, Dict, List, Optional

EEG_PIPELINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EEG_PIPELINE_DIR.parent
SCRIPTS_DIR = EEG_PIPELINE_DIR / "scripts"

# pipeline_config.py is stored in the shared parent folder.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from MetadataPipeline.forms.clinical_assessment import (
    import_clinical_file,
    reconcile_clinical_assessment,
    review_clinical_batch,
)
from MetadataPipeline.storage import LocalMetadataStore
from MetadataPipeline.storage.record_repository import MetadataRepository
from MetadataPipeline.validation import MetadataValidator, load_dictionary
from MetadataPipeline.validation.conditions import condition_matches

from ElectrophysiologyPipeline.views import EphysHome

from pipeline_config import (
    PipelineConfig,
    PipelineConfigError,
    build_settings_dict,
    get_settings_path,
    load_pipeline_config,
    load_settings_dict,
    save_settings_dict,
    validate_pipeline_config,
)

SCRUBBER_SCRIPT = SCRIPTS_DIR / "scrub_edf_metadata.py"
COMPARISON_SCRIPT = SCRIPTS_DIR / "compare_raw_and_scrubbed_edf.py"
BIDS_CONVERTER_SCRIPT = SCRIPTS_DIR / "convert_edf_to_bids.py"
METADATA_DICTIONARY = (
    PROJECT_ROOT
    / "MetadataPipeline"
    / "dictionaries"
    / "CoCANoT_Metadata_Phase1.xlsx"
)

COMPARISON_PORT = 8765
COMPARISON_URL = f"http://127.0.0.1:{COMPARISON_PORT}"


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
        if isinstance(self.widget, ttk.Treeview):
            focused = self.widget.focus()
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
    """Navigate folders and select multiple sibling directories with the keyboard."""

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        initial_dir: Path,
    ) -> None:
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
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        ttk.Label(
            root,
            text=(
                "Select one or more folders. Use Shift + Up/Down or Shift-click for a range, "
                "and Ctrl/Cmd-click for individual folders."
            ),
            wraplength=760,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Button(root, text="Up", command=self.go_up).grid(row=1, column=0, sticky="w")
        path_entry = ttk.Entry(root, textvariable=self.path_var)
        path_entry.grid(row=1, column=1, sticky="ew", padx=8)
        path_entry.bind("<Return>", self.go_to_typed_path)
        ttk.Button(root, text="Go", command=self.go_to_typed_path).grid(row=1, column=2)
        root.columnconfigure(1, weight=1)

        list_frame = ttk.Frame(root)
        list_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.folder_list = tk.Listbox(
            list_frame,
            selectmode="extended",
            exportselection=False,
            activestyle="dotbox",
        )
        self.folder_list.grid(row=0, column=0, sticky="nsew")
        self.folder_list.bind("<Double-1>", self.open_active_folder)
        self.folder_list.bind("<Return>", self.open_active_folder)
        self.selection = ExtendedSelectionController(self.folder_list)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.folder_list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.folder_list.configure(yscrollcommand=scrollbar.set)

        actions = ttk.Frame(root)
        actions.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(
            actions,
            text="Add Selected Folders",
            command=self.accept_selected,
        ).pack(side="right", padx=(0, 8))
        ttk.Button(
            actions,
            text="Add Current Folder",
            command=self.accept_current,
        ).pack(side="left")

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
        self.folder_list.focus_set()

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
        if event is not None and getattr(event, "y", None) is not None:
            index = self.folder_list.nearest(event.y)
        else:
            index = int(self.folder_list.index("active"))
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
    def ask_folders(
        cls,
        parent: tk.Widget,
        title: str,
        initial_dir: Path,
    ) -> List[str]:
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


_COMPARISON_MODULE = None


def load_comparison_module():
    """Load the comparison script as a reusable module without starting Flask."""
    global _COMPARISON_MODULE
    if _COMPARISON_MODULE is not None:
        return _COMPARISON_MODULE

    spec = importlib.util.spec_from_file_location(
        "edf_comparison_helpers",
        COMPARISON_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load comparison helpers from {COMPARISON_SCRIPT}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _COMPARISON_MODULE = module
    return module


class EDFReviewWindow(ttk.Frame):
    """Embedded page for comparing and editing raw/scrubbed EDF metadata."""

    def __init__(
        self,
        parent: "PipelineDashboard",
        input_dir: Path,
        scrubbed_dir: Path,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.parent_dashboard = parent
        self.on_close = on_close
        self.input_dir = input_dir
        self.scrubbed_dir = scrubbed_dir
        self.helpers = load_comparison_module()
        self.pairs: List[Dict[str, object]] = []
        self.current_pair_index: Optional[int] = None
        self.current_data: Optional[Dict[str, object]] = None

        self.header_field_var = tk.StringVar()
        self.header_value_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select an EDF file.")

        self.build_pairs()
        self.build_interface()
        self.populate_file_list()

    def _close_page(self) -> None:
        if self.on_close is not None:
            self.on_close()
        else:
            self.destroy()

    def build_pairs(self) -> None:
        for raw_path in self.helpers.find_edf_files(self.input_dir):
            relative_path = raw_path.relative_to(self.input_dir)
            scrubbed_path = (
                self.scrubbed_dir
                / relative_path.parent
                / self.helpers.scrubbed_filename(raw_path)
            )
            if scrubbed_path.exists():
                self.pairs.append(
                    {
                        "label": str(relative_path),
                        "raw_path": raw_path.resolve(),
                        "scrubbed_path": scrubbed_path.resolve(),
                    }
                )

    def build_interface(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(1, weight=1)

        ttk.Label(root, text="EDF Header and Annotation Review", font=("", 18, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(
            root,
            text=(
                "Raw EDF values are read-only. Select a scrubbed header field or annotation "
                "to edit it, then save the scrubbed EDF."
            ),
            wraplength=1380,
        ).grid(row=0, column=1, sticky="e")

        sidebar = ttk.LabelFrame(root, text="EDF files", padding=8)
        sidebar.grid(row=1, column=0, sticky="nsw", pady=(12, 0), padx=(0, 10))
        sidebar.rowconfigure(0, weight=1)
        self.file_list = tk.Listbox(sidebar, width=42, exportselection=False)
        self.file_list.grid(row=0, column=0, sticky="ns")
        self.file_list.bind("<<ListboxSelect>>", self.on_file_selected)
        file_scroll = ttk.Scrollbar(sidebar, orient="vertical", command=self.file_list.yview)
        file_scroll.grid(row=0, column=1, sticky="ns")
        self.file_list.configure(yscrollcommand=file_scroll.set)

        content = ttk.Frame(root)
        content.grid(row=1, column=1, sticky="nsew", pady=(12, 0))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=3)
        content.rowconfigure(1, weight=2)

        header_frame = ttk.LabelFrame(content, text="Complete EDF header", padding=8)
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
            ("raw", "Raw EDF", 390),
            ("scrubbed", "Scrubbed EDF", 390),
            ("editable", "Editable", 75),
        ):
            self.header_tree.heading(column, text=heading)
            self.header_tree.column(column, width=width, anchor="w")
        self.header_tree.grid(row=0, column=0, sticky="nsew")
        self.header_tree.bind("<<TreeviewSelect>>", self.on_header_selected)
        header_y = ttk.Scrollbar(header_frame, orient="vertical", command=self.header_tree.yview)
        header_y.grid(row=0, column=1, sticky="ns")
        header_x = ttk.Scrollbar(header_frame, orient="horizontal", command=self.header_tree.xview)
        header_x.grid(row=1, column=0, sticky="ew")
        self.header_tree.configure(yscrollcommand=header_y.set, xscrollcommand=header_x.set)

        header_edit = ttk.Frame(header_frame)
        header_edit.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        header_edit.columnconfigure(3, weight=1)
        ttk.Label(header_edit, text="Selected field").grid(row=0, column=0, sticky="w")
        ttk.Entry(header_edit, textvariable=self.header_field_var, state="readonly", width=24).grid(
            row=0, column=1, padx=(6, 14)
        )
        ttk.Label(header_edit, text="Scrubbed value").grid(row=0, column=2, sticky="w")
        self.header_value_entry = ttk.Entry(header_edit, textvariable=self.header_value_var)
        self.header_value_entry.grid(row=0, column=3, sticky="ew", padx=(6, 8))
        ttk.Button(header_edit, text="Apply Header Edit", command=self.apply_header_edit).grid(
            row=0, column=4
        )

        annotation_frame = ttk.LabelFrame(content, text="Annotations", padding=8)
        annotation_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        annotation_frame.columnconfigure(0, weight=1)
        annotation_frame.columnconfigure(1, weight=1)
        annotation_frame.rowconfigure(0, weight=1)

        self.raw_annotation_tree = self.make_annotation_tree(annotation_frame, "Raw EDF annotations")
        self.raw_annotation_tree.master.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        scrubbed_panel = ttk.LabelFrame(annotation_frame, text="Scrubbed EDF annotations", padding=6)
        scrubbed_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        scrubbed_panel.columnconfigure(0, weight=1)
        scrubbed_panel.rowconfigure(0, weight=1)
        self.scrubbed_annotation_tree = ttk.Treeview(
            scrubbed_panel,
            columns=("onset", "duration", "description"),
            show="headings",
            selectmode="browse",
        )
        for column, heading, width in (
            ("onset", "Onset", 90),
            ("duration", "Duration", 90),
            ("description", "Description", 330),
        ):
            self.scrubbed_annotation_tree.heading(column, text=heading)
            self.scrubbed_annotation_tree.column(column, width=width, anchor="w")
        self.scrubbed_annotation_tree.grid(row=0, column=0, sticky="nsew")
        ann_scroll = ttk.Scrollbar(scrubbed_panel, orient="vertical", command=self.scrubbed_annotation_tree.yview)
        ann_scroll.grid(row=0, column=1, sticky="ns")
        self.scrubbed_annotation_tree.configure(yscrollcommand=ann_scroll.set)

        ann_actions = ttk.Frame(scrubbed_panel)
        ann_actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        ttk.Button(ann_actions, text="Add", command=self.add_annotation).pack(side="left")
        ttk.Button(ann_actions, text="Edit", command=self.edit_annotation).pack(side="left", padx=(6, 0))
        ttk.Button(ann_actions, text="Remove", command=self.remove_annotation).pack(side="left", padx=(6, 0))

        footer = ttk.Frame(root)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(footer, textvariable=self.status_var).pack(side="left")
        ttk.Button(footer, text="Save Scrubbed EDF", command=self.save_current).pack(side="right")
        ttk.Button(footer, text="Back to Electrophysiology", command=self._close_page).pack(side="right", padx=(0, 8))

    def make_annotation_tree(self, parent: tk.Widget, title: str) -> ttk.Treeview:
        panel = ttk.LabelFrame(parent, text=title, padding=6)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            panel,
            columns=("onset", "duration", "description"),
            show="headings",
            selectmode="browse",
        )
        for column, heading, width in (
            ("onset", "Onset", 90),
            ("duration", "Duration", 90),
            ("description", "Description", 330),
        ):
            tree.heading(column, text=heading)
            tree.column(column, width=width, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(panel, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)
        return tree

    def populate_file_list(self) -> None:
        for pair in self.pairs:
            self.file_list.insert("end", pair["label"])
        if not self.pairs:
            self.status_var.set("No matching raw and scrubbed EDF pairs were found.")
            return
        self.file_list.selection_set(0)
        self.file_list.activate(0)
        self.load_pair(0)

    def on_file_selected(self, _event: tk.Event) -> None:
        selected = self.file_list.curselection()
        if selected:
            self.load_pair(int(selected[0]))

    def load_pair(self, index: int) -> None:
        pair = self.pairs[index]
        try:
            self.current_data = {
                "raw": self.helpers.read_review_data(pair["raw_path"]),
                "scrubbed": self.helpers.read_review_data(pair["scrubbed_path"]),
            }
        except Exception as exc:
            messagebox.showerror("Could not load EDF", str(exc), parent=self)
            return
        self.current_pair_index = index
        self.populate_header_tree()
        self.populate_annotations()
        self.status_var.set(str(pair["label"]))

    @staticmethod
    def display_value(value: object) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return "" if value is None else str(value)

    def populate_header_tree(self) -> None:
        for item in self.header_tree.get_children():
            self.header_tree.delete(item)
        if self.current_data is None:
            return
        raw_header = self.current_data["raw"]["header"]
        scrubbed_header = self.current_data["scrubbed"]["header"]
        keys = sorted(set(raw_header) | set(scrubbed_header))
        for key in keys:
            editable = "Yes" if key in self.helpers.EDITABLE_HEADER_FIELDS else "No"
            self.header_tree.insert(
                "",
                "end",
                iid=f"header-{key}",
                values=(
                    key,
                    self.display_value(raw_header.get(key)),
                    self.display_value(scrubbed_header.get(key)),
                    editable,
                ),
            )

    def on_header_selected(self, _event: tk.Event) -> None:
        selected = self.header_tree.selection()
        if not selected or self.current_data is None:
            return
        values = self.header_tree.item(selected[0], "values")
        field = str(values[0])
        self.header_field_var.set(field)
        self.header_value_var.set(self.display_value(self.current_data["scrubbed"]["header"].get(field)))
        state = "normal" if field in self.helpers.EDITABLE_HEADER_FIELDS else "disabled"
        self.header_value_entry.configure(state=state)

    def apply_header_edit(self) -> None:
        field = self.header_field_var.get()
        if not field or self.current_data is None:
            return
        if field not in self.helpers.EDITABLE_HEADER_FIELDS:
            messagebox.showinfo("Read-only field", "This header field is read-only.", parent=self)
            return
        self.current_data["scrubbed"]["header"][field] = self.header_value_var.get()
        item_id = f"header-{field}"
        values = list(self.header_tree.item(item_id, "values"))
        values[2] = self.header_value_var.get()
        self.header_tree.item(item_id, values=values)
        self.status_var.set("Header edit applied in memory. Click Save Scrubbed EDF to write it.")

    def populate_annotations(self) -> None:
        for tree in (self.raw_annotation_tree, self.scrubbed_annotation_tree):
            for item in tree.get_children():
                tree.delete(item)
        if self.current_data is None:
            return
        for tree, key in (
            (self.raw_annotation_tree, "raw"),
            (self.scrubbed_annotation_tree, "scrubbed"),
        ):
            for index, row in enumerate(self.current_data[key]["annotations"]):
                tree.insert(
                    "",
                    "end",
                    iid=f"{key}-annotation-{index}",
                    values=(row["onset"], row["duration"], row["description"]),
                )

    def prompt_annotation(self, initial: Optional[Dict[str, object]] = None) -> Optional[Dict[str, object]]:
        initial = initial or {"onset": 0, "duration": 0, "description": ""}
        onset = simpledialog.askfloat("Annotation onset", "Onset in seconds:", initialvalue=float(initial["onset"]), parent=self)
        if onset is None:
            return None
        duration = simpledialog.askfloat("Annotation duration", "Duration in seconds:", initialvalue=float(initial["duration"]), parent=self)
        if duration is None:
            return None
        description = simpledialog.askstring("Annotation description", "Description:", initialvalue=str(initial["description"]), parent=self)
        if description is None:
            return None
        return {"onset": onset, "duration": duration, "description": description}

    def add_annotation(self) -> None:
        if self.current_data is None:
            return
        row = self.prompt_annotation()
        if row is not None:
            self.current_data["scrubbed"]["annotations"].append(row)
            self.populate_annotations()

    def selected_scrubbed_annotation_index(self) -> Optional[int]:
        selected = self.scrubbed_annotation_tree.selection()
        if not selected:
            messagebox.showinfo("No annotation selected", "Select a scrubbed annotation first.", parent=self)
            return None
        return int(selected[0].rsplit("-", 1)[1])

    def edit_annotation(self) -> None:
        if self.current_data is None:
            return
        index = self.selected_scrubbed_annotation_index()
        if index is None:
            return
        updated = self.prompt_annotation(self.current_data["scrubbed"]["annotations"][index])
        if updated is not None:
            self.current_data["scrubbed"]["annotations"][index] = updated
            self.populate_annotations()

    def remove_annotation(self) -> None:
        if self.current_data is None:
            return
        index = self.selected_scrubbed_annotation_index()
        if index is None:
            return
        del self.current_data["scrubbed"]["annotations"][index]
        self.populate_annotations()

    def save_current(self) -> None:
        if self.current_data is None or self.current_pair_index is None:
            return
        pair = self.pairs[self.current_pair_index]
        try:
            self.helpers.rewrite_scrubbed_edf(
                pair["scrubbed_path"],
                self.current_data["scrubbed"]["header"],
                self.current_data["scrubbed"]["annotations"],
            )
            self.load_pair(self.current_pair_index)
            self.status_var.set("Saved scrubbed EDF successfully.")
        except Exception as exc:
            messagebox.showerror("Could not save scrubbed EDF", str(exc), parent=self)





class BIDSMetadataWindow(ttk.Frame):
    """Embedded page for scrubbed EDF metadata review and BIDS conversion."""

    RECORDING_MODALITY_TO_DATATYPE = {
        "Scalp EEG": "eeg",
        "Stereo EEG (SEEG)": "ieeg",
        "Subdural grid": "ieeg",
        "Subdural strips": "ieeg",
        "Depth electrodes (not SEEG)": "ieeg",
        "Intraoperative electrocorticography (ECoG)": "ieeg",
        "Magnetoencephalography (MEG)": "meg",
    }

    DERIVED_FIELDS = {
        "Recording Duration (hours)",
    }

    def __init__(
        self,
        parent: "PipelineDashboard",
        scrubbed_dir: Path,
        output_dir: Path,
        overwrite: bool,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.parent_dashboard = parent
        self.on_close = on_close
        self.scrubbed_dir = scrubbed_dir
        self.output_dir = output_dir
        self.overwrite = overwrite

        self.metadata_dictionary = load_dictionary(
            METADATA_DICTIONARY
        )
        self.metadata_validator = MetadataValidator(
            self.metadata_dictionary
        )
        self.metadata_rules = (
            self.metadata_dictionary["tables"]["Electrophysiology"]["fields"]
        )

        self.metadata_store = LocalMetadataStore()
        self.repository = MetadataRepository()
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
        self.site_var = tk.StringVar(
            value=f"Site: {self.site_id}"
        )

        self._build_interface()
        self._load_scrubbed_files()
        self._refresh_conditional_fields()

    def _close_page(self) -> None:
        if self.on_close is not None:
            self.on_close()
        else:
            self.destroy()

    # ------------------------------------------------------------------
    # Site
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
            "Enter the Site ID for this local installation.",
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
            metadata[
                "Clinical Assessment ID"
            ] = ""
            record[
                "metadata_confirmed"
            ] = False
            record[
                "status"
            ] = self._record_status(
                record
            )

        self._refresh_all_rows()

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    def _build_interface(self) -> None:
        root = ttk.Frame(
            self,
            padding=14,
        )
        root.pack(
            fill="both",
            expand=True,
        )
        root.columnconfigure(
            0,
            weight=1,
        )
        root.rowconfigure(
            2,
            weight=1,
            minsize=190,
        )
        root.rowconfigure(
            3,
            weight=3,
            minsize=420,
        )

        header = ttk.Frame(root)
        header.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        header.columnconfigure(
            0,
            weight=1,
        )

        ttk.Label(
            header,
            text="Electrophysiology Metadata & BIDS Review",
            font=("", 18, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            header,
            textvariable=self.site_var,
        ).grid(
            row=0,
            column=1,
            sticky="e",
            padx=(10, 8),
        )

        ttk.Button(
            header,
            text="Change Site",
            command=self._change_site,
        ).grid(
            row=0,
            column=2,
            sticky="e",
        )

        ttk.Button(
            header,
            text="Back to Electrophysiology",
            command=self._close_page,
        ).grid(
            row=0,
            column=3,
            sticky="e",
            padx=(8, 0),
        )

        ttk.Label(
            root,
            text=(
                "CoCANoT fields below come from the active machine-readable "
                "Electrophysiology dictionary. Project, Project Description, "
                "and Session ID control dataset organization."
            ),
            wraplength=1500,
        ).grid(
            row=1,
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
        table.columnconfigure(
            0,
            weight=1,
        )
        table.rowconfigure(
            0,
            weight=1,
        )

        columns = (
            "include",
            "file",
            "project",
            "patient",
            "recording",
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
            "recording": "Recording ID",
            "surgery": "Surgery ID",
            "modality": "Recording Modality",
        }
        widths = {
            "include": 70,
            "file": 420,
            "project": 170,
            "patient": 180,
            "recording": 150,
            "surgery": 140,
            "modality": 250,
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
            "<<TreeviewSelect>>",
            self._selected_record_changed,
        )
        self.tree.bind(
            "<Double-1>",
            self._toggle_at_pointer,
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
        self.tree_selection = ExtendedSelectionController(
            self.tree
        )

        shell = ttk.Frame(root)
        shell.grid(
            row=3,
            column=0,
            sticky="nsew",
            pady=(10, 0),
        )
        shell.columnconfigure(
            0,
            weight=1,
        )
        shell.rowconfigure(
            0,
            weight=1,
        )

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
        self.metadata_body.columnconfigure(
            0,
            weight=1,
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

        cocanot = ttk.LabelFrame(
            self.metadata_body,
            text="CoCANoT Electrophysiology Metadata",
            padding=12,
        )
        cocanot.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        cocanot.columnconfigure(
            0,
            weight=1,
        )

        ttk.Label(
            cocanot,
            text=(
                "Requiredness, input type, allowed values, conditional fields, "
                "prompts, and help text come from MR Electrophysiology. "
                "Clinical Assessment ID is assigned automatically."
            ),
            wraplength=1450,
        ).grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 8),
        )

        self.cocanot_form = ttk.Frame(
            cocanot
        )
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

        organization = ttk.LabelFrame(
            self.metadata_body,
            text="Dataset Organization",
            padding=12,
        )
        organization.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )
        organization.columnconfigure(
            1,
            weight=1,
        )
        organization.columnconfigure(
            3,
            weight=1,
        )

        self._add_entry(
            organization,
            0,
            0,
            "Project *",
            self.project_var,
        )
        self._add_entry(
            organization,
            0,
            2,
            "Session ID *",
            self.session_var,
        )
        self._add_entry(
            organization,
            1,
            0,
            "Project Description",
            self.project_description_var,
            columnspan=3,
        )

        ttk.Label(
            organization,
            text=(
                "Project and Session ID are required for dataset organization. "
                "Project Description is optional. The BIDS subject label is "
                "derived from CoCANoT Patient ID."
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
        ).pack(
            side="left",
        )
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
        ).pack(
            side="right",
        )

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
        entry = ttk.Entry(
            parent,
            textvariable=variable,
        )
        entry.grid(
            row=row,
            column=column + 1,
            columnspan=columnspan,
            sticky="ew",
            padx=(6, 14),
            pady=(4, 2),
        )
        return entry

    def _scroll_metadata_with_wheel(
        self,
        event: tk.Event,
    ) -> Optional[str]:
        pointer = self.winfo_containing(
            self.winfo_pointerx(),
            self.winfo_pointery(),
        )

        if not self._widget_in_metadata(
            pointer
        ):
            return None

        if type(pointer) in {
            tk.Listbox,
            tk.Text,
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

        self.metadata_canvas.yview_scroll(
            units,
            "units",
        )
        return "break"

    def _widget_in_metadata(
        self,
        widget: Optional[tk.Widget],
    ) -> bool:
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
    # Dictionary form
    # ------------------------------------------------------------------

    def _build_cocanot_form(self) -> None:
        row_index = 0

        for rule in self.metadata_rules:
            field_name = str(
                rule["field_name"]
            )

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
            elif rule.get(
                "required_if_field"
            ):
                marker = " * when applicable"
            else:
                marker = ""

            ttk.Label(
                frame,
                text=str(
                    rule["ui_prompt"]
                ) + marker,
                wraplength=470,
            ).grid(
                row=0,
                column=0,
                sticky="nw",
                padx=(0, 8),
            )

            help_text = str(
                rule.get(
                    "help_text"
                )
                or ""
            ).strip()

            if help_text:
                ttk.Button(
                    frame,
                    text="?",
                    width=3,
                    command=lambda item=rule: (
                        self._show_help(
                            item
                        )
                    ),
                ).grid(
                    row=0,
                    column=2,
                    sticky="n",
                    padx=(6, 0),
                )

            control: Dict[str, object] = {
                "frame": frame,
                "rule": rule,
            }

            if field_name in self.DERIVED_FIELDS:
                ttk.Label(
                    frame,
                    text="Automatically extracted from the EDF",
                ).grid(
                    row=0,
                    column=1,
                    sticky="w",
                )
                control[
                    "derived"
                ] = True
                self.metadata_controls[
                    field_name
                ] = control
                continue

            input_type = str(
                rule["input_type"]
            )

            if input_type in {
                "identifier",
                "free_text",
                "numeric",
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

                control[
                    "variable"
                ] = variable
                control[
                    "widget"
                ] = widget

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

                control[
                    "variable"
                ] = variable
                control[
                    "widget"
                ] = widget

            elif input_type == "multi_select":
                container = ttk.Frame(
                    frame
                )
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
                        max(
                            len(values),
                            4,
                        ),
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

                control[
                    "widget"
                ] = listbox

            self.metadata_controls[
                field_name
            ] = control

    def _show_help(
        self,
        rule: Dict[str, object],
    ) -> None:
        messagebox.showinfo(
            str(
                rule["field_name"]
            ),
            str(
                rule.get(
                    "help_text"
                )
                or ""
            ),
            parent=self,
        )

    def _metadata_selection_changed(
        self,
        _event: Optional[tk.Event] = None,
    ) -> None:
        self._metadata_value_changed()

    def _metadata_value_changed(self) -> None:
        self._refresh_conditional_fields()

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

            if field_name in self.DERIVED_FIELDS:
                continue

            control = self.metadata_controls[
                field_name
            ]

            if rule[
                "input_type"
            ] == "multi_select":
                listbox = control[
                    "widget"
                ]
                values[
                    field_name
                ] = [
                    str(
                        listbox.get(
                            index
                        )
                    )
                    for index in listbox.curselection()
                ]
            else:
                values[
                    field_name
                ] = (
                    control[
                        "variable"
                    ].get().strip()
                )

        return values

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
                rule[
                    "required_if_operator"
                ],
                rule[
                    "required_if_value"
                ],
            )

            if applies:
                frame.grid()
            else:
                frame.grid_remove()

    # ------------------------------------------------------------------
    # EDF records
    # ------------------------------------------------------------------

    @staticmethod
    def _matching_sidecar(
        edf_path: Path,
    ) -> Optional[Path]:
        candidate = edf_path.with_suffix(
            ".json"
        )
        return (
            candidate
            if candidate.exists()
            else None
        )

    @staticmethod
    def _recording_duration_hours(
        edf_path: Path,
    ) -> object:
        try:
            import pyedflib

            reader = pyedflib.EdfReader(
                str(edf_path)
            )
            try:
                return round(
                    float(
                        reader.file_duration
                    )
                    / 3600.0,
                    8,
                )
            finally:
                reader.close()
        except Exception:
            return ""

    def _load_scrubbed_files(
        self,
    ) -> None:
        edf_files = sorted(
            path
            for path in self.scrubbed_dir.rglob(
                "*"
            )
            if path.is_file()
            and path.suffix.lower() == ".edf"
        )

        for index, edf_path in enumerate(
            edf_files,
            start=1,
        ):
            item_id = f"record-{index}"
            sidecar = self._matching_sidecar(
                edf_path
            )
            duration = (
                self._recording_duration_hours(
                    edf_path
                )
            )

            metadata: Dict[str, object] = {
                "Recording Duration (hours)": duration,
            }

            self.records[
                item_id
            ] = {
                "edf_path": str(
                    edf_path.resolve()
                ),
                "sidecar_path": (
                    str(
                        sidecar.resolve()
                    )
                    if sidecar
                    else ""
                ),
                "source_label": str(
                    edf_path.relative_to(
                        self.scrubbed_dir
                    )
                ),
                "include": "Yes",
                "project": "",
                "project_description": "",
                "session_id": "",
                "cocanot_metadata": metadata,
                "metadata_confirmed": False,
                "status": "Missing metadata",
            }
            self._refresh_row(
                item_id
            )

        if self.records:
            first = next(
                iter(
                    self.records
                )
            )
            self.tree.selection_set(
                first
            )
            self.tree.focus(
                first
            )
            self.tree_selection.anchor = first
            self._selected_record_changed()

    def _refresh_row(
        self,
        item_id: str,
    ) -> None:
        record = self.records[
            item_id
        ]
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
                "Recording ID",
                "",
            ),
            metadata.get(
                "Surgery ID",
                "",
            ),
            metadata.get(
                "Recording Modality",
                "",
            ),
        )

        if self.tree.exists(
            item_id
        ):
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

    def _refresh_all_rows(
        self,
    ) -> None:
        for item_id in self.records:
            self._refresh_row(
                item_id
            )

    def _selected_record_changed(
        self,
        _event: Optional[tk.Event] = None,
    ) -> None:
        selected = list(
            self.tree.selection()
        )

        if not selected:
            return

        record = self.records[
            selected[0]
        ]
        self._load_record_into_form(
            record
        )

    def _load_record_into_form(
        self,
        record: Dict[str, object],
    ) -> None:
        metadata = record.get(
            "cocanot_metadata",
            {},
        )

        for rule in self.metadata_rules:
            field_name = str(
                rule["field_name"]
            )

            if (
                rule["system_generated"]
                or field_name in self.DERIVED_FIELDS
            ):
                continue

            control = self.metadata_controls[
                field_name
            ]
            value = metadata.get(
                field_name,
                "",
            )

            if rule[
                "input_type"
            ] == "multi_select":
                listbox = control[
                    "widget"
                ]
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
                    if str(
                        listbox.get(
                            index
                        )
                    ) in selected_values:
                        listbox.selection_set(
                            index
                        )
            else:
                control[
                    "variable"
                ].set(
                    str(
                        value
                        if value is not None
                        else ""
                    )
                )

        self.project_var.set(
            str(
                record.get(
                    "project"
                )
                or ""
            )
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
            str(
                record.get(
                    "session_id"
                )
                or ""
            )
        )
        self._refresh_conditional_fields()

    # ------------------------------------------------------------------
    # Validation and application
    # ------------------------------------------------------------------

    def _draft_metadata_for_validation(
        self,
        metadata: Dict[str, object],
    ) -> Dict[str, object]:
        draft = dict(
            metadata
        )

        if not draft.get(
            "Clinical Assessment ID"
        ):
            draft[
                "Clinical Assessment ID"
            ] = "PENDING"

        if not draft.get(
            "Recording Duration (hours)"
        ):
            draft[
                "Recording Duration (hours)"
            ] = 1

        return draft

    def _record_status(
        self,
        record: Dict[str, object],
    ) -> str:
        if record.get(
            "include"
        ) != "Yes":
            return "Excluded"

        if not str(
            record.get(
                "project"
            )
            or ""
        ).strip():
            return "Missing project"

        if not str(
            record.get(
                "session_id"
            )
            or ""
        ).strip():
            return "Missing session"

        metadata = record.get(
            "cocanot_metadata",
            {},
        )

        validation = (
            self.metadata_validator.validate_record(
                "Electrophysiology",
                self._draft_metadata_for_validation(
                    metadata
                ),
            )
        )

        for result in validation[
            "results"
        ]:
            if result["status"] in {
                "invalid",
                "missing_required",
            }:
                return (
                    f"{result['field_name']}: "
                    f"{result['message']}"
                )

        modality = str(
            metadata.get(
                "Recording Modality"
            )
            or ""
        )

        if modality in {
            "Other",
            "Unknown",
        }:
            return (
                "Recording Modality must identify a "
                "BIDS EEG, iEEG, or MEG datatype."
            )

        if modality == (
            "Magnetoencephalography (MEG)"
        ):
            return (
                "MEG requires the native acquisition format."
            )

        return "Ready"

    def _apply_to_selected(
        self,
    ) -> None:
        selected = list(
            self.tree.selection()
        )

        if not selected:
            messagebox.showinfo(
                "No selection",
                "Select one or more recordings first.",
                parent=self,
            )
            return

        common_metadata = (
            self._current_cocanot_metadata()
        )

        test_metadata = dict(
            common_metadata
        )
        test_metadata[
            "Recording Duration (hours)"
        ] = 1

        validation = (
            self.metadata_validator.validate_record(
                "Electrophysiology",
                self._draft_metadata_for_validation(
                    test_metadata
                ),
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
            messagebox.showerror(
                "Missing or invalid metadata",
                "\n".join(
                    f"{item['field_name']}: {item['message']}"
                    for item in problems[:12]
                ),
                parent=self,
            )
            return

        project = (
            self.project_var.get().strip()
        )
        session_id = (
            self.session_var.get().strip()
        )

        if not project:
            messagebox.showerror(
                "Missing project",
                "Project is required.",
                parent=self,
            )
            return

        if not session_id:
            messagebox.showerror(
                "Missing session",
                "Session ID is required.",
                parent=self,
            )
            return

        for item_id in selected:
            record = self.records[
                item_id
            ]
            duration = record[
                "cocanot_metadata"
            ].get(
                "Recording Duration (hours)",
                "",
            )
            metadata = dict(
                common_metadata
            )
            metadata[
                "Recording Duration (hours)"
            ] = duration
            metadata[
                "Clinical Assessment ID"
            ] = ""

            record[
                "cocanot_metadata"
            ] = metadata
            record[
                "project"
            ] = project
            record[
                "project_description"
            ] = (
                self.project_description_var.get().strip()
            )
            record[
                "session_id"
            ] = session_id
            record[
                "metadata_confirmed"
            ] = False
            record[
                "status"
            ] = self._record_status(
                record
            )
            self._refresh_row(
                item_id
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
                "Select one or more recordings first.",
                parent=self,
            )
            return

        for item_id in selected:
            record = self.records[
                item_id
            ]
            record[
                "include"
            ] = (
                "Yes"
                if included
                else "No"
            )
            record[
                "status"
            ] = self._record_status(
                record
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
        record[
            "include"
        ] = (
            "No"
            if record[
                "include"
            ] == "Yes"
            else "Yes"
        )
        record[
            "status"
        ] = self._record_status(
            record
        )
        self._refresh_row(
            item_id
        )

    # ------------------------------------------------------------------
    # Clinical assessment
    # ------------------------------------------------------------------

    def _resolve_clinical_assessments(
        self,
        included: List[
            Dict[str, object]
        ],
    ) -> bool:
        patient_ids = sorted({
            str(
                record[
                    "cocanot_metadata"
                ].get(
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
                    set(
                        patient_ids
                    ),
                )
            except ValueError as exc:
                messagebox.showerror(
                    "Clinical upload error",
                    str(
                        exc
                    ),
                    parent=self,
                )
                return False

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

            resolved[
                patient_id
            ] = assessment_id

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
            ] = resolved[
                patient_id
            ]

        return True

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    def _review_and_convert(
        self,
    ) -> None:
        included = [
            record
            for record in self.records.values()
            if record[
                "include"
            ] == "Yes"
        ]

        if not included:
            messagebox.showerror(
                "Nothing included",
                "Include at least one recording.",
                parent=self,
            )
            return

        problems = []

        for record in included:
            status = self._record_status(
                record
            )
            record[
                "status"
            ] = status

            if status != "Ready":
                problems.append(
                    f"{record['source_label']}: {status}"
                )

        self._refresh_all_rows()

        if problems:
            messagebox.showerror(
                "Incomplete metadata",
                "Complete the metadata for:\n\n"
                + "\n".join(
                    problems[:20]
                ),
                parent=self,
            )
            return

        if not self._resolve_clinical_assessments(
            included
        ):
            return

        for record in included:
            validation = (
                self.metadata_validator.validate_record(
                    "Electrophysiology",
                    record[
                        "cocanot_metadata"
                    ],
                )
            )

            bad = [
                result
                for result in validation[
                    "results"
                ]
                if result[
                    "status"
                ] in {
                    "invalid",
                    "missing_required",
                }
            ]

            if bad:
                messagebox.showerror(
                    "Metadata validation failed",
                    (
                        f"{record['source_label']}\n\n"
                        + "\n".join(
                            f"{item['field_name']}: "
                            f"{item['message']}"
                            for item in bad[:12]
                        )
                    ),
                    parent=self,
                )
                return

        if not messagebox.askyesno(
            "Confirm metadata",
            (
                f"{len(included)} recording"
                f"{'' if len(included) == 1 else 's'} passed "
                "automatic validation.\n\n"
                "Continue with BIDS conversion?"
            ),
            parent=self,
        ):
            return

        manifest_path = (
            self.scrubbed_dir.parent
            / "bids_conversion_manifest.json"
        )

        payload = {
            "bids_version": "1.11.1",
            "records": [],
        }

        for record in included:
            payload[
                "records"
            ].append({
                "edf_path": record[
                    "edf_path"
                ],
                "sidecar_path": record[
                    "sidecar_path"
                ],
                "site_id": self.site_id,
                "project": record[
                    "project"
                ],
                "project_description": record[
                    "project_description"
                ],
                "session_id": record[
                    "session_id"
                ],
                "cocanot_metadata": record[
                    "cocanot_metadata"
                ],
                "metadata_confirmed": True,
            })

        manifest_path.write_text(
            json.dumps(
                payload,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        command = [
            sys.executable,
            "-u",
            str(
                BIDS_CONVERTER_SCRIPT
            ),
            "--manifest",
            str(
                manifest_path
            ),
            "--output-dir",
            str(
                self.output_dir
            ),
        ]

        if self.overwrite:
            command.append(
                "--overwrite"
            )

        self.parent_dashboard.run_command(
            command,
            "BIDS conversion",
            on_success=lambda: self._bids_conversion_succeeded(
                included
            ),
        )

    def _bids_conversion_succeeded(
        self,
        included: List[Dict[str, object]],
    ) -> None:
        """Persist successfully converted Ephys metadata for Patient Review."""
        records_to_save = []

        for record in included:
            metadata = dict(
                record.get(
                    "cocanot_metadata",
                    {},
                )
            )

            context = {
                "project": str(
                    record.get(
                        "project",
                        "",
                    )
                    or ""
                ),
                "project_description": str(
                    record.get(
                        "project_description",
                        "",
                    )
                    or ""
                ),
                "session_id": str(
                    record.get(
                        "session_id",
                        "",
                    )
                    or ""
                ),
                "source_label": str(
                    record.get(
                        "source_label",
                        "",
                    )
                    or ""
                ),
                "edf_path": str(
                    record.get(
                        "edf_path",
                        "",
                    )
                    or ""
                ),
                "sidecar_path": str(
                    record.get(
                        "sidecar_path",
                        "",
                    )
                    or ""
                ),
                "bids_output_dir": str(
                    self.output_dir
                ),
            }

            records_to_save.append({
                "metadata": metadata,
                "context": context,
            })

        try:
            saved = self.repository.save_records(
                self.site_id,
                "Electrophysiology",
                records_to_save,
                source="electrophysiology_pipeline",
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror(
                "BIDS completed, metadata save failed",
                (
                    "The BIDS conversion completed successfully, but "
                    "the Electrophysiology records could not be saved "
                    "to CoCANoT Metadata Management.\n\n"
                    f"{exc}"
                ),
                parent=self,
            )
            return

        messagebox.showinfo(
            "Electrophysiology saved",
            (
                f"BIDS conversion completed and {len(saved)} "
                "Electrophysiology record"
                f"{'' if len(saved) == 1 else 's'} "
                "were saved to Metadata Management."
            ),
            parent=self,
        )

        self._close_page()


class PipelineDashboard(ttk.Frame):
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
        self.worker_thread: threading.Thread | None = None
        self.pipeline_busy = False
        self.log_history: List[str] = []
        self.raw_records: Dict[str, Dict[str, str]] = {}

        saved = self.read_saved_settings()
        eeg = saved.get("electrophysiology", {})
        saved_input_dirs = eeg.get("input_dirs") or ([eeg.get("input_dir")] if eeg.get("input_dir") else [])
        self.input_dirs: List[str] = [str(Path(path).expanduser()) for path in saved_input_dirs if path]

        self.derivatives_dir_var = tk.StringVar(value=str(eeg.get("derivatives_dir", "")))
        self.bids_output_dir_var = tk.StringVar(value=str(eeg.get("bids_output_dir", "")))
        self.overwrite_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")

        self.after(100, self.process_output_queue)

        if self.initial_view == "processing":
            self.show_processing()
        else:
            self.show_home()

    def clear_window(self) -> None:
        for child in self.winfo_children():
            child.destroy()

    def is_pipeline_running(self) -> bool:
        """Return True only while a worker/process is actually active."""
        process_running = (
            self.running_process is not None
            and self.running_process.poll() is None
        )
        worker_running = (
            self.worker_thread is not None
            and self.worker_thread.is_alive()
        )

        if process_running or worker_running:
            self.pipeline_busy = True
            return True

        self.pipeline_busy = False
        self.running_process = None
        self.worker_thread = None
        return False

    def _widget_exists(self, widget) -> bool:
        try:
            return widget is not None and bool(widget.winfo_exists())
        except (AttributeError, tk.TclError):
            return False

    def _configure_if_alive(self, widget, **kwargs) -> None:
        if self._widget_exists(widget):
            try:
                widget.configure(**kwargs)
            except tk.TclError:
                pass

    def show_home(self) -> None:
        if self.is_pipeline_running():
            messagebox.showwarning(
                "Pipeline busy",
                (
                    "Finish or stop the current operation before "
                    "leaving the processing screen."
                ),
                parent=self,
            )
            return

        self.clear_window()

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
                command=self.return_to_cocanot,
            ).pack(side="left")

        home = EphysHome(
            page,
            on_process=self.show_processing,
            on_review_patients=self.open_patient_explorer,
        )
        home.grid(
            row=1,
            column=0,
            sticky="nsew",
        )

    def show_processing(self) -> None:
        self.clear_window()
        self.build_interface()
        self.refresh_folder_list()
        self.scan_input_sources()

        if self.is_pipeline_running():
            self.set_controls_enabled(False)
            self._configure_if_alive(
                getattr(self, "stop_button", None),
                state="normal",
            )

    def leave_processing(self) -> None:
        if self.is_pipeline_running():
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

        self.show_home()

    def open_patient_explorer(self) -> None:
        if self.is_pipeline_running():
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

    def return_to_cocanot(self) -> None:
        if self.is_pipeline_running():
            messagebox.showwarning(
                "Pipeline busy",
                (
                    "Finish or stop the current operation before "
                    "leaving Electrophysiology."
                ),
                parent=self,
            )
            return

        if self.on_back is not None:
            self.on_back()

    def read_saved_settings(self) -> dict:
        try:
            return load_settings_dict()
        except PipelineConfigError as exc:
            messagebox.showwarning("Settings warning", str(exc))
            return {"electrophysiology": {}}

    def build_interface(self) -> None:
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
            text="Electrophysiology DeID Dashboard",
            font=("", 22, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Button(
            root,
            text="Back",
            command=self.leave_processing,
        ).grid(
            row=0,
            column=1,
            sticky="e",
            padx=(12, 0),
        )

        ttk.Label(
            root,
            text=(
                "Add EDF files or folders, choose the recordings to process, "
                "scrub headers, review, and convert accepted files to BIDS."
            ),
            wraplength=1300,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(4, 12),
        )

        source_frame = ttk.LabelFrame(
            root,
            text="Raw EDF Sources",
            padding=12,
        )
        source_frame.grid(
            row=2,
            column=0,
            sticky="ew",
        )
        source_frame.columnconfigure(
            0,
            weight=1,
        )

        self.folder_list = tk.Listbox(
            source_frame,
            height=4,
            selectmode="extended",
        )
        self.folder_list.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        self.folder_selection = ExtendedSelectionController(
            self.folder_list
        )

        source_buttons = ttk.Frame(
            source_frame
        )
        source_buttons.grid(
            row=0,
            column=1,
            sticky="ns",
            padx=(8, 0),
        )

        self.add_file_button = ttk.Button(
            source_buttons,
            text="Add EDF Files…",
            command=self.add_input_files,
        )
        self.add_file_button.pack(
            fill="x",
        )

        self.add_folder_button = ttk.Button(
            source_buttons,
            text="Add EDF Folders…",
            command=self.add_input_folder,
        )
        self.add_folder_button.pack(
            fill="x",
            pady=(6, 0),
        )

        self.remove_folder_button = ttk.Button(
            source_buttons,
            text="Remove Selected",
            command=self.remove_input_folders,
        )
        self.remove_folder_button.pack(
            fill="x",
            pady=(6, 0),
        )

        selection_frame = ttk.LabelFrame(
            root,
            text="Raw EDF Files",
            padding=8,
        )
        selection_frame.grid(
            row=3,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )
        selection_frame.columnconfigure(
            0,
            weight=1,
        )

        columns = (
            "include",
            "file",
            "source",
        )
        self.raw_tree = ttk.Treeview(
            selection_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            height=14,
        )

        for column, heading, width in (
            (
                "include",
                "Include",
                80,
            ),
            (
                "file",
                "File Name",
                650,
            ),
            (
                "source",
                "Source",
                420,
            ),
        ):
            self.raw_tree.heading(
                column,
                text=heading,
            )
            self.raw_tree.column(
                column,
                width=width,
                anchor="w",
            )

        self.raw_tree.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        self.raw_tree.bind(
            "<Double-1>",
            self.toggle_raw_inclusion_at_pointer,
        )

        raw_y = ttk.Scrollbar(
            selection_frame,
            orient="vertical",
            command=self.raw_tree.yview,
        )
        raw_y.grid(
            row=0,
            column=1,
            sticky="ns",
        )

        raw_x = ttk.Scrollbar(
            selection_frame,
            orient="horizontal",
            command=self.raw_tree.xview,
        )
        raw_x.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        self.raw_tree.configure(
            yscrollcommand=raw_y.set,
            xscrollcommand=raw_x.set,
        )
        self.raw_tree_selection = ExtendedSelectionController(
            self.raw_tree
        )

        raw_actions = ttk.Frame(
            selection_frame
        )
        raw_actions.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )

        ttk.Button(
            raw_actions,
            text="Include Selected",
            command=lambda: self.set_raw_selected(
                True
            ),
        ).pack(
            side="left",
        )

        ttk.Button(
            raw_actions,
            text="Exclude Selected",
            command=lambda: self.set_raw_selected(
                False
            ),
        ).pack(
            side="left",
            padx=(6, 0),
        )

        ttk.Button(
            raw_actions,
            text="Include All",
            command=lambda: self.set_raw_all(
                True
            ),
        ).pack(
            side="left",
            padx=(18, 0),
        )

        ttk.Button(
            raw_actions,
            text="Exclude All",
            command=lambda: self.set_raw_all(
                False
            ),
        ).pack(
            side="left",
            padx=(6, 0),
        )

        outputs = ttk.LabelFrame(
            root,
            text="Output Folders",
            padding=12,
        )
        outputs.grid(
            row=4,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )
        outputs.columnconfigure(
            0,
            weight=1,
        )

        self.derivatives_selector = FolderSelector(
            outputs,
            "Derivatives output folder",
            self.derivatives_dir_var,
            "Select the derivatives output folder",
            PROJECT_ROOT,
        )
        self.derivatives_selector.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 8),
        )

        self.bids_selector = FolderSelector(
            outputs,
            "BIDS output folder",
            self.bids_output_dir_var,
            "Select the BIDS output folder",
            PROJECT_ROOT,
        )
        self.bids_selector.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        output_actions = ttk.Frame(
            outputs
        )
        output_actions.grid(
            row=2,
            column=0,
            sticky="ew",
            pady=(8, 0),
        )

        self.save_settings_button = ttk.Button(
            output_actions,
            text="Save Folder Settings",
            command=self.save_folder_settings,
        )
        self.save_settings_button.pack(
            side="right",
        )

        operations = ttk.LabelFrame(
            root,
            text="Pipeline Operations",
            padding=12,
        )
        operations.grid(
            row=5,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )

        for index in range(3):
            operations.columnconfigure(
                index,
                weight=1,
            )

        self.scrub_button = ttk.Button(
            operations,
            text="1. Scrub Included EDFs",
            command=self.run_scrubber,
        )
        self.scrub_button.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(0, 6),
        )

        self.compare_button = ttk.Button(
            operations,
            text="2. Review Scrubbed EDFs",
            command=self.launch_comparison,
        )
        self.compare_button.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=6,
        )

        self.bids_button = ttk.Button(
            operations,
            text="3. Select & Convert to BIDS",
            command=self.open_bids_metadata_review,
        )
        self.bids_button.grid(
            row=0,
            column=2,
            sticky="ew",
            padx=(6, 0),
        )

        self.stop_button = ttk.Button(
            operations,
            text="Stop Current Operation",
            command=self.stop_current_operation,
            state="disabled",
        )
        self.stop_button.grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(8, 0),
        )

        self.overwrite_checkbox = ttk.Checkbutton(
            operations,
            text=(
                "Overwrite existing staged, scrubbed, "
                "or exact BIDS outputs"
            ),
            variable=self.overwrite_var,
        )
        self.overwrite_checkbox.grid(
            row=2,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(8, 0),
        )

        log_frame = ttk.LabelFrame(
            root,
            text="Pipeline Log",
            padding=8,
        )
        log_frame.grid(
            row=6,
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
            height=16,
            state="disabled",
        )
        self.log_text.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        log_scroll = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log_text.yview,
        )
        log_scroll.grid(
            row=1,
            column=1,
            sticky="ns",
        )
        self.log_text.configure(
            yscrollcommand=log_scroll.set,
        )

        if self.log_history:
            self.log_text.configure(state="normal")
            self.log_text.insert(
                "1.0",
                "\n".join(self.log_history) + "\n",
            )
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        else:
            self.append_log(
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
            self.folder_list,
            self.raw_tree,
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

    def refresh_folder_list(self) -> None:
        self.folder_list.delete(
            0,
            "end",
        )

        for path in self.input_dirs:
            self.folder_list.insert(
                "end",
                path,
            )

        if self.input_dirs:
            self.folder_list.selection_set(
                0
            )
            self.folder_list.activate(
                0
            )
            self.folder_selection.anchor = 0

    def _input_initial_dir(self) -> Path:
        if not self.input_dirs:
            return PROJECT_ROOT

        first = Path(
            self.input_dirs[0]
        ).expanduser()

        if first.is_dir():
            return first

        if first.parent.is_dir():
            return first.parent

        return PROJECT_ROOT

    def add_input_files(self) -> None:
        selected = list(
            filedialog.askopenfilenames(
                parent=self,
                title="Add raw EDF files",
                initialdir=str(
                    self._input_initial_dir()
                ),
            )
        )

        selected = [
            path
            for path in selected
            if Path(
                path
            ).suffix.lower() == ".edf"
        ]

        if not selected:
            return

        existing = set(
            self.input_dirs
        )
        added = 0

        for selected_path in selected:
            resolved = str(
                Path(
                    selected_path
                )
                .expanduser()
                .resolve()
            )

            if resolved in existing:
                continue

            self.input_dirs.append(
                resolved
            )
            existing.add(
                resolved
            )
            added += 1

        self.refresh_folder_list()
        self.scan_input_sources()
        self.append_log(
            f"Added {added} raw EDF file(s)."
        )

    def add_input_folder(self) -> None:
        selected_folders = (
            MultiFolderSelectionDialog.ask_folders(
                parent=self,
                title="Add raw EDF source folders",
                initial_dir=self._input_initial_dir(),
            )
        )

        if not selected_folders:
            return

        existing = set(
            self.input_dirs
        )
        added = 0

        for selected in selected_folders:
            resolved = str(
                Path(
                    selected
                )
                .expanduser()
                .resolve()
            )

            if resolved in existing:
                continue

            self.input_dirs.append(
                resolved
            )
            existing.add(
                resolved
            )
            added += 1

        self.refresh_folder_list()
        self.scan_input_sources()
        self.append_log(
            f"Added {added} raw EDF source folder(s)."
        )

    def remove_input_folders(self) -> None:
        indices = list(
            self.folder_list.curselection()
        )

        for index in reversed(
            indices
        ):
            del self.input_dirs[
                index
            ]

        self.refresh_folder_list()
        self.scan_input_sources()

    def scan_input_sources(self) -> None:
        self.raw_records.clear()

        for item in self.raw_tree.get_children():
            self.raw_tree.delete(
                item
            )

        counter = 1

        for source_index, source_text in enumerate(
            self.input_dirs,
            start=1,
        ):
            source = Path(
                source_text
            ).expanduser().resolve()

            if source.is_file():
                if source.suffix.lower() != ".edf":
                    continue

                edf_files = [
                    source
                ]
                source_root = source.parent
                source_name = source.parent.name

            elif source.is_dir():
                edf_files = sorted(
                    path
                    for path in source.rglob(
                        "*"
                    )
                    if path.is_file()
                    and path.suffix.lower() == ".edf"
                )
                source_root = source
                source_name = source.name

            else:
                self.append_log(
                    f"Skipping missing source: {source}"
                )
                continue

            for edf_path in edf_files:
                if source.is_file():
                    relative = Path(
                        edf_path.name
                    )
                else:
                    relative = edf_path.relative_to(
                        source_root
                    )

                item_id = f"raw-{counter}"
                counter += 1

                self.raw_records[
                    item_id
                ] = {
                    "include": "Yes",
                    "source_index": str(
                        source_index
                    ),
                    "source_folder": str(
                        source_root
                    ),
                    "source_name": source_name,
                    "patient_folder": (
                        relative.parent.name
                        if relative.parent
                        != Path(".")
                        else "(folder root)"
                    ),
                    "relative_path": str(
                        relative
                    ),
                    "edf_path": str(
                        edf_path
                    ),
                }

                self.refresh_raw_row(
                    item_id
                )

        self.append_log(
            f"Loaded {len(self.raw_records)} EDF file(s) "
            f"from {len(self.input_dirs)} source(s)."
        )

        if self.raw_records:
            first_item = next(
                iter(
                    self.raw_records
                )
            )
            self.raw_tree.selection_set(
                first_item
            )
            self.raw_tree.focus(
                first_item
            )
            self.raw_tree_selection.anchor = (
                first_item
            )
            self.after_idle(
                self.raw_tree_selection.focus
            )


    def refresh_raw_row(
        self,
        item_id: str,
    ) -> None:
        record = self.raw_records[
            item_id
        ]

        values = (
            record["include"],
            Path(
                record["edf_path"]
            ).name,
            record["source_name"],
        )

        if self.raw_tree.exists(
            item_id
        ):
            self.raw_tree.item(
                item_id,
                values=values,
            )
        else:
            self.raw_tree.insert(
                "",
                "end",
                iid=item_id,
                values=values,
            )

    def set_raw_selected(self, included: bool) -> None:
        selected = self.raw_tree.selection()
        if not selected:
            messagebox.showinfo("No selection", "Select one or more EDF rows first.")
            return
        for item_id in selected:
            self.raw_records[item_id]["include"] = "Yes" if included else "No"
            self.refresh_raw_row(item_id)

    def set_raw_all(self, included: bool) -> None:
        for item_id in self.raw_records:
            self.raw_records[item_id]["include"] = "Yes" if included else "No"
            self.refresh_raw_row(item_id)

    def toggle_raw_inclusion_at_pointer(self, event: tk.Event) -> None:
        item_id = self.raw_tree.identify_row(event.y)
        if item_id:
            current = self.raw_records[item_id]["include"]
            self.raw_records[item_id]["include"] = "No" if current == "Yes" else "Yes"
            self.refresh_raw_row(item_id)

    def selected_settings_dict(self) -> dict:
        config_inputs = []

        for source_text in self.input_dirs:
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

        settings = build_settings_dict(
            input_dirs=config_inputs,
            derivatives_dir=self.derivatives_dir_var.get().strip(),
            bids_output_dir=self.bids_output_dir_var.get().strip(),
        )

        electrophysiology = settings.setdefault(
            "electrophysiology",
            {},
        )
        electrophysiology[
            "input_dirs"
        ] = list(
            self.input_dirs
        )

        return settings

    def save_folder_settings(self, show_confirmation: bool = True) -> Optional[PipelineConfig]:
        if not self.input_dirs:
            messagebox.showerror(
                "Missing sources",
                "Add at least one raw EDF file or folder.",
            )
            return None
        if not self.derivatives_dir_var.get().strip() or not self.bids_output_dir_var.get().strip():
            messagebox.showerror("Missing folders", "Select derivatives and BIDS output folders.")
            return None

        try:
            settings = self.selected_settings_dict()
            save_settings_dict(settings)
            config = load_pipeline_config()
            validate_pipeline_config(config, create_outputs=True)
        except PipelineConfigError as exc:
            messagebox.showerror("Folder settings error", str(exc))
            return None

        if show_confirmation:
            messagebox.showinfo("Settings saved", "Folder settings were saved successfully.")
        return config

    def require_config(self) -> Optional[PipelineConfig]:
        return self.save_folder_settings(show_confirmation=False)

    def verify_script_exists(self, path: Path, description: str) -> bool:
        if path.is_file():
            return True
        messagebox.showerror("Missing script", f"Could not find the {description}:\n\n{path}")
        return False

    def prepare_staging_directory(self, derivatives_dir: Path) -> Optional[Path]:
        included = [record for record in self.raw_records.values() if record["include"] == "Yes"]
        if not included:
            messagebox.showerror("Nothing selected", "Include at least one EDF file.")
            return None

        staging_dir = derivatives_dir / "_selected_raw"
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)

        for record in included:
            source_index = int(record["source_index"])
            destination = staging_dir / f"source-{source_index:03d}" / record["relative_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(record["edf_path"], destination)

        selection_log = {
            "source_folders": self.input_dirs,
            "selected_files": [record["edf_path"] for record in included],
        }
        (staging_dir / "selection.json").write_text(json.dumps(selection_log, indent=2) + "\n", encoding="utf-8")
        self.append_log(f"Staged {len(included)} selected EDF file(s) in {staging_dir}")
        return staging_dir

    def run_scrubber(self) -> None:
        config = self.require_config()
        if config is None or not self.verify_script_exists(SCRUBBER_SCRIPT, "EDF scrubber script"):
            return
        if not self.raw_records:
            self.scan_input_sources()
        staging_dir = self.prepare_staging_directory(config.electrophysiology.derivatives_dir)
        if staging_dir is None:
            return

        command = [
            sys.executable,
            "-u",
            str(SCRUBBER_SCRIPT),
            "--input-dir",
            str(staging_dir),
            "--output-dir",
            str(config.electrophysiology.scrubbed_dir),
        ]
        if self.overwrite_var.get():
            command.append("--overwrite")
        self.run_command(command, "EDF metadata scrubbing")

    def launch_comparison(self) -> None:
        config = self.require_config()
        if config is None or not self.verify_script_exists(COMPARISON_SCRIPT, "EDF comparison script"):
            return

        input_dir = config.electrophysiology.derivatives_dir / "_selected_raw"
        scrubbed_dir = config.electrophysiology.scrubbed_dir
        if not input_dir.is_dir():
            messagebox.showerror(
                "No staged raw EDFs",
                "Run Step 1 before reviewing raw and scrubbed EDF files.",
            )
            return
        if not scrubbed_dir.is_dir():
            messagebox.showerror(
                "No scrubbed EDFs",
                "Run Step 1 before reviewing raw and scrubbed EDF files.",
            )
            return

        self.clear_window()

        try:
            review = EDFReviewWindow(
                self,
                input_dir,
                scrubbed_dir,
                on_close=self.show_processing,
            )
            review.pack(fill="both", expand=True)
        except Exception as exc:
            self.show_processing()
            messagebox.showerror(
                "Could not open EDF review",
                str(exc),
                parent=self,
            )
            return

        if not review.pairs:
            review.destroy()
            self.show_processing()
            messagebox.showerror(
                "No matching EDF files",
                "No matching raw and scrubbed EDF pairs were found.",
                parent=self,
            )

    def open_bids_metadata_review(self) -> None:
        config = self.require_config()
        if config is None or not self.verify_script_exists(BIDS_CONVERTER_SCRIPT, "BIDS converter script"):
            return
        scrubbed_dir = config.electrophysiology.scrubbed_dir
        if not scrubbed_dir.exists() or not any(path.suffix.lower() == ".edf" for path in scrubbed_dir.rglob("*")):
            messagebox.showerror("No scrubbed EDFs", "Run the scrubber before BIDS conversion.")
            return
        self.clear_window()
        page = BIDSMetadataWindow(
            self,
            scrubbed_dir,
            config.electrophysiology.bids_output_dir,
            self.overwrite_var.get(),
            on_close=self.show_processing,
        )
        page.pack(fill="both", expand=True)

    def run_command(
        self,
        command: List[str],
        operation_name: str,
        on_success: Optional[Callable[[], None]] = None,
    ) -> None:
        if self.is_pipeline_running():
            messagebox.showwarning(
                "Pipeline busy",
                "Another pipeline operation is already running.",
                parent=self,
            )
            return

        self.pipeline_busy = True
        self.set_controls_enabled(False)
        self._configure_if_alive(
            getattr(self, "stop_button", None),
            state="normal",
        )
        self.status_var.set(f"Running: {operation_name}")
        self.append_log("\n" + "=" * 72)
        self.append_log(f"Starting {operation_name}")
        self.append_log(
            "Command: "
            + " ".join(
                self.format_command_argument(arg)
                for arg in command
            )
        )

        worker = threading.Thread(
            target=self.command_worker,
            args=(command, operation_name, on_success),
            daemon=True,
        )
        self.worker_thread = worker
        worker.start()

    def command_worker(
        self,
        command: List[str],
        operation_name: str,
        on_success: Optional[Callable[[], None]],
    ) -> None:
        return_code = 1

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
                    self.output_queue.put(
                        line.rstrip("\n")
                    )

            return_code = self.running_process.wait()

        except Exception as exc:
            self.output_queue.put(
                f"ERROR: Could not run {operation_name}: {exc}"
            )
            return_code = 1

        finally:
            self.running_process = None

        try:
            self.after(
                0,
                lambda: self.command_finished(
                    operation_name,
                    return_code,
                    on_success,
                ),
            )
        except tk.TclError:
            pass

    def command_finished(
        self,
        operation_name: str,
        return_code: int,
        on_success: Optional[Callable[[], None]],
    ) -> None:
        self.pipeline_busy = False
        self.running_process = None
        self.worker_thread = None

        self.set_controls_enabled(True)
        self._configure_if_alive(
            getattr(self, "stop_button", None),
            state="disabled",
        )

        if return_code == 0:
            self.status_var.set(
                f"Completed: {operation_name}"
            )
            self.append_log(
                f"{operation_name} completed successfully."
            )

            if on_success:
                on_success()
        else:
            self.status_var.set(
                f"Failed: {operation_name}"
            )
            self.append_log(
                f"{operation_name} exited with code {return_code}."
            )
            messagebox.showerror(
                "Pipeline operation failed",
                "See the pipeline log for details.",
                parent=self,
            )

    def stop_current_operation(self) -> None:
        if (
            self.running_process is not None
            and self.running_process.poll() is None
        ):
            self.running_process.terminate()

    def set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"

        for selector_name in (
            "derivatives_selector",
            "bids_selector",
        ):
            selector = getattr(
                self,
                selector_name,
                None,
            )
            if self._widget_exists(selector):
                try:
                    selector.set_enabled(enabled)
                except tk.TclError:
                    pass

        for widget_name in (
            "add_file_button",
            "add_folder_button",
            "remove_folder_button",
            "save_settings_button",
            "scrub_button",
            "compare_button",
            "bids_button",
            "overwrite_checkbox",
        ):
            self._configure_if_alive(
                getattr(self, widget_name, None),
                state=state,
            )

    def append_log(self, message: str) -> None:
        self.log_history.append(message)

        log_widget = getattr(
            self,
            "log_text",
            None,
        )

        if not self._widget_exists(log_widget):
            return

        try:
            log_widget.configure(state="normal")
            log_widget.insert("end", message + "\n")
            log_widget.see("end")
            log_widget.configure(state="disabled")
        except tk.TclError:
            pass

    def process_output_queue(self) -> None:
        while True:
            try:
                message = self.output_queue.get_nowait()
            except Empty:
                break

            self.append_log(message)

        try:
            self.after(
                100,
                self.process_output_queue,
            )
        except tk.TclError:
            pass

    @staticmethod
    def format_command_argument(argument: str) -> str:
        return f'"{argument}"' if " " in argument else argument

    def close_dashboard(self) -> None:
        if self.is_pipeline_running():
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
    root.title("Electrophysiology DeID Dashboard")
    root.geometry("1180x840")
    root.minsize(980, 700)

    app = PipelineDashboard(root)
    app.pack(fill="both", expand=True)

    root.protocol(
        "WM_DELETE_WINDOW",
        app.close_dashboard,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
