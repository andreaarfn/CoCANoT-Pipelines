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


class EDFReviewWindow(tk.Toplevel):
    """Native dashboard window for comparing and editing raw/scrubbed EDF metadata."""

    def __init__(
        self,
        parent: "PipelineDashboard",
        input_dir: Path,
        scrubbed_dir: Path,
    ) -> None:
        super().__init__(parent)
        self.parent_dashboard = parent
        self.input_dir = input_dir
        self.scrubbed_dir = scrubbed_dir
        self.helpers = load_comparison_module()
        self.pairs: List[Dict[str, object]] = []
        self.current_pair_index: Optional[int] = None
        self.current_data: Optional[Dict[str, object]] = None

        self.title("EDF Header and Annotation Review")
        self.geometry("1500x900")
        self.minsize(1050, 680)
        self.transient(parent)

        self.header_field_var = tk.StringVar()
        self.header_value_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select an EDF file.")

        self.build_pairs()
        self.build_interface()
        self.populate_file_list()

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
        ttk.Button(footer, text="Close", command=self.destroy).pack(side="right", padx=(0, 8))

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




class CollapsibleSection(ttk.Frame):
    """Simple expand/collapse section used for optional BIDS metadata."""

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        *,
        expanded: bool = False,
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.expanded = expanded

        self.columnconfigure(0, weight=1)

        self.toggle_button = ttk.Button(
            self,
            text="",
            command=self.toggle,
        )
        self.toggle_button.grid(row=0, column=0, sticky="ew")

        self.body = ttk.Frame(self, padding=(10, 8, 10, 4))
        self.body.columnconfigure(1, weight=1)
        self.body.columnconfigure(3, weight=1)

        self._refresh()

    def _refresh(self) -> None:
        arrow = "▼" if self.expanded else "▶"
        self.toggle_button.configure(text=f"{arrow} {self.title}")
        if self.expanded:
            self.body.grid(row=1, column=0, sticky="ew")
        else:
            self.body.grid_remove()

    def toggle(self) -> None:
        self.expanded = not self.expanded
        self._refresh()


