"""Patient-centered review of metadata and linked local data."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from MetadataPipeline.storage.data_link_store import (
    PatientDataLinkStore,
)


METADATA_PIPELINE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = METADATA_PIPELINE_DIR.parent
NIFTI_VIEWER_SCRIPT = (
    PROJECT_ROOT
    / "ImagingPipeline"
    / "views"
    / "nifti_viewer.py"
)


class PatientDataReview(tk.Toplevel):
    """Show one CoCANoT record together with its linked local BIDS data."""

    def __init__(
        self,
        parent,
        table_name,
        record,
        on_edit_metadata=None,
        on_delete=None,
    ):
        super().__init__(parent)
        self.table_name = table_name
        self.record = record
        self.on_edit_metadata = on_edit_metadata
        self.on_delete = on_delete
        self.data_links = PatientDataLinkStore()

        self._signal_reader = None
        self._signal_figure = None
        self._signal_canvas = None
        self._signal_toolbar = None
        self._signal_channel_vars = []
        self._signal_channels = []
        self._signal_start_seconds = 0.0
        self._signal_duration_seconds = 10.0
        self._signal_total_duration = 0.0
        self._signal_fs = None

        self.title("Patient Data Review")
        self.geometry("1180x860")
        self.minsize(900, 650)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._build_interface()

    def _build_interface(self):
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="Patient Data Review",
            font=("", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")

        patient_id = str(self.record.get("patient_id", "") or "")
        record_id = str(self.record.get("record_id", "") or "")

        ttk.Label(
            header,
            text=(
                f"Patient: {patient_id}   |   "
                f"{self.table_name}: {record_id}"
            ),
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        self.notebook = ttk.Notebook(outer)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        metadata_tab = ttk.Frame(self.notebook, padding=10)
        data_tab = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(metadata_tab, text="CoCANoT Metadata")
        self.notebook.add(data_tab, text="Linked Data")

        self._build_metadata_tab(metadata_tab)
        self._build_data_tab(data_tab)

        if self.table_name == "Electrophysiology":
            signal_tab = ttk.Frame(self.notebook, padding=10)
            self.notebook.add(signal_tab, text="Signal Viewer")
            self._build_signal_tab(signal_tab)

        actions = ttk.Frame(outer)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        ttk.Button(actions, text="Close", command=self._close).pack(side="right")

        if self.on_edit_metadata is not None:
            ttk.Button(
                actions,
                text="Edit CoCANoT Metadata",
                command=self._edit_metadata,
            ).pack(side="right", padx=(0, 8))

        if self.on_delete is not None:
            ttk.Button(
                actions,
                text="Delete Record",
                command=self._delete_record,
            ).pack(side="left")

    def _build_metadata_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        tree = ttk.Treeview(
            parent,
            columns=("field", "value"),
            show="headings",
        )
        tree.heading("field", text="Field")
        tree.heading("value", text="Value")
        tree.column("field", width=330, anchor="nw")
        tree.column("value", width=680, anchor="nw")
        tree.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)

        metadata = self.record.get("metadata", {})
        if type(metadata) is not dict:
            metadata = {}

        for index, (field_name, value) in enumerate(metadata.items(), start=1):
            tree.insert(
                "",
                "end",
                iid=f"metadata-{index}",
                values=(field_name, self._display_value(value)),
            )

    def _linked_data(self):
        context = self.record.get("context", {})
        if type(context) is not dict:
            context = {}

        linked = dict(context)
        stored = self.data_links.get_link(
            self.record.get("site_id", ""),
            self.record.get("patient_id", ""),
            self.table_name,
            self.record.get("record_id", ""),
        )
        linked.update(stored)
        return linked

    def _build_data_tab(self, parent):
        parent.columnconfigure(0, weight=1)

        context = self._linked_data()
        data_path = self._context_path(context, "bids_data_path")
        sidecar_path = self._context_path(context, "bids_sidecar_path")

        status_frame = ttk.LabelFrame(parent, text="Data Connection", padding=12)
        status_frame.grid(row=0, column=0, sticky="ew")
        status_frame.columnconfigure(1, weight=1)

        available = data_path is not None and data_path.is_file()

        rows = [
            ("Status", "Available" if available else "No linked final BIDS file recorded"),
            ("Project", context.get("project", "")),
            ("Session ID", context.get("session_id", "")),
            ("BIDS data file", str(data_path) if data_path is not None else ""),
            ("BIDS sidecar", str(sidecar_path) if sidecar_path is not None else ""),
        ]

        if self.table_name == "Imaging":
            rows.append(("Defacing source", context.get("defacing_source", "")))

        if self.table_name == "Electrophysiology":
            rows.extend([
                ("Channels table", context.get("bids_channels_path", "")),
                ("Electrodes table", context.get("bids_electrodes_path", "")),
                ("Coordinate system", context.get("bids_coordsystem_path", "")),
            ])

        for row_index, (label, value) in enumerate(rows):
            self._data_row(status_frame, row_index, label, value)

        buttons = ttk.Frame(parent)
        buttons.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        if available:
            if self.table_name == "Imaging":
                ttk.Button(
                    buttons,
                    text="Open Image",
                    command=lambda: self._open_image_viewer(data_path),
                ).pack(side="left")
            elif self.table_name == "Electrophysiology":
                ttk.Button(
                    buttons,
                    text="View Recording Signals",
                    command=self._show_signal_tab,
                ).pack(side="left")

            ttk.Button(
                buttons,
                text="Open Data Folder",
                command=lambda: self._open_path(data_path.parent),
            ).pack(side="left", padx=(6, 0))

        if sidecar_path is not None and sidecar_path.is_file():
            ttk.Button(
                buttons,
                text="Open BIDS Sidecar",
                command=lambda: self._open_path(sidecar_path),
            ).pack(side="left", padx=(6, 0))

        if not available:
            ttk.Label(
                parent,
                text=(
                    "This record has CoCANoT metadata, but no final BIDS "
                    "file is linked yet. New Imaging and Electrophysiology "
                    "conversions will save that connection automatically. "
                    "Existing records can be linked by re-running their "
                    "BIDS conversion."
                ),
                wraplength=900,
            ).grid(row=2, column=0, sticky="w", pady=(14, 0))

    def _build_signal_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        context = self._linked_data()
        self._signal_path = self._context_path(context, "bids_data_path")

        top = ttk.Frame(parent)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(6, weight=1)

        ttk.Label(top, text="Display window").grid(row=0, column=0, sticky="w")
        self._signal_window_var = tk.StringVar(value="10")
        window_box = ttk.Combobox(
            top,
            textvariable=self._signal_window_var,
            values=("10", "30", "60"),
            state="readonly",
            width=6,
        )
        window_box.grid(row=0, column=1, sticky="w", padx=(6, 12))
        window_box.bind("<<ComboboxSelected>>", lambda _e: self._signal_window_changed())

        ttk.Button(top, text="◀ Previous", command=self._signal_previous).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(top, text="Next ▶", command=self._signal_next).grid(row=0, column=3, padx=(0, 12))

        ttk.Label(top, text="Start (s)").grid(row=0, column=4, sticky="w")
        self._signal_start_var = tk.StringVar(value="0")
        start_entry = ttk.Entry(top, textvariable=self._signal_start_var, width=10)
        start_entry.grid(row=0, column=5, sticky="w", padx=(6, 8))
        start_entry.bind("<Return>", lambda _e: self._signal_jump())
        ttk.Button(top, text="Go", command=self._signal_jump).grid(row=0, column=6, sticky="w")

        self._signal_status_var = tk.StringVar(value="Loading EDF recording…")
        ttk.Label(parent, textvariable=self._signal_status_var).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(8, 6),
        )

        plot_frame = ttk.Frame(parent)
        plot_frame.grid(row=2, column=0, sticky="nsew")
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.rowconfigure(0, weight=1)
        self._signal_plot_frame = plot_frame

        if self._signal_path is None or not self._signal_path.is_file():
            self._signal_status_var.set("No linked EDF file is available for this record.")
            return

        self.after_idle(self._initialize_signal_viewer)

    def _initialize_signal_viewer(self):
        try:
            import pyedflib
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
            from matplotlib.figure import Figure
        except Exception as exc:
            self._signal_status_var.set(
                "Signal viewer unavailable. Install pyedflib and matplotlib in the active environment."
            )
            messagebox.showerror("Signal viewer unavailable", str(exc), parent=self)
            return

        try:
            self._signal_reader = pyedflib.EdfReader(str(self._signal_path))
            signal_count = int(self._signal_reader.signals_in_file)
            self._signal_channels = list(self._signal_reader.getSignalLabels())
            self._signal_total_duration = float(self._signal_reader.file_duration)

            if signal_count == 0:
                self._signal_status_var.set("This EDF contains no signal channels.")
                return

            # Read a manageable number of channels at once for review.
            max_channels = min(signal_count, 12)
            self._signal_channel_indices = list(range(max_channels))

            self._signal_figure = Figure(figsize=(10, 6), dpi=100)
            self._signal_axes = self._signal_figure.add_subplot(111)
            self._signal_canvas = FigureCanvasTkAgg(self._signal_figure, master=self._signal_plot_frame)
            self._signal_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

            toolbar = NavigationToolbar2Tk(self._signal_canvas, self._signal_plot_frame, pack_toolbar=False)
            toolbar.update()
            toolbar.grid(row=1, column=0, sticky="ew")
            self._signal_toolbar = toolbar

            self._draw_signal_window()
        except Exception as exc:
            self._signal_status_var.set("Could not load EDF recording.")
            messagebox.showerror("Could not load EDF", str(exc), parent=self)

    def _draw_signal_window(self):
        if self._signal_reader is None or self._signal_figure is None:
            return

        import numpy as np

        duration = float(self._signal_window_var.get() or 10)
        duration = max(1.0, duration)
        self._signal_duration_seconds = duration

        max_start = max(0.0, self._signal_total_duration - duration)
        self._signal_start_seconds = min(max(0.0, self._signal_start_seconds), max_start)
        self._signal_start_var.set(f"{self._signal_start_seconds:.1f}")

        ax = self._signal_axes
        ax.clear()

        plotted = 0
        offset_step = 1.0
        labels = []
        tick_positions = []

        for display_index, channel_index in enumerate(self._signal_channel_indices):
            sample_frequency = float(self._signal_reader.getSampleFrequency(channel_index))
            if sample_frequency <= 0:
                continue

            start_sample = int(round(self._signal_start_seconds * sample_frequency))
            sample_count = int(round(duration * sample_frequency))
            total_samples = int(self._signal_reader.getNSamples()[channel_index])
            sample_count = max(0, min(sample_count, total_samples - start_sample))
            if sample_count <= 0:
                continue

            signal = self._signal_reader.readSignal(
                channel_index,
                start=start_sample,
                n=sample_count,
            )
            signal = np.asarray(signal, dtype=float)
            if signal.size == 0:
                continue

            centered = signal - np.nanmedian(signal)
            scale = np.nanpercentile(np.abs(centered), 95)
            if not np.isfinite(scale) or scale <= 0:
                scale = np.nanmax(np.abs(centered))
            if not np.isfinite(scale) or scale <= 0:
                scale = 1.0

            normalized = centered / scale
            offset = display_index * 3.0
            times = self._signal_start_seconds + np.arange(signal.size) / sample_frequency
            ax.plot(times, normalized + offset, linewidth=0.8)

            labels.append(self._signal_channels[channel_index].strip() or f"Ch {channel_index + 1}")
            tick_positions.append(offset)
            plotted += 1

        ax.set_xlabel("Time (seconds)")
        if plotted:
            ax.set_yticks(tick_positions)
            ax.set_yticklabels(labels)
            ax.set_xlim(
                self._signal_start_seconds,
                min(self._signal_start_seconds + duration, self._signal_total_duration),
            )
            ax.set_title(
                f"EDF signals — {Path(self._signal_path).name}"
            )
            ax.grid(True, axis="x", alpha=0.2)
        else:
            ax.text(0.5, 0.5, "No signal samples available in this window.", ha="center", va="center")
            ax.set_axis_off()

        self._signal_figure.tight_layout()
        self._signal_canvas.draw_idle()
        self._signal_status_var.set(
            f"Showing {plotted} channel(s) | "
            f"{self._signal_start_seconds:.1f}–"
            f"{min(self._signal_start_seconds + duration, self._signal_total_duration):.1f} s "
            f"of {self._signal_total_duration:.1f} s"
        )

    def _signal_window_changed(self):
        try:
            self._signal_duration_seconds = float(self._signal_window_var.get())
        except ValueError:
            self._signal_duration_seconds = 10.0
        self._draw_signal_window()

    def _signal_previous(self):
        self._signal_start_seconds = max(
            0.0,
            self._signal_start_seconds - self._signal_duration_seconds,
        )
        self._draw_signal_window()

    def _signal_next(self):
        self._signal_start_seconds = min(
            max(0.0, self._signal_total_duration - self._signal_duration_seconds),
            self._signal_start_seconds + self._signal_duration_seconds,
        )
        self._draw_signal_window()

    def _signal_jump(self):
        try:
            self._signal_start_seconds = float(self._signal_start_var.get().strip())
        except ValueError:
            messagebox.showerror(
                "Invalid start time",
                "Enter a numeric start time in seconds.",
                parent=self,
            )
            return
        self._draw_signal_window()

    def _show_signal_tab(self):
        for tab_id in self.notebook.tabs():
            if self.notebook.tab(tab_id, "text") == "Signal Viewer":
                self.notebook.select(tab_id)
                return

    @staticmethod
    def _data_row(parent, row, label, value):
        ttk.Label(parent, text=label, font=("", 10, "bold")).grid(
            row=row,
            column=0,
            sticky="nw",
            padx=(0, 12),
            pady=3,
        )
        ttk.Label(
            parent,
            text=(str(value) if value not in (None, "") else "—"),
            wraplength=760,
        ).grid(row=row, column=1, sticky="nw", pady=3)

    @staticmethod
    def _display_value(value):
        if type(value) is list:
            return ", ".join(str(item) for item in value)
        if type(value) is dict:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _context_path(context, key):
        value = str(context.get(key, "") or "").strip()
        if not value:
            return None
        return Path(value).expanduser()

    def _edit_metadata(self):
        callback = self.on_edit_metadata
        self._close()
        if callback is not None:
            callback()

    def _delete_record(self):
        if self.on_delete is None:
            return
        if self.on_delete(self.record):
            self._close()

    def _open_image_viewer(self, path):
        path = Path(path).expanduser()

        if not path.is_file():
            messagebox.showerror(
                "Image not found",
                f"The linked NIfTI file no longer exists:\n\n{path}",
                parent=self,
            )
            return

        if not NIFTI_VIEWER_SCRIPT.is_file():
            messagebox.showerror(
                "Image viewer unavailable",
                (
                    "Could not find the CoCANoT NIfTI viewer:\n\n"
                    f"{NIFTI_VIEWER_SCRIPT}"
                ),
                parent=self,
            )
            return

        try:
            subprocess.Popen(
                [sys.executable, str(NIFTI_VIEWER_SCRIPT), str(path)],
                cwd=str(PROJECT_ROOT),
            )
        except OSError as exc:
            messagebox.showerror(
                "Could not open image viewer",
                str(exc),
                parent=self,
            )

    def _open_path(self, path):
        path = Path(path).expanduser()

        if not path.exists():
            messagebox.showerror(
                "File not found",
                f"The linked path no longer exists:\n\n{path}",
                parent=self,
            )
            return

        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif os.name == "nt":
                os.startfile(str(path))
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror(
                "Could not open file",
                str(exc),
                parent=self,
            )

    def _close(self):
        if self._signal_reader is not None:
            try:
                self._signal_reader.close()
            except Exception:
                pass
            self._signal_reader = None
        self.destroy()
