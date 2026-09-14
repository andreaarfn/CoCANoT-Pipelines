"""Landing page for CoCANoT Metadata Management."""

from __future__ import annotations

from tkinter import ttk


class MetadataHome(ttk.Frame):
    """Choose between participant-level review and site-level batch import."""

    def __init__(
        self,
        parent,
        on_open_patient_explorer,
        on_open_batch_import,
    ):
        super().__init__(parent)

        self.on_open_patient_explorer = on_open_patient_explorer
        self.on_open_batch_import = on_open_batch_import

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        ttk.Label(
            self,
            text="Metadata Management",
            font=("", 22, "bold"),
        ).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
        )

        ttk.Label(
            self,
            text=(
                "Review metadata for one participant or import "
                "validated metadata for multiple participants."
            ),
            wraplength=900,
        ).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(5, 20),
        )

        self._add_option(
            column=0,
            title="Patient Explorer",
            description=(
                "Review or edit Clinical, Surgical, Imaging, and "
                "Electrophysiology metadata for one participant."
            ),
            button_text="Open Patient Explorer",
            command=self.on_open_patient_explorer,
        )

        self._add_option(
            column=1,
            title="Batch Import",
            description=(
                "Import and validate Clinical or Surgical metadata "
                "for multiple participants in one CSV or Excel file."
            ),
            button_text="Open Batch Import",
            command=self.on_open_batch_import,
        )

    def _add_option(
        self,
        column,
        title,
        description,
        button_text,
        command,
    ):
        card = ttk.LabelFrame(
            self,
            text=title,
            padding=18,
        )
        card.grid(
            row=2,
            column=column,
            sticky="nsew",
            padx=(0, 8) if column == 0 else (8, 0),
        )
        card.columnconfigure(0, weight=1)

        ttk.Label(
            card,
            text=description,
            wraplength=410,
        ).grid(
            row=0,
            column=0,
            sticky="nw",
            pady=(0, 18),
        )

        ttk.Button(
            card,
            text=button_text,
            command=command,
        ).grid(
            row=1,
            column=0,
            sticky="w",
        )
