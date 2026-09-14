"""Clinical Assessment review window."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ClinicalAssessmentReview(tk.Toplevel):
    """Review one Clinical Assessment and edit it when it is current."""

    def __init__(
        self,
        parent,
        dictionary,
        record,
        editable,
        on_edit,
    ):
        super().__init__(
            parent
        )
        self.dictionary = dictionary
        self.record = record
        self.editable = editable
        self.on_edit = on_edit

        self.title(
            f"Clinical Assessment — {record['record_id']}"
        )
        self.geometry(
            "900x720"
        )
        self.minsize(
            720,
            560,
        )
        self.transient(
            parent
        )

        self._build_interface()

    def _build_interface(self):
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
            1,
            weight=1,
        )

        patient_id = self.record[
            "patient_id"
        ]
        assessment_id = self.record[
            "record_id"
        ]

        ttk.Label(
            root,
            text=f"Clinical Assessment {assessment_id}",
            font=(
                "",
                17,
                "bold",
            ),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            root,
            text=f"CoCANoT Patient ID: {patient_id}",
        ).grid(
            row=0,
            column=1,
            sticky="e",
        )

        shell = ttk.Frame(
            root
        )
        shell.grid(
            row=1,
            column=0,
            columnspan=2,
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

        canvas = tk.Canvas(
            shell,
            highlightthickness=0,
        )
        canvas.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        scroll = ttk.Scrollbar(
            shell,
            orient="vertical",
            command=canvas.yview,
        )
        scroll.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        canvas.configure(
            yscrollcommand=scroll.set,
        )

        body = ttk.Frame(
            canvas
        )
        body_id = canvas.create_window(
            (0, 0),
            window=body,
            anchor="nw",
        )
        body.columnconfigure(
            1,
            weight=1,
        )

        body.bind(
            "<Configure>",
            lambda _event: canvas.configure(
                scrollregion=canvas.bbox(
                    "all"
                )
            ),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(
                body_id,
                width=event.width,
            ),
        )

        metadata = self.record[
            "metadata"
        ]
        rules = self.dictionary[
            "tables"
        ]["Clinical"]["fields"]

        row_index = 0

        for rule in rules:
            field_name = rule[
                "field_name"
            ]
            value = metadata.get(
                field_name
            )

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
                shown = str(
                    value
                )

            ttk.Label(
                body,
                text=field_name,
            ).grid(
                row=row_index,
                column=0,
                sticky="nw",
                padx=(0, 12),
                pady=4,
            )

            ttk.Label(
                body,
                text=shown,
                wraplength=520,
            ).grid(
                row=row_index,
                column=1,
                sticky="nw",
                pady=4,
            )

            row_index += 1

        actions = ttk.Frame(
            root
        )
        actions.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(10, 0),
        )

        ttk.Button(
            actions,
            text="Close",
            command=self.destroy,
        ).pack(
            side="right",
        )

        if self.editable:
            ttk.Button(
                actions,
                text="Edit Clinical Assessment",
                command=self._edit,
            ).pack(
                side="right",
                padx=(0, 8),
            )
        else:
            ttk.Label(
                actions,
                text=(
                    "Historical assessments are review-only. "
                    "Only the latest assessment can be edited."
                ),
            ).pack(
                side="left",
            )

    def _edit(self):
        self.destroy()
        self.on_edit(
            self.record
        )
