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


class BIDSMetadataWindow(tk.Toplevel):
    """Review scrubbed recordings and assign explicit dataset and recording metadata."""

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
        self.records: Dict[str, Dict[str, str]] = {}

        self.title("BIDS Metadata Review")
        self.geometry("1500x850")
        self.minsize(1120, 680)
        self.transient(parent)

        self.dataset_name_var = tk.StringVar()
        self.dataset_description_var = tk.StringVar()
        self.site_var = tk.StringVar()
        self.task_var = tk.StringVar(value="monitoring")
        self.task_description_var = tk.StringVar()
        self.datatype_var = tk.StringVar(value="eeg")
        self.manufacturer_var = tk.StringVar()
        self.model_name_var = tk.StringVar()
        self.channel_type_description_var = tk.StringVar()
        self.next_subject_number = 1

        self.build_interface()
        self.load_scrubbed_files()

    def build_interface(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        ttk.Label(root, text="BIDS Metadata Review", font=("", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            root,
            text=(
                "Assign a dataset and recording metadata to selected rows. "
                "Each dataset name creates a separate folder inside the BIDS output folder."
            ),
            wraplength=1400,
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))

        table_frame = ttk.Frame(root)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = (
            "include", "file", "dataset", "participant", "task",
            "datatype", "site", "manufacturer", "model", "age", "sex",
        )
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
        )
        headings = {
            "include": "Include",
            "file": "Scrubbed EDF",
            "dataset": "Dataset",
            "participant": "Participant ID",
            "task": "Task",
            "datatype": "Datatype",
            "site": "Site",
            "manufacturer": "Manufacturer",
            "model": "Model Name",
            "age": "Age",
            "sex": "Sex",
        }
        widths = {
            "include": 65,
            "file": 300,
            "dataset": 170,
            "participant": 120,
            "task": 100,
            "datatype": 75,
            "site": 80,
            "manufacturer": 130,
            "model": 130,
            "age": 55,
            "sex": 60,
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

        controls = ttk.LabelFrame(root, text="Metadata to apply", padding=12)
        controls.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        for index in range(6):
            controls.columnconfigure(index, weight=1 if index in (1, 3, 5) else 0)

        ttk.Label(controls, text="Dataset name").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.dataset_name_var).grid(
            row=0, column=1, sticky="ew", padx=(6, 12)
        )
        ttk.Label(controls, text="Dataset description").grid(row=0, column=2, sticky="w")
        ttk.Entry(controls, textvariable=self.dataset_description_var).grid(
            row=0, column=3, columnspan=3, sticky="ew", padx=(6, 0)
        )

        ttk.Label(controls, text="Site code").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(controls, textvariable=self.site_var).grid(
            row=1, column=1, sticky="ew", padx=(6, 12), pady=(8, 0)
        )
        ttk.Label(controls, text="Task").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(controls, textvariable=self.task_var).grid(
            row=1, column=3, sticky="ew", padx=(6, 12), pady=(8, 0)
        )
        ttk.Label(controls, text="Datatype").grid(row=1, column=4, sticky="w", pady=(8, 0))
        ttk.Combobox(
            controls,
            textvariable=self.datatype_var,
            values=("eeg", "ieeg"),
            state="readonly",
            width=8,
        ).grid(row=1, column=5, sticky="ew", padx=(6, 0), pady=(8, 0))

        ttk.Label(controls, text="Task description").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(controls, textvariable=self.task_description_var).grid(
            row=2, column=1, columnspan=5, sticky="ew", padx=(6, 0), pady=(8, 0)
        )

        ttk.Label(controls, text="Manufacturer").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(controls, textvariable=self.manufacturer_var).grid(
            row=3, column=1, sticky="ew", padx=(6, 12), pady=(8, 0)
        )
        ttk.Label(controls, text="Model name").grid(row=3, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(controls, textvariable=self.model_name_var).grid(
            row=3, column=3, sticky="ew", padx=(6, 12), pady=(8, 0)
        )
        ttk.Label(controls, text="Channel type description").grid(
            row=3, column=4, sticky="w", pady=(8, 0)
        )
        ttk.Entry(controls, textvariable=self.channel_type_description_var).grid(
            row=3, column=5, sticky="ew", padx=(6, 0), pady=(8, 0)
        )

        apply_actions = ttk.Frame(controls)
        apply_actions.grid(row=4, column=0, columnspan=6, sticky="e", pady=(10, 0))
        ttk.Button(
            apply_actions,
            text="Apply to Selected",
            command=self.apply_to_selected,
        ).pack(side="left")
        ttk.Button(
            apply_actions,
            text="Apply to All",
            command=self.apply_to_all,
        ).pack(side="left", padx=(8, 0))

        actions = ttk.Frame(root)
        actions.grid(row=4, column=0, sticky="ew", pady=(12, 0))

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
            text="Generate Different Participant IDs",
            command=self.generate_distinct_ids,
        ).pack(side="left", padx=(18, 0))
        ttk.Button(
            actions,
            text="Assign Same Participant ID",
            command=self.assign_same_id,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            actions,
            text="Edit Participant ID",
            command=self.edit_participant_id,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            actions,
            text="Convert Included Recordings",
            command=self.create_manifest_and_convert,
        ).pack(side="right")

    @staticmethod
    def matching_sidecar(edf_path: Path) -> Optional[Path]:
        candidates = [
            edf_path.with_suffix(".json"),
            edf_path.with_name(edf_path.stem + "_metadata.json"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

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

    def sidecar_demographics(self, sidecar: Optional[Path]) -> tuple[str, str]:
        if sidecar is None:
            return "n/a", "n/a"
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "n/a", "n/a"
        age = self.find_nested_value(
            payload, {"age", "age_at_recording", "participant_age"}
        ) or "n/a"
        sex = self.find_nested_value(
            payload, {"sex", "gender", "participant_sex"}
        ) or "n/a"
        return age, sex

    def load_scrubbed_files(self) -> None:
        edf_files = sorted(
            path for path in self.scrubbed_dir.rglob("*")
            if path.is_file() and path.suffix.lower() == ".edf"
        )
        for index, edf_path in enumerate(edf_files, start=1):
            sidecar = self.matching_sidecar(edf_path)
            age, sex = self.sidecar_demographics(sidecar)
            item_id = f"record-{index}"
            self.records[item_id] = {
                "edf_path": str(edf_path.resolve()),
                "sidecar_path": str(sidecar.resolve()) if sidecar else "",
                "source_label": str(edf_path.relative_to(self.scrubbed_dir)),
                "include": "Yes",
                "dataset_name": "",
                "dataset_description": "",
                "participant": "",
                "task": "",
                "task_description": "",
                "datatype": "",
                "site": "",
                "manufacturer": "",
                "model_name": "",
                "channel_type_description": "",
                "age": age,
                "sex": sex,
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
            record["dataset_name"],
            record["participant"],
            record["task"],
            record["datatype"],
            record["site"],
            record["manufacturer"],
            record["model_name"],
            record["age"],
            record["sex"],
        )
        if self.tree.exists(item_id):
            self.tree.item(item_id, values=values)
        else:
            self.tree.insert("", "end", iid=item_id, values=values)

    def target_ids(self, all_rows: bool = False) -> List[str]:
        if all_rows:
            return list(self.records)
        selected = list(self.tree.selection())
        if not selected:
            messagebox.showinfo(
                "No selection",
                "Select one or more recordings first.",
                parent=self,
            )
        return selected

    def metadata_values(self) -> Dict[str, str]:
        return {
            "dataset_name": self.dataset_name_var.get().strip(),
            "dataset_description": self.dataset_description_var.get().strip(),
            "site": self.site_var.get().strip(),
            "task": self.task_var.get().strip(),
            "task_description": self.task_description_var.get().strip(),
            "datatype": self.datatype_var.get().strip().lower(),
            "manufacturer": self.manufacturer_var.get().strip(),
            "model_name": self.model_name_var.get().strip(),
            "channel_type_description": self.channel_type_description_var.get().strip(),
        }

    def apply_metadata(self, item_ids: List[str]) -> None:
        values = self.metadata_values()
        missing = [
            label
            for key, label in (
                ("dataset_name", "dataset name"),
                ("dataset_description", "dataset description"),
                ("site", "site code"),
                ("task", "task"),
                ("task_description", "task description"),
                ("manufacturer", "manufacturer"),
                ("model_name", "model name"),
                ("channel_type_description", "channel type description"),
            )
            if not values[key]
        ]
        if values["datatype"] not in {"eeg", "ieeg"}:
            missing.append("datatype")
        if missing:
            messagebox.showerror(
                "Missing metadata",
                "Complete these fields before applying:\n\n" + "\n".join(missing),
                parent=self,
            )
            return

        for item_id in item_ids:
            self.records[item_id].update(values)
            self.refresh_row(item_id)

    def apply_to_selected(self) -> None:
        ids = self.target_ids()
        if ids:
            self.apply_metadata(ids)

    def apply_to_all(self) -> None:
        self.apply_metadata(self.target_ids(all_rows=True))

    def set_selected_included(self, included: bool) -> None:
        for item_id in self.target_ids():
            self.records[item_id]["include"] = "Yes" if included else "No"
            self.refresh_row(item_id)

    def toggle_inclusion_at_pointer(self, event: tk.Event) -> None:
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        current = self.records[item_id]["include"]
        self.records[item_id]["include"] = "No" if current == "Yes" else "Yes"
        self.refresh_row(item_id)

    def next_generated_id(self) -> str:
        used = {
            record["participant"].replace("sub-", "")
            for record in self.records.values()
            if record["participant"]
        }
        while True:
            candidate = f"{self.next_subject_number:06d}"
            self.next_subject_number += 1
            if candidate not in used:
                return f"sub-{candidate}"

    def generate_distinct_ids(self) -> None:
        for item_id in self.target_ids():
            self.records[item_id]["participant"] = self.next_generated_id()
            self.refresh_row(item_id)

    def assign_same_id(self) -> None:
        ids = self.target_ids()
        if not ids:
            return
        existing = next(
            (
                self.records[item]["participant"]
                for item in ids
                if self.records[item]["participant"]
            ),
            "",
        )
        value = simpledialog.askstring(
            "Participant ID",
            "Enter a de-identified participant ID, or leave blank to generate one:",
            initialvalue=existing,
            parent=self,
        )
        if value is None:
            return
        value = value.strip() or self.next_generated_id()
        for item_id in ids:
            self.records[item_id]["participant"] = value
            self.refresh_row(item_id)

    def edit_participant_id(self) -> None:
        ids = self.target_ids()
        if len(ids) != 1:
            messagebox.showinfo(
                "Select one",
                "Select exactly one recording to edit.",
                parent=self,
            )
            return
        item_id = ids[0]
        value = simpledialog.askstring(
            "Participant ID",
            "Enter the de-identified participant ID:",
            initialvalue=self.records[item_id]["participant"],
            parent=self,
        )
        if value is not None and value.strip():
            self.records[item_id]["participant"] = value.strip()
            self.refresh_row(item_id)

    def create_manifest_and_convert(self) -> None:
        included = [
            record for record in self.records.values()
            if record["include"] == "Yes"
        ]
        if not included:
            messagebox.showerror(
                "Nothing selected",
                "Include at least one recording.",
                parent=self,
            )
            return

        required = (
            "dataset_name",
            "dataset_description",
            "participant",
            "task",
            "task_description",
            "datatype",
            "site",
            "manufacturer",
            "model_name",
            "channel_type_description",
        )
        missing: List[str] = []
        for record in included:
            absent = [name for name in required if not record[name]]
            if absent:
                missing.append(f"{record['source_label']}: {', '.join(absent)}")
        if missing:
            messagebox.showerror(
                "Incomplete metadata",
                "Complete the required fields before conversion:\n\n"
                + "\n".join(missing[:15]),
                parent=self,
            )
            return

        dataset_descriptions: Dict[str, str] = {}
        conflicts: List[str] = []
        for record in included:
            name = record["dataset_name"]
            description = record["dataset_description"]
            existing = dataset_descriptions.get(name)
            if existing is not None and existing != description:
                conflicts.append(name)
            dataset_descriptions[name] = description
        if conflicts:
            messagebox.showerror(
                "Dataset description conflict",
                "These dataset names have more than one description:\n\n"
                + "\n".join(sorted(set(conflicts))),
                parent=self,
            )
            return

        manifest_path = self.scrubbed_dir.parent / "bids_conversion_manifest.json"
        payload = {
            "bids_version": "1.11.1",
            "records": [
                {
                    "edf_path": record["edf_path"],
                    "sidecar_path": record["sidecar_path"],
                    "participant_id": record["participant"],
                    "task": record["task"],
                    "task_description": record["task_description"],
                    "datatype": record["datatype"],
                    "site": record["site"],
                    "dataset_name": record["dataset_name"],
                    "dataset_description": record["dataset_description"],
                    "manufacturer": record["manufacturer"],
                    "model_name": record["model_name"],
                    "channel_type_description": record["channel_type_description"],
                }
                for record in included
            ],
        }
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

        # Keep this review window open while conversion runs. If the converter
        # reports an error, every annotation remains available for correction.
        # Close the window only after a successful conversion.
        self.parent_dashboard.run_command(
            command,
            "BIDS conversion",
            on_success=self.destroy,
        )
class PipelineDashboard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Electrophysiology Pipeline")
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

        ttk.Label(root, text="Electrophysiology Pipeline", font=("", 22, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            root,
            text=(
                "Add multiple raw EDF folders, scan them, and include only the recordings you want. "
                "Use Shift-click or Ctrl/Cmd-click to select ranges or individual rows."
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
