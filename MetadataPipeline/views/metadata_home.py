"""Landing pages for CoCANoT Metadata Management."""

from __future__ import annotations

from tkinter import ttk


class MetadataHome(ttk.Frame):
    """Choose between single-patient management and bulk upload."""

    def __init__(
        self,
        parent,
        on_manage_one_patient,
        on_open_bulk_upload,
    ):
        super().__init__(parent)

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
            text="Choose how you want to manage metadata.",
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
            title="Manage One Patient",
            description=(
                "Select one patient to review or update Clinical, Surgical, "
                "Imaging, and Electrophysiology metadata."
            ),
            button_text="Manage One Patient",
            command=on_manage_one_patient,
        )

        self._add_option(
            column=1,
            title="Bulk Upload",
            description=(
                "Add data for multiple patients using Clinical, Surgical, "
                "Imaging, or Electrophysiology pathways."
            ),
            button_text="Open Bulk Upload",
            command=on_open_bulk_upload,
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


class MetadataBulkHome(ttk.Frame):
    """Choose a table-specific or pipeline-specific bulk upload pathway."""

    def __init__(
        self,
        parent,
        on_back,
        on_clinical,
        on_surgical,
        on_imaging,
        on_electrophysiology,
    ):
        super().__init__(parent)

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        ttk.Button(
            self,
            text="Back to Metadata Management",
            command=on_back,
        ).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 10),
        )

        ttk.Label(
            self,
            text="Bulk Upload",
            font=("", 22, "bold"),
        ).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
        )

        ttk.Label(
            self,
            text="Choose the type of data you want to add.",
            wraplength=900,
        ).grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(5, 20),
        )

        options = (
            (
                3,
                0,
                "Clinical Metadata",
                "Import Clinical metadata using the MR Clinical dictionary.",
                "Open Clinical Upload",
                on_clinical,
            ),
            (
                3,
                1,
                "Surgical Metadata",
                "Import Surgical metadata using the MR Surgical dictionary.",
                "Open Surgical Upload",
                on_surgical,
            ),
            (
                4,
                0,
                "Imaging Metadata",
                "Imaging metadata is collected through the Imaging processing workflow.",
                "Continue to Imaging",
                on_imaging,
            ),
            (
                4,
                1,
                "Electrophysiology Metadata",
                (
                    "Electrophysiology metadata is collected through the "
                    "Electrophysiology processing workflow."
                ),
                "Continue to Electrophysiology",
                on_electrophysiology,
            ),
        )

        for row, column, title, description, button_text, command in options:
            card = ttk.LabelFrame(
                self,
                text=title,
                padding=18,
            )
            card.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=(0, 8) if column == 0 else (8, 0),
                pady=(0, 8) if row == 3 else (8, 0),
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
