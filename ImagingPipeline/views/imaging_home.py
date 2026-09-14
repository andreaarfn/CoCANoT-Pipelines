"""Landing page for the Imaging pipeline."""

from __future__ import annotations

from tkinter import ttk


class ImagingHome(ttk.Frame):
    def __init__(
        self,
        parent,
        on_process,
        on_review_patients,
    ):
        super().__init__(
            parent,
            padding=28,
        )

        self.columnconfigure(
            0,
            weight=1,
        )

        ttk.Label(
            self,
            text="Imaging",
            font=("", 24, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            self,
            text=(
                "Choose whether to process new imaging data "
                "or review previously processed participants."
            ),
            wraplength=760,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(6, 24),
        )

        self._add_choice(
            row=2,
            title="Process Imaging",
            description=(
                "De-identify and validate one or more imaging studies."
            ),
            command=on_process,
        )

        self._add_choice(
            row=3,
            title="Review Patients",
            description=(
                "Review previously processed imaging and related metadata."
            ),
            command=on_review_patients,
        )

    def _add_choice(
        self,
        row,
        title,
        description,
        command,
    ):
        frame = ttk.LabelFrame(
            self,
            padding=16,
        )
        frame.grid(
            row=row,
            column=0,
            sticky="ew",
            pady=(0, 12),
        )
        frame.columnconfigure(
            0,
            weight=1,
        )

        ttk.Label(
            frame,
            text=title,
            font=("", 15, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            frame,
            text=description,
            wraplength=720,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(4, 10),
        )

        ttk.Button(
            frame,
            text=title,
            command=command,
        ).grid(
            row=2,
            column=0,
            sticky="w",
        )
