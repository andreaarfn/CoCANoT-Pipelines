#!/usr/bin/env python3
"""Interactive 3D/4D NIfTI viewer used by Patient Data Review."""

from __future__ import annotations

import argparse
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import nibabel as nib
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class NiftiViewer(tk.Tk):
    """Interactively navigate all spatial slices and 4D volumes."""

    def __init__(
        self,
        nifti_path: Path,
    ):
        super().__init__()

        self.nifti_path = nifti_path
        self.image = None
        self.data = None
        self.axes = {}

        self.x_index = 0
        self.y_index = 0
        self.z_index = 0
        self.current_volume = 0
        self.intensity_limits = (
            0.0,
            1.0,
        )

        self.x_var = tk.DoubleVar(
            value=0
        )
        self.y_var = tk.DoubleVar(
            value=0
        )
        self.z_var = tk.DoubleVar(
            value=0
        )
        self.volume_var = tk.DoubleVar(
            value=0
        )
        self.status_var = tk.StringVar(
            value=""
        )

        self.title(
            f"NIfTI Image Review - {self.nifti_path.name}"
        )
        self.geometry(
            "1250x900"
        )
        self.minsize(
            900,
            650,
        )

        self._build_interface()
        self._load_image()

    def _build_interface(
        self,
    ):
        root = ttk.Frame(
            self,
            padding=12,
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
            1,
            weight=1,
        )

        header = ttk.Frame(
            root
        )
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 8),
        )
        header.columnconfigure(
            0,
            weight=1,
        )

        ttk.Label(
            header,
            text="Interactive NIfTI Review",
            font=(
                "",
                18,
                "bold",
            ),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            header,
            text=str(
                self.nifti_path
            ),
            wraplength=950,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(3, 0),
        )

        image_frame = ttk.LabelFrame(
            root,
            text="Linked 3D / 4D navigation",
            padding=8,
        )
        image_frame.grid(
            row=1,
            column=0,
            sticky="nsew",
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
            figsize=(
                12,
                6,
            ),
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
        ) = self._axis_control(
            controls,
            0,
            "Sagittal X",
            self.x_var,
            self._x_changed,
        )

        (
            self.y_scale,
            self.y_label,
        ) = self._axis_control(
            controls,
            1,
            "Coronal Y",
            self.y_var,
            self._y_changed,
        )

        (
            self.z_scale,
            self.z_label,
        ) = self._axis_control(
            controls,
            2,
            "Axial Z",
            self.z_var,
            self._z_changed,
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
                "Use the mouse wheel over Axial, Coronal, or Sagittal "
                "to move through the complete slice stack. Click inside "
                "a view to reposition the linked location. For 4D data, "
                "use the volume slider to review every time point."
            ),
            wraplength=1050,
        ).grid(
            row=4,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(7, 0),
        )

        footer = ttk.Frame(
            root
        )
        footer.grid(
            row=2,
            column=0,
            sticky="ew",
            pady=(8, 0),
        )

        ttk.Label(
            footer,
            textvariable=self.status_var,
        ).pack(
            side="left",
        )

        ttk.Button(
            footer,
            text="Close",
            command=self.destroy,
        ).pack(
            side="right",
        )

    @staticmethod
    def _axis_control(
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

        return (
            scale,
            value_label,
        )

    def _load_image(
        self,
    ):
        try:
            self.image = nib.load(
                str(
                    self.nifti_path
                )
            )
        except Exception as exc:
            messagebox.showerror(
                "Could not open NIfTI",
                str(
                    exc
                ),
                parent=self,
            )
            self.destroy()
            return

        if len(
            self.image.shape
        ) not in {
            3,
            4,
        }:
            messagebox.showerror(
                "Unsupported NIfTI",
                (
                    "Patient Data Review currently supports "
                    "3D and 4D NIfTI images."
                ),
                parent=self,
            )
            self.destroy()
            return

        self.data = self.image.dataobj
        shape = self.image.shape

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

        self.status_var.set(
            (
                f"Shape: {shape}"
                + (
                    f" | Volumes: {shape[3]}"
                    if len(shape) == 4
                    else ""
                )
            )
        )

    def _current_volume_data(
        self,
    ):
        if self.data is None:
            raise RuntimeError(
                "No image loaded."
            )

        if len(
            self.image.shape
        ) == 4:
            return np.asanyarray(
                self.data[
                    ...,
                    self.current_volume
                ]
            )

        return np.asanyarray(
            self.data
        )

    def _update_intensity_limits(
        self,
    ):
        data = self._current_volume_data()
        finite = data[
            np.isfinite(
                data
            )
        ]

        if finite.size == 0:
            self.intensity_limits = (
                0.0,
                1.0,
            )
            return

        low, high = np.percentile(
            finite,
            [
                1,
                99,
            ],
        )
        low = float(
            low
        )
        high = float(
            high
        )

        if high <= low:
            high = (
                low + 1.0
            )

        self.intensity_limits = (
            low,
            high,
        )

    @staticmethod
    def _clamp(
        value,
        size,
    ):
        return max(
            0,
            min(
                size - 1,
                value,
            ),
        )

    def _x_changed(
        self,
        value,
    ):
        if self.image is None:
            return

        self.x_index = self._clamp(
            int(
                round(
                    float(
                        value
                    )
                )
            ),
            self.image.shape[0],
        )
        self._refresh_coordinate_labels()
        self._draw_views()

    def _y_changed(
        self,
        value,
    ):
        if self.image is None:
            return

        self.y_index = self._clamp(
            int(
                round(
                    float(
                        value
                    )
                )
            ),
            self.image.shape[1],
        )
        self._refresh_coordinate_labels()
        self._draw_views()

    def _z_changed(
        self,
        value,
    ):
        if self.image is None:
            return

        self.z_index = self._clamp(
            int(
                round(
                    float(
                        value
                    )
                )
            ),
            self.image.shape[2],
        )
        self._refresh_coordinate_labels()
        self._draw_views()

    def _volume_changed(
        self,
        value,
    ):
        if (
            self.image is None
            or len(
                self.image.shape
            ) != 4
        ):
            return

        self.current_volume = self._clamp(
            int(
                round(
                    float(
                        value
                    )
                )
            ),
            self.image.shape[3],
        )
        self._update_intensity_limits()
        self._refresh_coordinate_labels()
        self._draw_views()

    def _refresh_coordinate_labels(
        self,
    ):
        if self.image is None:
            return

        shape = self.image.shape

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

    def _draw_views(
        self,
    ):
        if self.image is None:
            return

        try:
            data = self._current_volume_data()
        except Exception as exc:
            self.status_var.set(
                str(
                    exc
                )
            )
            return

        self.figure.clear()
        self.axes = {}

        views = (
            (
                "Axial",
                np.rot90(
                    data[
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
                    data[
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
                    data[
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
            title,
            view,
            plane,
        ) in enumerate(
            views,
            start=1,
        ):
            axis = self.figure.add_subplot(
                1,
                3,
                column,
            )
            axis.imshow(
                view,
                cmap="gray",
                origin="lower",
                vmin=low,
                vmax=high,
            )
            axis.set_title(
                title
            )
            axis.axis(
                "off"
            )
            self.axes[
                axis
            ] = plane

        if len(
            self.image.shape
        ) == 4:
            title = (
                "Linked 3D navigation | "
                f"Volume {self.current_volume} / "
                f"{self.image.shape[3] - 1}"
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
    ):
        if (
            self.image is None
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
                self.image.shape[2],
            )
            self.z_var.set(
                self.z_index
            )

        elif plane == "coronal":
            self.y_index = self._clamp(
                self.y_index + direction,
                self.image.shape[1],
            )
            self.y_var.set(
                self.y_index
            )

        elif plane == "sagittal":
            self.x_index = self._clamp(
                self.x_index + direction,
                self.image.shape[0],
            )
            self.x_var.set(
                self.x_index
            )

        self._refresh_coordinate_labels()
        self._draw_views()

    def _on_figure_click(
        self,
        event,
    ):
        if (
            self.image is None
            or event.inaxes not in self.axes
            or event.xdata is None
            or event.ydata is None
        ):
            return

        plane = self.axes[
            event.inaxes
        ]
        shape = self.image.shape

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


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Open a de-identified 3D or 4D NIfTI "
            "in the CoCANoT interactive viewer."
        )
    )
    parser.add_argument(
        "nifti_path",
        type=Path,
    )
    return parser.parse_args()


def main():
    args = parse_args()
    path = args.nifti_path.expanduser().resolve()

    if (
        not path.is_file()
        or not path.name.endswith(
            (
                ".nii",
                ".nii.gz",
            )
        )
    ):
        raise SystemExit(
            f"Invalid NIfTI path: {path}"
        )

    app = NiftiViewer(
        path
    )
    app.mainloop()


if __name__ == "__main__":
    main()
