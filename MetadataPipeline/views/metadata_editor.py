"""Dictionary-driven metadata review and edit window."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from MetadataPipeline.forms.form_helpers import (
    field_is_visible,
)
from MetadataPipeline.validation import (
    MetadataValidator,
)


class MetadataEditor(tk.Toplevel):
    """Review or edit one Surgical, Imaging, or Ephys record."""

    def __init__(
        self,
        parent,
        dictionary,
        repository,
        site_id,
        table_name,
        record=None,
        patient_id="",
        on_saved=None,
    ):
        super().__init__(
            parent
        )
        self.dictionary = dictionary
        self.repository = repository
        self.site_id = site_id
        self.table_name = table_name
        self.record = record
        self.on_saved = on_saved
        self.validator = MetadataValidator(
            dictionary
        )

        self.rules = dictionary[
            "tables"
        ][table_name]["fields"]
        self.controls = {}
        self.initial_metadata = dict(
            (
                record.get(
                    "metadata",
                    {},
                )
                if record
                else {}
            )
        )

        if (
            patient_id
            and not self.initial_metadata.get(
                "CoCANoT Patient ID"
            )
        ):
            self.initial_metadata[
                "CoCANoT Patient ID"
            ] = patient_id

        patient_value = str(
            self.initial_metadata.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()

        if (
            patient_value
            and not self.initial_metadata.get(
                "Clinical Assessment ID"
            )
        ):
            assessments = (
                self.repository.clinical_assessments(
                    self.site_id,
                    patient_value,
                )
            )

            if assessments:
                self.initial_metadata[
                    "Clinical Assessment ID"
                ] = assessments[0][
                    "record_id"
                ]

        self.title(
            f"{table_name} Metadata Review"
        )
        self.geometry(
            "1100x850"
        )
        self.minsize(
            850,
            650,
        )
        self.transient(
            parent
        )

        self._build_interface()
        self._load_values()
        self._refresh_conditions()

    def _build_interface(self):
        outer = ttk.Frame(
            self,
            padding=12,
        )
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

        canvas = tk.Canvas(
            outer,
            highlightthickness=0,
        )
        canvas.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        scroll = ttk.Scrollbar(
            outer,
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
        window_id = canvas.create_window(
            (0, 0),
            window=body,
            anchor="nw",
        )
        body.columnconfigure(
            0,
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
                window_id,
                width=event.width,
            ),
        )

        for row_index, rule in enumerate(
            self.rules
        ):
            self._build_field(
                body,
                row_index,
                rule,
            )

        actions = ttk.Frame(
            outer
        )
        actions.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(10, 0),
        )

        ttk.Button(
            actions,
            text="Cancel",
            command=self.destroy,
        ).pack(
            side="right",
        )

        ttk.Button(
            actions,
            text="Validate & Save",
            command=self._save,
        ).pack(
            side="right",
            padx=(0, 8),
        )

    def _build_field(
        self,
        parent,
        row_index,
        rule,
    ):
        field_name = rule[
            "field_name"
        ]
        frame = ttk.Frame(
            parent
        )
        frame.grid(
            row=row_index,
            column=0,
            sticky="ew",
            pady=(4, 4),
        )
        frame.columnconfigure(
            1,
            weight=1,
        )

        required = (
            rule["required"]
            or bool(
                rule.get(
                    "required_if_field"
                )
            )
        )
        marker = (
            " *"
            if required
            else ""
        )

        ttk.Label(
            frame,
            text=str(
                rule["ui_prompt"]
            ) + marker,
            wraplength=390,
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
                command=lambda value=help_text, name=field_name: (
                    messagebox.showinfo(
                        name,
                        value,
                        parent=self,
                    )
                ),
            ).grid(
                row=0,
                column=2,
                sticky="n",
                padx=(6, 0),
            )

        control = {
            "rule": rule,
            "frame": frame,
        }

        if rule[
            "system_generated"
        ]:
            variable = tk.StringVar()
            ttk.Entry(
                frame,
                textvariable=variable,
                state="readonly",
            ).grid(
                row=0,
                column=1,
                sticky="ew",
            )
            control[
                "variable"
            ] = variable
            self.controls[
                field_name
            ] = control
            return

        input_type = rule[
            "input_type"
        ]

        if input_type == "multi_select":
            listbox = tk.Listbox(
                frame,
                selectmode="extended",
                exportselection=False,
                height=min(
                    max(
                        len(
                            rule.get(
                                "allowed_values",
                                [],
                            )
                        ),
                        4,
                    ),
                    7,
                ),
            )
            listbox.grid(
                row=0,
                column=1,
                sticky="ew",
            )

            for value in rule.get(
                "allowed_values",
                [],
            ):
                listbox.insert(
                    "end",
                    value,
                )

            listbox.bind(
                "<<ListboxSelect>>",
                lambda _event: self._refresh_conditions(),
            )
            control[
                "widget"
            ] = listbox

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
                lambda _event: self._refresh_conditions(),
            )
            control[
                "variable"
            ] = variable

        else:
            variable = tk.StringVar()
            ttk.Entry(
                frame,
                textvariable=variable,
            ).grid(
                row=0,
                column=1,
                sticky="ew",
            )
            variable.trace_add(
                "write",
                lambda *_args: self._refresh_conditions(),
            )
            control[
                "variable"
            ] = variable

        self.controls[
            field_name
        ] = control

    def _load_values(self):
        for rule in self.rules:
            field_name = rule[
                "field_name"
            ]
            control = self.controls[
                field_name
            ]
            value = self.initial_metadata.get(
                field_name
            )

            if rule[
                "input_type"
            ] == "multi_select":
                selected_values = (
                    value
                    if type(value) is list
                    else []
                )
                widget = control[
                    "widget"
                ]

                for index in range(
                    widget.size()
                ):
                    if widget.get(
                        index
                    ) in selected_values:
                        widget.selection_set(
                            index
                        )

                continue

            control[
                "variable"
            ].set(
                ""
                if value is None
                else str(
                    value
                )
            )

    def _answers(self):
        answers = {}

        for rule in self.rules:
            field_name = rule[
                "field_name"
            ]
            control = self.controls[
                field_name
            ]

            if rule[
                "input_type"
            ] == "multi_select":
                widget = control[
                    "widget"
                ]
                answers[
                    field_name
                ] = [
                    widget.get(
                        index
                    )
                    for index in widget.curselection()
                ]
                continue

            answers[
                field_name
            ] = control[
                "variable"
            ].get().strip()

        return answers

    def _refresh_conditions(self):
        answers = self._answers()

        for field_name, control in self.controls.items():
            rule = control[
                "rule"
            ]
            frame = control[
                "frame"
            ]

            if field_is_visible(
                rule,
                answers,
            ):
                frame.grid()
                continue

            self._clear_control(
                control
            )
            frame.grid_remove()

    @staticmethod
    def _clear_control(control):
        rule = control[
            "rule"
        ]

        if rule[
            "input_type"
        ] == "multi_select":
            widget = control[
                "widget"
            ]

            if widget.curselection():
                widget.selection_clear(
                    0,
                    "end",
                )
            return

        variable = control.get(
            "variable"
        )

        if (
            variable is not None
            and variable.get()
            and not rule[
                "system_generated"
            ]
        ):
            variable.set(
                ""
            )

    def _save(self):
        metadata = self._answers()

        validation = self.validator.validate_record(
            self.table_name,
            metadata,
        )

        problems = [
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

        if problems:
            messagebox.showerror(
                "Metadata validation failed",
                "\n".join(
                    f"{item['field_name']}: {item['message']}"
                    for item in problems[:15]
                ),
                parent=self,
            )
            return

        try:
            saved = self.repository.save_record(
                self.site_id,
                self.table_name,
                metadata,
            )
        except ValueError as exc:
            messagebox.showerror(
                "Could not save metadata",
                str(
                    exc
                ),
                parent=self,
            )
            return

        if self.on_saved is not None:
            self.on_saved(
                saved
            )

        self.destroy()