class BIDSMetadataWindow(tk.Toplevel):
    """
    Review scrubbed EDF recordings and assign CoCANoT + BIDS metadata.

    Legend:
      ** = required by CoCANoT
       * = required by BIDS
      no marker = BIDS recommended / optional
    """

    RECORDING_MODALITY_TO_DATATYPE = {
        "Scalp EEG": "eeg",
        "Stereo EEG (SEEG)": "ieeg",
        "Subdural Grid/Strip EEG (ECoG)": "ieeg",
        "Magnetoencephalography (MEG)": "meg",
    }

    PURPOSE_OPTIONS = (
        "Diagnostic evaluation",
        "Presurgical evaluation",
        "Neuromodulation Planning",
        "Seizure Localization",
        "Postoperative Evaluation (<30 days)",
        "Follow-up Evaluation (>30 days after surgery)",
        "Other",
        "Unknown",
    )

    TIMING_OPTIONS = (
        "Preoperative",
        "Intraoperative",
        "Immediate Postoperative (<30 days after surgery)",
        "Follow-up (>30 days after surgery)",
        "Unknown",
    )

    LOCALIZATION_OPTIONS = (
        "Medial temporal",
        "Temporal neocortical",
        "Frontal",
        "Parietal",
        "Occipital",
        "Insula",
        "Thalamus: Anterior nucleus",
        "Thalamus: Centromedian",
        "Thalamus: Pulvinar",
        "Vagus Nerve",
        "Other",
        "N/A",
    )

    COMMON_OPTIONAL_FIELDS = (
        ("project_description", "Project Description", "entry"),
        ("session", "Session ID", "entry"),
        ("task_description", "Task Description", "entry"),
        ("instructions", "Instructions", "entry"),
        ("cog_atlas_id", "CogAtlasID", "entry"),
        ("cog_po_id", "CogPOID", "entry"),
        ("manufacturer", "Manufacturer", "entry"),
        ("model_name", "Manufacturer's Model Name", "entry"),
        ("software_versions", "Software Versions", "entry"),
        ("device_serial_number", "Device Serial Number / pseudonym", "entry"),
        ("institution_name", "Institution Name", "entry"),
        ("institution_address", "Institution Address", "entry"),
        ("institutional_department_name", "Institutional Department Name", "entry"),
        ("recording_type", "Recording Type", "combo", ("", "continuous", "epoched", "discontinuous")),
        ("epoch_length", "Epoch Length (seconds)", "entry"),
        ("hardware_filters", "Hardware Filters (JSON or n/a)", "entry"),
        ("subject_artefact_description", "Subject Artefact Description", "entry"),
        ("electrical_stimulation", "Electrical Stimulation", "combo", ("", "true", "false")),
        ("electrical_stimulation_parameters", "Electrical Stimulation Parameters", "entry"),
    )

    EEG_OPTIONAL_FIELDS = (
        ("cap_manufacturer", "Cap Manufacturer", "entry"),
        ("cap_model_name", "Cap Manufacturer's Model Name", "entry"),
        ("eeg_ground", "EEG Ground", "entry"),
        ("head_circumference", "Head Circumference (cm)", "entry"),
        ("eeg_placement_scheme", "EEG Placement Scheme", "entry"),
        ("eeg_electrodes_tsv_path", "Electrodes TSV (optional)", "file"),
        ("eeg_coordsystem_json_path", "Coordinate System JSON (required if electrodes TSV is supplied)", "file"),
    )

    IEEG_OPTIONAL_FIELDS = (
        ("electrode_manufacturer", "Electrode Manufacturer", "entry"),
        ("electrode_model_name", "Electrode Manufacturer's Model Name", "entry"),
        ("ieeg_ground", "iEEG Ground", "entry"),
        ("ieeg_placement_scheme", "iEEG Placement Scheme", "entry"),
        ("ieeg_electrode_groups", "iEEG Electrode Groups", "entry"),
    )

    MEG_OPTIONAL_FIELDS = (
        ("continuous_head_localization", "Continuous Head Localization", "combo", ("", "true", "false")),
        ("head_coil_frequency", "Head Coil Frequency (number or JSON array)", "entry"),
        ("max_movement", "Maximum Head Movement (mm)", "entry"),
        ("associated_empty_room", "Associated Empty Room (BIDS URI or JSON array)", "entry"),
        ("eeg_placement_scheme", "EEG Placement Scheme (if EEG recorded with MEG)", "entry"),
        ("cap_manufacturer", "Cap Manufacturer (if EEG recorded with MEG)", "entry"),
        ("cap_model_name", "Cap Manufacturer's Model Name (if EEG recorded with MEG)", "entry"),
        ("eeg_reference", "EEG Reference (if EEG recorded with MEG)", "entry"),
    )

    def __init__(
        self,
        parent: "PipelineDashboard",
        scrubbed_dir: Path,
        output_dir: Path,
        overwrite: bool,
    ) -> None:
        super().__init__(parent)
        self.parent_dashboard = parent
        self.scrubbed_dir = scrubbed_dir
        self.output_dir = output_dir
        self.overwrite = overwrite
        self.records: Dict[str, Dict[str, object]] = {}
        self.field_vars: Dict[str, tk.StringVar] = {}

        self.title("Electrophysiology BIDS Metadata Review")
        self.geometry("1600x1000")
        self.minsize(1180, 760)
        self.transient(parent)

        # CoCANoT metadata.
        self.cocanot_patient_id_var = tk.StringVar()
        self.surgery_id_var = tk.StringVar()
        self.recording_id_var = tk.StringVar()
        self.recording_modality_var = tk.StringVar(value="Scalp EEG")
        self.timing_var = tk.StringVar(value="Unknown")
        self.thalamus_recorded_var = tk.StringVar()
        self.thalamus_stimulated_var = tk.StringVar()
        self.seizure_count_var = tk.StringVar(value="0")
        self.comments_var = tk.StringVar(value="N/A")

        # BIDS workflow / sidecar metadata.
        self.project_var = tk.StringVar()
        self.task_name_var = tk.StringVar(value="monitoring")

        self.build_interface()
        self.load_scrubbed_files()
        self._seizure_count_changed()
        self._modality_changed()

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _var(self, key: str, default: str = "") -> tk.StringVar:
        if key not in self.field_vars:
            self.field_vars[key] = tk.StringVar(value=default)
        return self.field_vars[key]

    @staticmethod
    def _add_labeled_entry(
        parent: tk.Widget,
        row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
        *,
        width: int = 28,
        columnspan: int = 1,
        readonly: bool = False,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(
            row=row,
            column=column,
            sticky="w",
            pady=(4, 2),
        )
        entry = ttk.Entry(
            parent,
            textvariable=variable,
            width=width,
            state="readonly" if readonly else "normal",
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

    @staticmethod
    def _add_labeled_combo(
        parent: tk.Widget,
        row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
        values: tuple[str, ...],
        *,
        width: int = 25,
    ) -> ttk.Combobox:
        ttk.Label(parent, text=label).grid(
            row=row,
            column=column,
            sticky="w",
            pady=(4, 2),
        )
        combo = ttk.Combobox(
            parent,
            textvariable=variable,
            values=values,
            state="readonly",
            width=width,
        )
        combo.grid(
            row=row,
            column=column + 1,
            sticky="ew",
            padx=(6, 14),
            pady=(4, 2),
        )
        return combo

    def _add_file_field(
        self,
        parent: tk.Widget,
        row: int,
        label: str,
        key: str,
    ) -> None:
        variable = self._var(key)
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(4, 2))
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(6, 6), pady=(4, 2))

        def browse() -> None:
            selected = filedialog.askopenfilename(
                parent=self,
                title=label,
                initialdir=str(self.scrubbed_dir),
            )
            if selected:
                variable.set(selected)

        ttk.Button(parent, text="Browse…", command=browse).grid(
            row=row,
            column=3,
            sticky="e",
            pady=(4, 2),
        )

    def _clear_frame(self, frame: tk.Widget) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def build_interface(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        ttk.Label(
            root,
            text="Electrophysiology BIDS Metadata Review",
            font=("", 18, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            root,
            text=(
                "** Required by CoCANoT     * Required by BIDS     "
                "Fields without a marker are BIDS recommended / optional. "
                "Recording duration and sampling frequency are extracted from each recording when possible."
            ),
            wraplength=1500,
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        # --------------------------------------------------------------
        # Recording table
        # --------------------------------------------------------------

        table_frame = ttk.Frame(root)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = (
            "include",
            "file",
            "project",
            "patient",
            "surgery",
            "recording",
            "modality",
            "datatype",
            "duration",
            "task",
            "status",
        )
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            height=8,
        )
        headings = {
            "include": "Include",
            "file": "Scrubbed EDF",
            "project": "Project*",
            "patient": "CoCANoT Patient ID**",
            "surgery": "Surgery ID**",
            "recording": "Recording ID**",
            "modality": "Recording Modality**",
            "datatype": "BIDS Data Type",
            "duration": "Duration (sec)**",
            "task": "Task Name*",
            "status": "Status",
        }
        widths = {
            "include": 60,
            "file": 300,
            "project": 130,
            "patient": 140,
            "surgery": 110,
            "recording": 120,
            "modality": 210,
            "datatype": 90,
            "duration": 110,
            "task": 110,
            "status": 190,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w")

        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", self.toggle_inclusion_at_pointer)
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree_selection = ExtendedSelectionController(self.tree)

        # --------------------------------------------------------------
        # Scrollable metadata area
        # --------------------------------------------------------------

        metadata_shell = ttk.Frame(root)
        metadata_shell.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        metadata_shell.columnconfigure(0, weight=1)
        metadata_shell.rowconfigure(0, weight=1)

        self.metadata_canvas = tk.Canvas(metadata_shell, height=520, highlightthickness=0)
        self.metadata_canvas.grid(row=0, column=0, sticky="nsew")
        metadata_scroll = ttk.Scrollbar(
            metadata_shell,
            orient="vertical",
            command=self.metadata_canvas.yview,
        )
        metadata_scroll.grid(row=0, column=1, sticky="ns")
        self.metadata_canvas.configure(yscrollcommand=metadata_scroll.set)

        self.metadata_body = ttk.Frame(self.metadata_canvas)
        self.metadata_window_id = self.metadata_canvas.create_window(
            (0, 0),
            window=self.metadata_body,
            anchor="nw",
        )
        self.metadata_body.bind("<Configure>", self._metadata_body_configured)
        self.metadata_canvas.bind("<Configure>", self._metadata_canvas_configured)

        self.metadata_body.columnconfigure(0, weight=1)

        # --------------------------------------------------------------
        # CoCANoT section
        # --------------------------------------------------------------

        cocanot = ttk.LabelFrame(
            self.metadata_body,
            text="CoCANoT Metadata — all fields marked ** are required",
            padding=12,
        )
        cocanot.grid(row=0, column=0, sticky="ew")
        for col in (1, 3):
            cocanot.columnconfigure(col, weight=1)

        self._add_labeled_entry(
            cocanot, 0, 0, "CoCANoT Patient ID**", self.cocanot_patient_id_var
        )
        self._add_labeled_entry(
            cocanot, 0, 2, "Surgery ID**", self.surgery_id_var
        )
        self._add_labeled_entry(
            cocanot, 1, 0, "Recording ID**", self.recording_id_var
        )

        ttk.Label(cocanot, text="Recording Modality**").grid(
            row=1, column=2, sticky="w", pady=(4, 2)
        )
        modality_combo = ttk.Combobox(
            cocanot,
            textvariable=self.recording_modality_var,
            values=tuple(self.RECORDING_MODALITY_TO_DATATYPE),
            state="readonly",
        )
        modality_combo.grid(row=1, column=3, sticky="ew", padx=(6, 14), pady=(4, 2))
        modality_combo.bind("<<ComboboxSelected>>", self._modality_changed)

        ttk.Label(cocanot, text="Purpose** (select one or more)").grid(
            row=2, column=0, sticky="nw", pady=(8, 2)
        )
        purpose_frame = ttk.Frame(cocanot)
        purpose_frame.grid(row=2, column=1, sticky="nsew", padx=(6, 14), pady=(8, 2))
        purpose_frame.columnconfigure(0, weight=1)
        self.purpose_list = tk.Listbox(
            purpose_frame,
            selectmode="extended",
            exportselection=False,
            height=5,
        )
        self.purpose_list.grid(row=0, column=0, sticky="nsew")
        for option in self.PURPOSE_OPTIONS:
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
            row=2, column=2, sticky="nw", pady=(8, 2)
        )
        ttk.Combobox(
            cocanot,
            textvariable=self.timing_var,
            values=self.TIMING_OPTIONS,
            state="readonly",
        ).grid(row=2, column=3, sticky="ew", padx=(6, 14), pady=(8, 2))

        self._add_labeled_combo(
            cocanot,
            3,
            0,
            "Did you record the thalamus?**",
            self.thalamus_recorded_var,
            ("", "Yes", "No"),
        )
        self._add_labeled_combo(
            cocanot,
            3,
            2,
            "Did you stimulate the thalamus?**",
            self.thalamus_stimulated_var,
            ("", "Yes", "No"),
        )

        ttk.Label(cocanot, text="Recording Duration (seconds)**").grid(
            row=4, column=0, sticky="w", pady=(8, 2)
        )
        ttk.Label(
            cocanot,
            text="Automatically extracted separately from each EDF",
        ).grid(row=4, column=1, sticky="w", padx=(6, 14), pady=(8, 2))

        ttk.Label(cocanot, text="Number of Seizures Captured**").grid(
            row=4, column=2, sticky="w", pady=(8, 2)
        )
        seizure_entry = ttk.Entry(cocanot, textvariable=self.seizure_count_var)
        seizure_entry.grid(row=4, column=3, sticky="ew", padx=(6, 14), pady=(8, 2))
        seizure_entry.bind("<KeyRelease>", self._seizure_count_changed)

        ttk.Label(
            cocanot,
            text="Primary Seizure Onset Localization**",
        ).grid(row=5, column=0, sticky="nw", pady=(8, 2))
        localization_frame = ttk.Frame(cocanot)
        localization_frame.grid(
            row=5,
            column=1,
            columnspan=3,
            sticky="ew",
            padx=(6, 14),
            pady=(8, 2),
        )
        localization_frame.columnconfigure(0, weight=1)
        self.localization_list = tk.Listbox(
            localization_frame,
            selectmode="extended",
            exportselection=False,
            height=5,
        )
        self.localization_list.grid(row=0, column=0, sticky="ew")
        for option in self.LOCALIZATION_OPTIONS:
            self.localization_list.insert("end", option)
        localization_scroll = ttk.Scrollbar(
            localization_frame,
            orient="vertical",
            command=self.localization_list.yview,
        )
        localization_scroll.grid(row=0, column=1, sticky="ns")
        self.localization_list.configure(yscrollcommand=localization_scroll.set)
        self.localization_selection = ExtendedSelectionController(self.localization_list)

        ttk.Label(cocanot, text="Comments**").grid(
            row=6, column=0, sticky="w", pady=(8, 2)
        )
        comments_entry = ttk.Entry(cocanot, textvariable=self.comments_var)
        comments_entry.grid(
            row=6,
            column=1,
            columnspan=3,
            sticky="ew",
            padx=(6, 14),
            pady=(8, 2),
        )
        ttk.Label(
            cocanot,
            text='Use "N/A" when there are no additional comments. Do not include PHI.',
        ).grid(row=7, column=1, columnspan=3, sticky="w", padx=(6, 14))

        # --------------------------------------------------------------
        # BIDS required section
        # --------------------------------------------------------------

        required = ttk.LabelFrame(
            self.metadata_body,
            text="BIDS Required Metadata — fields marked * are required",
            padding=12,
        )
        required.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        required.columnconfigure(1, weight=1)
        required.columnconfigure(3, weight=1)

        self._add_labeled_entry(required, 0, 0, "Project*", self.project_var)

        self.subject_preview_var = tk.StringVar(value="Derived from CoCANoT Patient ID")
        self._add_labeled_entry(
            required,
            0,
            2,
            "Subject ID*",
            self.subject_preview_var,
            readonly=True,
        )

        self._add_labeled_entry(
            required,
            1,
            0,
            "Task Name*",
            self.task_name_var,
            columnspan=1,
        )

        ttk.Label(required, text="Sampling Frequency*").grid(
            row=1, column=2, sticky="w", pady=(4, 2)
        )
        ttk.Label(
            required,
            text="Automatically extracted from the recording",
        ).grid(row=1, column=3, sticky="w", padx=(6, 14), pady=(4, 2))

        self.required_dynamic = ttk.Frame(required)
        self.required_dynamic.grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="ew",
            pady=(8, 0),
        )
        self.required_dynamic.columnconfigure(1, weight=1)
        self.required_dynamic.columnconfigure(3, weight=1)

        # --------------------------------------------------------------
        # Optional / recommended BIDS section
        # --------------------------------------------------------------

        self.optional_section = CollapsibleSection(
            self.metadata_body,
            "BIDS Optional / Recommended Metadata",
            expanded=False,
        )
        self.optional_section.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.optional_dynamic = self.optional_section.body
        self.optional_dynamic.columnconfigure(1, weight=1)
        self.optional_dynamic.columnconfigure(3, weight=1)

        # --------------------------------------------------------------
        # MEG warning
        # --------------------------------------------------------------

        self.modality_notice_var = tk.StringVar()
        self.modality_notice = ttk.Label(
            self.metadata_body,
            textvariable=self.modality_notice_var,
            wraplength=1450,
        )
        self.modality_notice.grid(row=3, column=0, sticky="w", pady=(10, 0))

        # --------------------------------------------------------------
        # Bottom controls
        # --------------------------------------------------------------

        actions = ttk.Frame(root)
        actions.grid(row=4, column=0, sticky="ew", pady=(10, 0))

        ttk.Button(
            actions,
            text="Include Selected",
            command=lambda: self.set_selected_included(True),
        ).pack(side="left")

        ttk.Button(
            actions,
            text="Exclude Selected",
            command=lambda: self.set_selected_included(False),
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            actions,
            text="Apply to Selected",
            command=self.apply_to_selected,
        ).pack(side="left", padx=(18, 0))

        ttk.Button(
            actions,
            text="Convert Included Recordings",
            command=self.create_manifest_and_convert,
        ).pack(side="right")

    def _metadata_body_configured(self, _event: tk.Event) -> None:
        self.metadata_canvas.configure(scrollregion=self.metadata_canvas.bbox("all"))

    def _metadata_canvas_configured(self, event: tk.Event) -> None:
        self.metadata_canvas.itemconfigure(self.metadata_window_id, width=event.width)

    def _add_dynamic_field(
        self,
        parent: tk.Widget,
        row: int,
        config: tuple,
        *,
        required: bool = False,
    ) -> int:
        key, label, field_type, *rest = config
        label_text = f"{label}*" if required else label
        variable = self._var(key)

        if field_type == "combo":
            values = tuple(rest[0]) if rest else ("",)
            self._add_labeled_combo(parent, row, 0, label_text, variable, values)
        elif field_type == "file":
            self._add_file_field(parent, row, label_text, key)
        else:
            self._add_labeled_entry(parent, row, 0, label_text, variable, columnspan=2)
        return row + 1

    def _modality_changed(self, _event: Optional[tk.Event] = None) -> None:
        modality = self.recording_modality_var.get().strip()
        datatype = self.RECORDING_MODALITY_TO_DATATYPE.get(modality, "")

        self._clear_frame(self.required_dynamic)
        self._clear_frame(self.optional_dynamic)
        self.required_dynamic.columnconfigure(1, weight=1)
        self.required_dynamic.columnconfigure(3, weight=1)
        self.optional_dynamic.columnconfigure(1, weight=1)
        self.optional_dynamic.columnconfigure(3, weight=1)

        # Defaults that are BIDS-valid and explicit.
        if not self._var("software_filters").get():
            self._var("software_filters").set("n/a")

        row = 0

        if datatype == "eeg":
            self._add_labeled_entry(
                self.required_dynamic,
                row,
                0,
                "EEG Reference*",
                self._var("eeg_reference"),
            )
            self._add_labeled_combo(
                self.required_dynamic,
                row,
                2,
                "Power Line Frequency*",
                self._var("power_line_frequency"),
                ("", "50", "60", "n/a"),
            )
            row += 1
            self._add_labeled_entry(
                self.required_dynamic,
                row,
                0,
                "Software Filters* (JSON or n/a)",
                self._var("software_filters"),
                columnspan=2,
            )

            optional = list(self.COMMON_OPTIONAL_FIELDS) + list(self.EEG_OPTIONAL_FIELDS)
            self.modality_notice_var.set(
                "Scalp EEG selected: conversion will follow the BIDS EEG layout "
                "and create an *_eeg.json sidecar plus *_channels.tsv."
            )

        elif datatype == "ieeg":
            self._add_labeled_entry(
                self.required_dynamic,
                row,
                0,
                "iEEG Reference*",
                self._var("ieeg_reference"),
            )
            self._add_labeled_combo(
                self.required_dynamic,
                row,
                2,
                "Power Line Frequency*",
                self._var("power_line_frequency"),
                ("", "50", "60", "n/a"),
            )
            row += 1
            self._add_labeled_entry(
                self.required_dynamic,
                row,
                0,
                "Software Filters* (JSON or n/a)",
                self._var("software_filters"),
                columnspan=2,
            )
            row += 1
            self._add_file_field(
                self.required_dynamic,
                row,
                "Electrodes TSV*",
                "ieeg_electrodes_tsv_path",
            )
            row += 1
            self._add_file_field(
                self.required_dynamic,
                row,
                "Coordinate System JSON*",
                "ieeg_coordsystem_json_path",
            )

            optional = list(self.COMMON_OPTIONAL_FIELDS) + list(self.IEEG_OPTIONAL_FIELDS)
            self.modality_notice_var.set(
                "SEEG / ECoG selected: conversion will follow the BIDS iEEG layout. "
                "BIDS requires an electrodes.tsv file and matching coordsystem.json for iEEG."
            )

        elif datatype == "meg":
            self._add_labeled_combo(
                self.required_dynamic,
                row,
                0,
                "Power Line Frequency*",
                self._var("power_line_frequency"),
                ("", "50", "60", "n/a"),
            )
            self._add_labeled_entry(
                self.required_dynamic,
                row,
                2,
                "Dewar Position*",
                self._var("dewar_position"),
            )
            row += 1
            self._add_labeled_entry(
                self.required_dynamic,
                row,
                0,
                "Software Filters* (JSON or n/a)",
                self._var("software_filters"),
                columnspan=2,
            )
            row += 1
            self._add_labeled_combo(
                self.required_dynamic,
                row,
                0,
                "Digitized Landmarks*",
                self._var("digitized_landmarks"),
                ("", "true", "false"),
            )
            self._add_labeled_combo(
                self.required_dynamic,
                row,
                2,
                "Digitized Head Points*",
                self._var("digitized_head_points"),
                ("", "true", "false"),
            )

            optional = list(self.COMMON_OPTIONAL_FIELDS) + list(self.MEG_OPTIONAL_FIELDS)
            self.modality_notice_var.set(
                "MEG selected. BIDS requires raw MEG data to remain in the native "
                "manufacturer format. This EDF workflow will therefore NOT export an EDF "
                "as raw BIDS MEG. The fields are shown so the metadata model is complete, "
                "but conversion is intentionally blocked until a native-MEG workflow is added."
            )

        else:
            optional = []
            self.modality_notice_var.set("Select a recording modality.")

        optional_row = 0
        for config in optional:
            optional_row = self._add_dynamic_field(
                self.optional_dynamic,
                optional_row,
                config,
                required=False,
            )

        self.subject_preview_var.set(
            self.cocanot_patient_id_var.get().strip()
            or "Derived from CoCANoT Patient ID"
        )

    # ------------------------------------------------------------------
    # File metadata
    # ------------------------------------------------------------------

    @staticmethod
    def matching_sidecar(edf_path: Path) -> Optional[Path]:
        candidates = [
            edf_path.with_suffix(".json"),
            edf_path.with_name(edf_path.stem + "_metadata.json"),
        ]
        return next((candidate for candidate in candidates if candidate.exists()), None)

    @staticmethod
    def find_nested_value(payload: object, keys: set[str]) -> str:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if str(key).lower() in keys and value not in (None, ""):
                    return str(value)
            for value in payload.values():
                found = BIDSMetadataWindow.find_nested_value(value, keys)
                if found:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = BIDSMetadataWindow.find_nested_value(value, keys)
                if found:
                    return found
        return ""

    def sidecar_sex(self, sidecar: Optional[Path]) -> str:
        if sidecar is None:
            return "n/a"
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "n/a"
        return self.find_nested_value(
            payload,
            {"sex", "gender", "participant_sex"},
        ) or "n/a"

    @staticmethod
    def edf_duration_seconds(edf_path: Path) -> object:
        try:
            import pyedflib

            reader = pyedflib.EdfReader(str(edf_path))
            try:
                return float(reader.file_duration)
            finally:
                reader.close()
        except Exception:
            return "n/a"

    def load_scrubbed_files(self) -> None:
        edf_files = sorted(
            path
            for path in self.scrubbed_dir.rglob("*")
            if path.is_file() and path.suffix.lower() == ".edf"
        )

        for index, edf_path in enumerate(edf_files, start=1):
            sidecar = self.matching_sidecar(edf_path)
            item_id = f"record-{index}"

            self.records[item_id] = {
                "edf_path": str(edf_path.resolve()),
                "sidecar_path": str(sidecar.resolve()) if sidecar else "",
                "source_label": str(edf_path.relative_to(self.scrubbed_dir)),
                "include": "Yes",
                "project": "",
                "project_description": "",
                "cocanot_patient_id": "",
                "surgery_id": "",
                "recording_id": "",
                "recording_modality": "",
                "datatype": "",
                "purpose": [],
                "timing_relative_to_surgery": "",
                "thalamus_recorded": "",
                "thalamus_stimulated": "",
                "recording_duration_seconds": self.edf_duration_seconds(edf_path),
                "number_of_seizures_captured": "",
                "primary_seizure_onset_localization": [],
                "comments": "",
                "task_name": "",
                "session": "",
                "bids_metadata": {},
                "sex": self.sidecar_sex(sidecar),
                "status": "Missing required metadata",
            }
            self.refresh_row(item_id)

        if edf_files:
            first_item = next(iter(self.records))
            self.tree.selection_set(first_item)
            self.tree.focus(first_item)
            self.tree_selection.anchor = first_item
            self.after_idle(self.tree_selection.focus)

    def refresh_row(self, item_id: str) -> None:
        record = self.records[item_id]
        values = (
            record["include"],
            record["source_label"],
            record["project"],
            record["cocanot_patient_id"],
            record["surgery_id"],
            record["recording_id"],
            record["recording_modality"],
            record["datatype"],
            record["recording_duration_seconds"],
            record["task_name"],
            record["status"],
        )
        if self.tree.exists(item_id):
            self.tree.item(item_id, values=values)
        else:
            self.tree.insert("", "end", iid=item_id, values=values)

    # ------------------------------------------------------------------
    # Form values / validation
    # ------------------------------------------------------------------

    def target_ids(self) -> List[str]:
        selected = list(self.tree.selection())
        if not selected:
            messagebox.showinfo(
                "No selection",
                "Select one or more recordings first.",
                parent=self,
            )
        return selected

    @staticmethod
    def _selected_values(listbox: tk.Listbox) -> List[str]:
        return [str(listbox.get(index)) for index in listbox.curselection()]

    def _seizure_count_changed(self, _event: Optional[tk.Event] = None) -> None:
        text = self.seizure_count_var.get().strip()

        if text.isdigit() and int(text) == 0:
            self.localization_list.configure(state="disabled")
            self.localization_list.selection_clear(0, "end")
            try:
                index = self.LOCALIZATION_OPTIONS.index("N/A")
                self.localization_list.selection_set(index)
            except ValueError:
                pass
        else:
            self.localization_list.configure(state="normal")

    @staticmethod
    def _valid_json_or_na(value: str) -> bool:
        text = value.strip()
        if text.lower() == "n/a":
            return True
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return False
        return isinstance(parsed, dict)

    @staticmethod
    def _valid_number_or_na(value: str) -> bool:
        text = value.strip()
        if text.lower() == "n/a":
            return True
        try:
            float(text)
        except ValueError:
            return False
        return True

    def metadata_values(self) -> Dict[str, object]:
        modality = self.recording_modality_var.get().strip()
        datatype = self.RECORDING_MODALITY_TO_DATATYPE.get(modality, "")

        localization = self._selected_values(self.localization_list)
        seizure_text = self.seizure_count_var.get().strip()
        if seizure_text == "0":
            localization = ["N/A"]

        bids_metadata = {
            key: variable.get().strip()
            for key, variable in self.field_vars.items()
        }

        return {
            "project": self.project_var.get().strip(),
            "project_description": bids_metadata.get("project_description", ""),
            "cocanot_patient_id": self.cocanot_patient_id_var.get().strip(),
            "participant": self.cocanot_patient_id_var.get().strip(),
            "surgery_id": self.surgery_id_var.get().strip(),
            "recording_id": self.recording_id_var.get().strip(),
            "recording_modality": modality,
            "datatype": datatype,
            "purpose": self._selected_values(self.purpose_list),
            "timing_relative_to_surgery": self.timing_var.get().strip(),
            "thalamus_recorded": self.thalamus_recorded_var.get().strip(),
            "thalamus_stimulated": self.thalamus_stimulated_var.get().strip(),
            "number_of_seizures_captured": seizure_text,
            "primary_seizure_onset_localization": localization,
            "comments": self.comments_var.get().strip(),
            "task_name": self.task_name_var.get().strip(),
            "session": bids_metadata.get("session", ""),
            "bids_metadata": bids_metadata,
        }

    def validate_values(self, values: Dict[str, object]) -> List[str]:
        problems: List[str] = []

        # CoCANoT required metadata.
        for key, label in (
            ("cocanot_patient_id", "CoCANoT Patient ID"),
            ("surgery_id", "Surgery ID"),
            ("recording_id", "Recording ID"),
            ("recording_modality", "Recording Modality"),
            ("timing_relative_to_surgery", "Timing Relative to Surgery"),
            ("thalamus_recorded", "Did you record the thalamus?"),
            ("thalamus_stimulated", "Did you stimulate the thalamus?"),
            ("number_of_seizures_captured", "Number of Seizures Captured"),
            ("comments", 'Comments (use "N/A" when none)'),
        ):
            if not str(values.get(key, "")).strip():
                problems.append(f"{label} is required by CoCANoT.")

        if not values.get("purpose"):
            problems.append("Purpose is required by CoCANoT.")

        seizure_text = str(values.get("number_of_seizures_captured", "")).strip()
        if seizure_text:
            if not seizure_text.isdigit():
                problems.append(
                    "Number of Seizures Captured must be zero or a positive whole number."
                )
            elif int(seizure_text) > 0 and not values.get(
                "primary_seizure_onset_localization"
            ):
                problems.append(
                    "Primary Seizure Onset Localization is required when seizures were captured."
                )

        # BIDS workflow required metadata.
        if not str(values.get("project", "")).strip():
            problems.append("Project is required for the BIDS dataset.")
        if not str(values.get("task_name", "")).strip():
            problems.append("Task Name is required by BIDS.")

        modality = str(values.get("recording_modality", ""))
        datatype = str(values.get("datatype", ""))
        bids = dict(values.get("bids_metadata", {}))

        if datatype == "eeg":
            if not bids.get("eeg_reference"):
                problems.append("EEG Reference is required by BIDS.")
            if not bids.get("power_line_frequency"):
                problems.append("Power Line Frequency is required by BIDS.")
            if not bids.get("software_filters"):
                problems.append("Software Filters is required by BIDS.")

            electrodes = str(bids.get("eeg_electrodes_tsv_path", "")).strip()
            coordsystem = str(bids.get("eeg_coordsystem_json_path", "")).strip()
            if bool(electrodes) != bool(coordsystem):
                problems.append(
                    "For EEG, Electrode TSV and Coordinate System JSON must be supplied together."
                )

        elif datatype == "ieeg":
            if not bids.get("ieeg_reference"):
                problems.append("iEEG Reference is required by BIDS.")
            if not bids.get("power_line_frequency"):
                problems.append("Power Line Frequency is required by BIDS.")
            if not bids.get("software_filters"):
                problems.append("Software Filters is required by BIDS.")
            if not bids.get("ieeg_electrodes_tsv_path"):
                problems.append("Electrodes TSV is required for BIDS iEEG.")
            if not bids.get("ieeg_coordsystem_json_path"):
                problems.append("Coordinate System JSON is required for BIDS iEEG.")

        elif datatype == "meg":
            for key, label in (
                ("power_line_frequency", "Power Line Frequency"),
                ("dewar_position", "Dewar Position"),
                ("software_filters", "Software Filters"),
                ("digitized_landmarks", "Digitized Landmarks"),
                ("digitized_head_points", "Digitized Head Points"),
            ):
                if not bids.get(key):
                    problems.append(f"{label} is required by BIDS MEG.")

        if bids.get("software_filters") and not self._valid_json_or_na(
            str(bids["software_filters"])
        ):
            problems.append(
                'Software Filters must be a JSON object or the literal value "n/a".'
            )

        if bids.get("hardware_filters") and not self._valid_json_or_na(
            str(bids["hardware_filters"])
        ):
            problems.append(
                'Hardware Filters must be a JSON object or the literal value "n/a".'
            )

        if bids.get("power_line_frequency") and not self._valid_number_or_na(
            str(bids["power_line_frequency"])
        ):
            problems.append("Power Line Frequency must be numeric or n/a.")

        if bids.get("epoch_length"):
            try:
                if float(str(bids["epoch_length"])) < 0:
                    raise ValueError
            except ValueError:
                problems.append("Epoch Length must be a non-negative number.")

        if bids.get("head_circumference"):
            try:
                if float(str(bids["head_circumference"])) <= 0:
                    raise ValueError
            except ValueError:
                problems.append("Head Circumference must be a number greater than zero.")

        if modality == "Magnetoencephalography (MEG)":
            # This is a workflow limitation, not missing metadata.
            pass

        return problems

    def apply_metadata(self, item_ids: List[str]) -> None:
        values = self.metadata_values()
        problems = self.validate_values(values)

        if problems:
            messagebox.showerror(
                "Missing or invalid metadata",
                "Correct these fields before applying:\n\n"
                + "\n".join(f"• {problem}" for problem in problems),
                parent=self,
            )
            return

        self.subject_preview_var.set(str(values["participant"]))

        for item_id in item_ids:
            preserved_duration = self.records[item_id]["recording_duration_seconds"]
            self.records[item_id].update(values)
            self.records[item_id]["recording_duration_seconds"] = preserved_duration

            if preserved_duration == "n/a":
                self.records[item_id]["status"] = "Could not read recording duration"
            else:
                self.records[item_id]["status"] = (
                    "Ready"
                    if self._record_complete(self.records[item_id])
                    else "Missing required metadata"
                )
            self.refresh_row(item_id)

    def apply_to_selected(self) -> None:
        ids = self.target_ids()
        if ids:
            self.apply_metadata(ids)

    def set_selected_included(self, included: bool) -> None:
        for item_id in self.target_ids():
            self.records[item_id]["include"] = "Yes" if included else "No"
            if not included:
                self.records[item_id]["status"] = "Excluded"
            else:
                self.records[item_id]["status"] = (
                    "Ready"
                    if self._record_complete(self.records[item_id])
                    else "Missing required metadata"
                )
            self.refresh_row(item_id)

    def toggle_inclusion_at_pointer(self, event: tk.Event) -> None:
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        included = self.records[item_id]["include"] != "Yes"
        self.records[item_id]["include"] = "Yes" if included else "No"
        self.records[item_id]["status"] = (
            "Ready"
            if included and self._record_complete(self.records[item_id])
            else ("Excluded" if not included else "Missing required metadata")
        )
        self.refresh_row(item_id)

    def _record_complete(self, record: Dict[str, object]) -> bool:
        if record.get("recording_duration_seconds") == "n/a":
            return False
        values = dict(record)
        return not self.validate_values(values)

    # ------------------------------------------------------------------
    # Manifest / conversion
    # ------------------------------------------------------------------

    def create_manifest_and_convert(self) -> None:
        included = [
            record
            for record in self.records.values()
            if record["include"] == "Yes"
        ]

        if not included:
            messagebox.showerror(
                "Nothing selected",
                "Include at least one recording.",
                parent=self,
            )
            return

        incomplete = [
            str(record["source_label"])
            for record in included
            if not self._record_complete(record)
        ]
        if incomplete:
            messagebox.showerror(
                "Incomplete metadata",
                "Complete the required metadata for:\n\n"
                + "\n".join(incomplete[:20]),
                parent=self,
            )
            return

        meg_records = [
            str(record["source_label"])
            for record in included
            if record["datatype"] == "meg"
        ]
        if meg_records:
            messagebox.showerror(
                "Native MEG files required",
                "BIDS raw MEG data must remain in the native MEG acquisition format.\n\n"
                "This EDF conversion workflow will not export EDF files as raw BIDS MEG.\n\n"
                "MEG recording(s):\n" + "\n".join(meg_records[:20]),
                parent=self,
            )
            return

        manifest_path = self.scrubbed_dir.parent / "bids_conversion_manifest.json"

        payload = {
            "bids_version": "1.11.1",
            "records": [],
        }

        for record in included:
            payload["records"].append(
                {
                    "edf_path": record["edf_path"],
                    "sidecar_path": record["sidecar_path"],
                    "project": record["project"],
                    "project_description": record["project_description"],
                    "participant_id": record["cocanot_patient_id"],
                    "cocanot_patient_id": record["cocanot_patient_id"],
                    "surgery_id": record["surgery_id"],
                    "recording_id": record["recording_id"],
                    "session_id": record["session"],
                    "task_name": record["task_name"],
                    "recording_modality": record["recording_modality"],
                    "datatype": record["datatype"],
                    "purpose": record["purpose"],
                    "timing_relative_to_surgery": record["timing_relative_to_surgery"],
                    "thalamus_recorded": record["thalamus_recorded"],
                    "thalamus_stimulated": record["thalamus_stimulated"],
                    "number_of_seizures_captured": record["number_of_seizures_captured"],
                    "primary_seizure_onset_localization": record[
                        "primary_seizure_onset_localization"
                    ],
                    "comments": record["comments"],
                    "bids_metadata": record["bids_metadata"],
                }
            )

        manifest_path.write_text(
            json.dumps(payload, indent=2) + "\n",
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
            "BIDS conversion",
            on_success=self.destroy,
        )



class PipelineDashboard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Electrophysiology DeID Dashboard")
        self.geometry("1180x840")
        self.minsize(980, 700)

        self.output_queue: Queue[str] = Queue()
        self.running_process: subprocess.Popen[str] | None = None
        self.pipeline_busy = False
        self.raw_records: Dict[str, Dict[str, str]] = {}

        saved = self.read_saved_settings()
        eeg = saved.get("electrophysiology", {})
        saved_input_dirs = eeg.get("input_dirs") or ([eeg.get("input_dir")] if eeg.get("input_dir") else [])
        self.input_dirs: List[str] = [str(Path(path).expanduser()) for path in saved_input_dirs if path]

        self.derivatives_dir_var = tk.StringVar(value=str(eeg.get("derivatives_dir", "")))
        self.bids_output_dir_var = tk.StringVar(value=str(eeg.get("bids_output_dir", "")))
        self.overwrite_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")

        self.build_interface()
        self.refresh_folder_list()
        self.after(100, self.process_output_queue)
        self.protocol("WM_DELETE_WINDOW", self.close_dashboard)

    def read_saved_settings(self) -> dict:
        try:
            return load_settings_dict()
        except PipelineConfigError as exc:
            messagebox.showwarning("Settings warning", str(exc))
            return {"electrophysiology": {}}

    def build_interface(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        ttk.Label(root, text="Electrophysiology DeID Dashboard", font=("", 22, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            root,
            text=(
                "Select folders containing EDF or EDF files, scrub headers, "
                "review, and convert accepted files to BIDS."
            ),
            wraplength=1100,
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))

        folders = ttk.LabelFrame(root, text="Source and output folders", padding=12)
        folders.grid(row=2, column=0, sticky="ew")
        folders.columnconfigure(0, weight=1)

        source_frame = ttk.Frame(folders)
        source_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        source_frame.columnconfigure(0, weight=1)
        ttk.Label(source_frame, text="Raw EDF source folders").grid(row=0, column=0, sticky="w")
        self.folder_list = tk.Listbox(source_frame, height=4, selectmode="extended")
        self.folder_list.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.folder_selection = ExtendedSelectionController(self.folder_list)
        folder_buttons = ttk.Frame(source_frame)
        folder_buttons.grid(row=1, column=1, sticky="ns", padx=(8, 0), pady=(4, 0))
        self.add_folder_button = ttk.Button(folder_buttons, text="Add Folder…", command=self.add_input_folder)
        self.add_folder_button.pack(fill="x")
        self.remove_folder_button = ttk.Button(folder_buttons, text="Remove Selected", command=self.remove_input_folders)
        self.remove_folder_button.pack(fill="x", pady=(6, 0))
        self.scan_button = ttk.Button(folder_buttons, text="Scan EDFs", command=self.scan_input_folders)
        self.scan_button.pack(fill="x", pady=(6, 0))

        self.derivatives_selector = FolderSelector(
            folders,
            "Derivatives output folder",
            self.derivatives_dir_var,
            "Select the derivatives output folder",
            PROJECT_ROOT,
        )
        self.derivatives_selector.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.bids_selector = FolderSelector(
            folders,
            "BIDS output folder",
            self.bids_output_dir_var,
            "Select the BIDS output folder",
            PROJECT_ROOT,
        )
        self.bids_selector.grid(row=2, column=0, sticky="ew")

        content = ttk.Frame(root)
        content.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=2)
        content.rowconfigure(3, weight=1)

        selection_frame = ttk.LabelFrame(content, text="Raw EDF selection", padding=8)
        selection_frame.grid(row=0, column=0, sticky="nsew")
        selection_frame.columnconfigure(0, weight=1)
        selection_frame.rowconfigure(0, weight=1)

        columns = ("include", "source", "patient_folder", "file")
        self.raw_tree = ttk.Treeview(selection_frame, columns=columns, show="headings", selectmode="extended")
        for column, heading, width in (
            ("include", "Include", 70),
            ("source", "Source folder", 230),
            ("patient_folder", "Patient/parent folder", 180),
            ("file", "EDF file", 520),
        ):
            self.raw_tree.heading(column, text=heading)
            self.raw_tree.column(column, width=width, anchor="w")
        self.raw_tree.grid(row=0, column=0, sticky="nsew")
        self.raw_tree.bind("<Double-1>", self.toggle_raw_inclusion_at_pointer)
        raw_scroll = ttk.Scrollbar(selection_frame, orient="vertical", command=self.raw_tree.yview)
        raw_scroll.grid(row=0, column=1, sticky="ns")
        self.raw_tree.configure(yscrollcommand=raw_scroll.set)
        self.raw_tree_selection = ExtendedSelectionController(self.raw_tree)

        raw_actions = ttk.Frame(content)
        raw_actions.grid(row=1, column=0, sticky="ew", pady=(6, 10))
        ttk.Button(raw_actions, text="Include Selected", command=lambda: self.set_raw_selected(True)).pack(side="left")
        ttk.Button(raw_actions, text="Exclude Selected", command=lambda: self.set_raw_selected(False)).pack(side="left", padx=(6, 0))
        ttk.Button(raw_actions, text="Include All", command=lambda: self.set_raw_all(True)).pack(side="left", padx=(18, 0))
        ttk.Button(raw_actions, text="Exclude All", command=lambda: self.set_raw_all(False)).pack(side="left", padx=(6, 0))
        self.save_settings_button = ttk.Button(raw_actions, text="Save Folder Settings", command=self.save_folder_settings)
        self.save_settings_button.pack(side="right")

        operations = ttk.LabelFrame(content, text="Pipeline Operations", padding=12)
        operations.grid(row=2, column=0, sticky="ew")
        for index in range(3):
            operations.columnconfigure(index, weight=1)
        self.scrub_button = ttk.Button(operations, text="1. Scrub Included EDFs", command=self.run_scrubber)
        self.scrub_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.compare_button = ttk.Button(operations, text="2. Review Scrubbed EDFs", command=self.launch_comparison)
        self.compare_button.grid(row=0, column=1, sticky="ew", padx=6)
        self.bids_button = ttk.Button(operations, text="3. Select & Convert to BIDS", command=self.open_bids_metadata_review)
        self.bids_button.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        self.stop_button = ttk.Button(operations, text="Stop Current Operation", command=self.stop_current_operation, state="disabled")
        self.stop_button.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.overwrite_checkbox = ttk.Checkbutton(
            operations,
            text="Overwrite existing staged, scrubbed, or exact BIDS outputs",
            variable=self.overwrite_var,
        )
        self.overwrite_checkbox.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

        log_frame = ttk.LabelFrame(content, text="Pipeline Log", padding=8)
        log_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        ttk.Label(log_frame, textvariable=self.status_var).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.log_text = tk.Text(log_frame, wrap="word", height=10, state="disabled")
        self.log_text.grid(row=1, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.append_log(f"Dashboard ready. Settings file: {get_settings_path()}")

    def refresh_folder_list(self) -> None:
        self.folder_list.delete(0, "end")
        for path in self.input_dirs:
            self.folder_list.insert("end", path)
        if self.input_dirs:
            self.folder_list.selection_set(0)
            self.folder_list.activate(0)
            self.folder_selection.anchor = 0

    def add_input_folder(self) -> None:
        if self.input_dirs:
            first_folder = Path(self.input_dirs[0]).expanduser()
            initial_dir = first_folder.parent if first_folder.parent.is_dir() else PROJECT_ROOT
        else:
            initial_dir = PROJECT_ROOT

        selected_folders = MultiFolderSelectionDialog.ask_folders(
            parent=self,
            title="Add raw EDF source folders",
            initial_dir=initial_dir,
        )
        if not selected_folders:
            return

        existing = set(self.input_dirs)
        added = 0
        for selected in selected_folders:
            resolved = str(Path(selected).expanduser().resolve())
            if resolved not in existing:
                self.input_dirs.append(resolved)
                existing.add(resolved)
                added += 1

        self.refresh_folder_list()
        self.append_log(f"Added {added} raw EDF source folder(s).")

    def remove_input_folders(self) -> None:
        indices = list(self.folder_list.curselection())
        for index in reversed(indices):
            del self.input_dirs[index]
        self.refresh_folder_list()

    def scan_input_folders(self) -> None:
        self.raw_records.clear()
        for item in self.raw_tree.get_children():
            self.raw_tree.delete(item)

        counter = 1
        for source_index, folder_text in enumerate(self.input_dirs, start=1):
            folder = Path(folder_text).expanduser().resolve()
            if not folder.is_dir():
                self.append_log(f"Skipping missing folder: {folder}")
                continue
            for edf_path in sorted(path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() == ".edf"):
                relative = edf_path.relative_to(folder)
                item_id = f"raw-{counter}"
                counter += 1
                self.raw_records[item_id] = {
                    "include": "Yes",
                    "source_index": str(source_index),
                    "source_folder": str(folder),
                    "source_name": folder.name,
                    "patient_folder": relative.parent.name if relative.parent != Path(".") else "(folder root)",
                    "relative_path": str(relative),
                    "edf_path": str(edf_path),
                }
                self.refresh_raw_row(item_id)

        self.append_log(f"Found {len(self.raw_records)} EDF file(s) across {len(self.input_dirs)} folder(s).")
        if self.raw_records:
            first_item = next(iter(self.raw_records))
            self.raw_tree.selection_set(first_item)
            self.raw_tree.focus(first_item)
            self.raw_tree_selection.anchor = first_item
            self.after_idle(self.raw_tree_selection.focus)

    def refresh_raw_row(self, item_id: str) -> None:
        record = self.raw_records[item_id]
        values = (record["include"], record["source_name"], record["patient_folder"], record["relative_path"])
        if self.raw_tree.exists(item_id):
            self.raw_tree.item(item_id, values=values)
        else:
            self.raw_tree.insert("", "end", iid=item_id, values=values)

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
        return build_settings_dict(
            input_dirs=self.input_dirs,
            derivatives_dir=self.derivatives_dir_var.get().strip(),
            bids_output_dir=self.bids_output_dir_var.get().strip(),
        )

    def save_folder_settings(self, show_confirmation: bool = True) -> Optional[PipelineConfig]:
        if not self.input_dirs:
            messagebox.showerror("Missing folders", "Add at least one raw EDF source folder.")
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
            messagebox.showerror("Nothing selected", "Scan the source folders and include at least one EDF file.")
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
            self.scan_input_folders()
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

        try:
            review = EDFReviewWindow(self, input_dir, scrubbed_dir)
        except Exception as exc:
            messagebox.showerror("Could not open EDF review", str(exc))
            return

        if not review.pairs:
            review.destroy()
            messagebox.showerror(
                "No matching EDF files",
                "No matching raw and scrubbed EDF pairs were found.",
            )

    def open_bids_metadata_review(self) -> None:
        config = self.require_config()
        if config is None or not self.verify_script_exists(BIDS_CONVERTER_SCRIPT, "BIDS converter script"):
            return
        scrubbed_dir = config.electrophysiology.scrubbed_dir
        if not scrubbed_dir.exists() or not any(path.suffix.lower() == ".edf" for path in scrubbed_dir.rglob("*")):
            messagebox.showerror("No scrubbed EDFs", "Run the scrubber before BIDS conversion.")
            return
        BIDSMetadataWindow(self, scrubbed_dir, config.electrophysiology.bids_output_dir, self.overwrite_var.get())

    def run_command(self, command: List[str], operation_name: str, on_success: Optional[Callable[[], None]] = None) -> None:
        if self.pipeline_busy:
            messagebox.showwarning("Pipeline busy", "Another pipeline operation is already running.")
            return
        self.pipeline_busy = True
        self.set_controls_enabled(False)
        self.stop_button.configure(state="normal")
        self.status_var.set(f"Running: {operation_name}")
        self.append_log("\n" + "=" * 72)
        self.append_log(f"Starting {operation_name}")
        self.append_log("Command: " + " ".join(self.format_command_argument(arg) for arg in command))
        threading.Thread(target=self.command_worker, args=(command, operation_name, on_success), daemon=True).start()

    def command_worker(self, command: List[str], operation_name: str, on_success: Optional[Callable[[], None]]) -> None:
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
        self.after(0, lambda: self.command_finished(operation_name, return_code, on_success))

    def command_finished(self, operation_name: str, return_code: int, on_success: Optional[Callable[[], None]]) -> None:
        self.pipeline_busy = False
        self.set_controls_enabled(True)
        self.stop_button.configure(state="disabled")
        if return_code == 0:
            self.status_var.set(f"Completed: {operation_name}")
            self.append_log(f"{operation_name} completed successfully.")
            if on_success:
                on_success()
        else:
            self.status_var.set(f"Failed: {operation_name}")
            self.append_log(f"{operation_name} exited with code {return_code}.")
            messagebox.showerror("Pipeline operation failed", "See the pipeline log for details.")

    def stop_current_operation(self) -> None:
        if self.running_process is not None and self.running_process.poll() is None:
            self.running_process.terminate()

    def set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.derivatives_selector.set_enabled(enabled)
        self.bids_selector.set_enabled(enabled)
        for widget in (
            self.add_folder_button,
            self.remove_folder_button,
            self.scan_button,
            self.save_settings_button,
            self.scrub_button,
            self.compare_button,
            self.bids_button,
            self.overwrite_checkbox,
        ):
            widget.configure(state=state)

    def append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def process_output_queue(self) -> None:
        while True:
            try:
                message = self.output_queue.get_nowait()
            except Empty:
                break
            self.append_log(message)
        self.after(100, self.process_output_queue)

    @staticmethod
    def format_command_argument(argument: str) -> str:
        return f'"{argument}"' if " " in argument else argument

    def close_dashboard(self) -> None:
        if self.running_process is not None and self.running_process.poll() is None:
            if not messagebox.askyesno("Operation running", "Stop the current operation and close?"):
                return
            self.running_process.terminate()
        self.destroy()


def main() -> None:
    app = PipelineDashboard()
    app.mainloop()


if __name__ == "__main__":
    main()
