"""Bulk Surgical metadata import for the Metadata Dashboard."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from MetadataPipeline.forms.clinical_assessment import (
    reconcile_clinical_assessment,
)
from MetadataPipeline.ingestion.file_loader import (
    MetadataFileError,
    load_metadata_file,
)
from MetadataPipeline.ingestion.record_normalizer import (
    normalize_record,
)
from MetadataPipeline.validation import MetadataValidator
from MetadataPipeline.validation.conditions import (
    condition_matches,
)
from MetadataPipeline.views.import_review import (
    ImportReviewWindow,
)


def _display_value(value):
    if type(value) is list:
        return ", ".join(
            str(item)
            for item in value
        )

    if value in (
        None,
        "",
    ):
        return "(blank)"

    return str(
        value
    )


def _normalized(value):
    if type(value) is list:
        return sorted(
            [
                _normalized(item)
                for item in value
            ],
            key=lambda item: str(item),
        )

    if type(value) is dict:
        return {
            key: _normalized(item)
            for key, item in sorted(
                value.items()
            )
        }

    if type(value) is str:
        return value.strip()

    return value


def _changed_fields(
    current,
    uploaded,
    fields,
):
    changed = []

    for field in fields:
        field_name = field.get(
            "field_name"
        )

        if not field_name:
            continue

        if field_name in {
            "CoCANoT Patient ID",
            "Surgery ID",
            "Clinical Assessment ID",
        }:
            continue

        if _normalized(
            current.get(
                field_name
            )
        ) != _normalized(
            uploaded.get(
                field_name
            )
        ):
            changed.append(
                field_name
            )

    return changed


def _selected_duplicate_errors(
    records,
):
    errors = []
    seen = set()

    for record in records:
        patient_id = str(
            record.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()
        surgery_id = str(
            record.get(
                "Surgery ID"
            )
            or ""
        ).strip()

        key = (
            patient_id,
            surgery_id,
        )

        if key in seen:
            errors.append(
                f"Surgery ID {surgery_id} appears more than once "
                f"for Patient {patient_id} in the selected rows."
            )
            continue

        seen.add(
            key
        )

    return errors


def _existing_conflicts(
    repository,
    site_id,
    records,
    fields,
):
    conflicts = []
    resolutions = {}
    for record in records:
        patient_id = str(
            record.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()
        surgery_id = str(
            record.get(
                "Surgery ID"
            )
            or ""
        ).strip()

        existing = repository.get_record(
            site_id,
            "Surgical",
            surgery_id,
            patient_id=patient_id,
        )

        if existing is None:
            continue

        uploaded = record
        current = dict(
            existing[
                "metadata"
            ]
        )
        changed = _changed_fields(
            current,
            uploaded,
            fields,
        )

        key = (
            patient_id,
            surgery_id,
        )

        if not changed:
            resolutions[
                key
            ] = "keep"
            continue

        conflicts.append({
            "patient_id": patient_id,
            "surgery_id": surgery_id,
            "existing": existing,
            "uploaded": uploaded,
            "changed_fields": changed,
        })

    return (
        conflicts,
        resolutions,
    )


class SurgicalConflictComparisonDialog(
    tk.Toplevel
):
    """Compare stored and uploaded Surgical records side by side."""

    def __init__(
        self,
        parent,
        conflicts,
        fields,
    ):
        super().__init__(
            parent
        )
        self.conflicts = conflicts
        self.fields = fields
        self.decisions = {}
        self.result = None
        self.selected_index = None
        self.upload_variables = {}
        self.field_frames = {}
        self._updating_conditions = False

        self.title(
            "Resolve Existing Surgical Records"
        )
        self.geometry(
            "1220x800"
        )
        self.minsize(
            1000,
            660,
        )
        self.transient(
            parent
        )
        self.grab_set()

        self._build_interface()
        self._refresh_table()

        if self.conflicts:
            self.table.selection_set(
                "0"
            )
            self._select_conflict(
                0
            )

    def _build_interface(
        self,
    ):
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
        )

        ttk.Label(
            root,
            text="Resolve Existing Surgical Records",
            font=("", 17, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            root,
            text=(
                "The current stored Surgical record is shown on the left "
                "and the uploaded version is shown on the right. Fields "
                "appear in Surgical dictionary order. You may edit the "
                "uploaded values before deciding which version to keep."
            ),
            wraplength=1120,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(5, 10),
        )

        body = ttk.Panedwindow(
            root,
            orient=tk.VERTICAL,
        )
        body.grid(
            row=2,
            column=0,
            sticky="nsew",
        )

        table_frame = ttk.Frame(
            body
        )
        comparison_frame = ttk.Frame(
            body
        )

        body.add(
            table_frame,
            weight=1,
        )
        body.add(
            comparison_frame,
            weight=3,
        )

        self._build_conflict_table(
            table_frame
        )
        self._build_comparison_area(
            comparison_frame
        )

        actions = ttk.Frame(
            root
        )
        actions.grid(
            row=3,
            column=0,
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

        self.confirm_button = ttk.Button(
            actions,
            text="Continue",
            command=self._confirm,
            state="disabled",
        )
        self.confirm_button.pack(
            side="right",
            padx=(0, 8),
        )

    def _build_conflict_table(
        self,
        parent,
    ):
        parent.columnconfigure(
            0,
            weight=1,
        )
        parent.rowconfigure(
            0,
            weight=1,
        )

        columns = (
            "patient",
            "surgery",
            "differences",
            "decision",
        )

        self.table = ttk.Treeview(
            parent,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.table.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        headings = {
            "patient": "Patient",
            "surgery": "Surgery ID",
            "differences": "Changed Fields",
            "decision": "Decision",
        }
        widths = {
            "patient": 130,
            "surgery": 170,
            "differences": 520,
            "decision": 190,
        }

        for column in columns:
            self.table.heading(
                column,
                text=headings[
                    column
                ],
            )
            self.table.column(
                column,
                width=widths[
                    column
                ],
                anchor="w",
            )

        scrollbar = ttk.Scrollbar(
            parent,
            orient="vertical",
            command=self.table.yview,
        )
        scrollbar.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        self.table.configure(
            yscrollcommand=scrollbar.set,
        )

        self.table.bind(
            "<<TreeviewSelect>>",
            self._selection_changed,
        )

    def _build_comparison_area(
        self,
        parent,
    ):
        parent.columnconfigure(
            0,
            weight=1,
        )
        parent.rowconfigure(
            1,
            weight=1,
        )

        self.detail_title = ttk.Label(
            parent,
            text="Select a conflict to compare",
            font=("", 12, "bold"),
        )
        self.detail_title.grid(
            row=0,
            column=0,
            sticky="w",
            pady=(10, 5),
        )

        shell = ttk.Frame(
            parent
        )
        shell.grid(
            row=1,
            column=0,
            sticky="nsew",
        )
        shell.columnconfigure(
            0,
            weight=1,
        )
        shell.rowconfigure(
            0,
            weight=1,
        )

        self.canvas = tk.Canvas(
            shell,
            highlightthickness=0,
        )
        self.canvas.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        scrollbar = ttk.Scrollbar(
            shell,
            orient="vertical",
            command=self.canvas.yview,
        )
        scrollbar.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        self.canvas.configure(
            yscrollcommand=scrollbar.set,
        )

        self.comparison_body = ttk.Frame(
            self.canvas,
            padding=(4, 4, 10, 10),
        )
        self.comparison_window = (
            self.canvas.create_window(
                (0, 0),
                window=self.comparison_body,
                anchor="nw",
            )
        )

        self.comparison_body.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(
                scrollregion=self.canvas.bbox(
                    "all"
                )
            ),
        )
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(
                self.comparison_window,
                width=event.width,
            ),
        )

        choice_bar = ttk.Frame(
            parent
        )
        choice_bar.grid(
            row=2,
            column=0,
            sticky="ew",
            pady=(8, 0),
        )

        ttk.Button(
            choice_bar,
            text="Keep Existing",
            command=lambda: self._set_decision(
                "keep"
            ),
        ).pack(
            side="left",
        )

        ttk.Button(
            choice_bar,
            text="Use Uploaded Version",
            command=lambda: self._set_decision(
                "replace"
            ),
        ).pack(
            side="left",
            padx=(8, 0),
        )

    def _refresh_table(
        self,
    ):
        current = self.table.selection()

        for item in self.table.get_children():
            self.table.delete(
                item
            )

        for index, conflict in enumerate(
            self.conflicts
        ):
            key = (
                conflict[
                    "patient_id"
                ],
                conflict[
                    "surgery_id"
                ],
            )
            decision = self.decisions.get(
                key,
                "Choose",
            )

            if decision == "keep":
                shown = "Keep Existing"
            elif decision == "replace":
                shown = "Use Uploaded"
            else:
                shown = "Choose"

            self.table.insert(
                "",
                "end",
                iid=str(
                    index
                ),
                values=(
                    conflict[
                        "patient_id"
                    ],
                    conflict[
                        "surgery_id"
                    ],
                    ", ".join(
                        conflict[
                            "changed_fields"
                        ]
                    ),
                    shown,
                ),
            )

        if current:
            item = current[
                0
            ]

            if self.table.exists(
                item
            ):
                self.table.selection_set(
                    item
                )

        complete = (
            len(
                self.decisions
            )
            == len(
                self.conflicts
            )
        )

        self.confirm_button.configure(
            state=(
                "normal"
                if complete
                else "disabled"
            )
        )

    def _selection_changed(
        self,
        _event=None,
    ):
        selected = self.table.selection()

        if not selected:
            return

        self._save_uploaded_values()
        self._select_conflict(
            int(
                selected[
                    0
                ]
            )
        )

    def _select_conflict(
        self,
        index,
    ):
        self.selected_index = index
        self._build_field_comparison()

    def _build_field_comparison(
        self,
    ):
        for child in self.comparison_body.winfo_children():
            child.destroy()

        self.upload_variables = {}
        self.field_frames = {}

        if self.selected_index is None:
            return

        conflict = self.conflicts[
            self.selected_index
        ]
        existing = conflict[
            "existing"
        ][
            "metadata"
        ]
        uploaded = conflict[
            "uploaded"
        ]

        self.detail_title.configure(
            text=(
                f"Patient {conflict['patient_id']} / "
                f"Surgery {conflict['surgery_id']}"
            )
        )

        self.comparison_body.columnconfigure(
            0,
            weight=0,
        )
        self.comparison_body.columnconfigure(
            1,
            weight=1,
        )
        self.comparison_body.columnconfigure(
            2,
            weight=1,
        )

        ttk.Label(
            self.comparison_body,
            text="Field",
            font=("", 11, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=(0, 8),
        )

        ttk.Label(
            self.comparison_body,
            text="Current Version",
            font=("", 11, "bold"),
        ).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(0, 12),
            pady=(0, 8),
        )

        ttk.Label(
            self.comparison_body,
            text="Uploaded Version",
            font=("", 11, "bold"),
        ).grid(
            row=0,
            column=2,
            sticky="w",
            pady=(0, 8),
        )

        row_index = 1

        for field in self.fields:
            field_name = field.get(
                "field_name"
            )

            if not field_name:
                continue

            row_frame = ttk.Frame(
                self.comparison_body
            )
            row_frame.grid(
                row=row_index,
                column=0,
                columnspan=3,
                sticky="ew",
                pady=2,
            )
            row_frame.columnconfigure(
                0,
                weight=0,
            )
            row_frame.columnconfigure(
                1,
                weight=1,
            )
            row_frame.columnconfigure(
                2,
                weight=1,
            )

            self.field_frames[
                field_name
            ] = (
                row_frame,
                field,
            )

            ttk.Label(
                row_frame,
                text=field_name,
                wraplength=260,
            ).grid(
                row=0,
                column=0,
                sticky="nw",
                padx=(0, 12),
                pady=5,
            )

            ttk.Label(
                row_frame,
                text=_display_value(
                    existing.get(
                        field_name
                    )
                ),
                wraplength=360,
            ).grid(
                row=0,
                column=1,
                sticky="nw",
                padx=(0, 12),
                pady=5,
            )

            self._add_uploaded_editor(
                row_frame,
                field,
                uploaded,
            )

            row_index += 1

        self._refresh_conditions()

    def _add_uploaded_editor(
        self,
        parent,
        field,
        uploaded,
    ):
        field_name = field[
            "field_name"
        ]
        input_type = field.get(
            "input_type"
        ) or "free_text"
        value = uploaded.get(
            field_name
        )

        if field_name in {
            "CoCANoT Patient ID",
            "Surgery ID",
            "Clinical Assessment ID",
        }:
            ttk.Label(
                parent,
                text=_display_value(
                    value
                ),
                wraplength=360,
            ).grid(
                row=0,
                column=2,
                sticky="nw",
                pady=5,
            )
            return

        if input_type == "single_select":
            variable = tk.StringVar(
                value=(
                    ""
                    if value is None
                    else str(
                        value
                    )
                )
            )
            widget = ttk.Combobox(
                parent,
                textvariable=variable,
                values=tuple(
                    field.get(
                        "allowed_values",
                        [],
                    )
                ),
                state="readonly",
            )
            widget.grid(
                row=0,
                column=2,
                sticky="ew",
                pady=5,
            )
            variable.trace_add(
                "write",
                lambda *_args: self._field_changed(),
            )
            self.upload_variables[
                field_name
            ] = (
                "single",
                variable,
            )
            return

        if input_type == "multi_select":
            if type(value) is str:
                selected = [
                    item.strip()
                    for item in value.split(
                        ";"
                    )
                    if item.strip()
                ]
            elif type(value) is list:
                selected = list(
                    value
                )
            else:
                selected = []

            container = ttk.Frame(
                parent
            )
            container.grid(
                row=0,
                column=2,
                sticky="ew",
                pady=5,
            )

            variables = {}

            for option in field.get(
                "allowed_values",
                [],
            ):
                variable = tk.BooleanVar(
                    value=option in selected,
                )
                variables[
                    option
                ] = variable

                ttk.Checkbutton(
                    container,
                    text=option,
                    variable=variable,
                    command=self._field_changed,
                ).pack(
                    anchor="w",
                )

            self.upload_variables[
                field_name
            ] = (
                "multi",
                variables,
            )
            return

        variable = tk.StringVar(
            value=(
                ""
                if value is None
                else str(
                    value
                )
            )
        )
        widget = ttk.Entry(
            parent,
            textvariable=variable,
        )
        widget.grid(
            row=0,
            column=2,
            sticky="ew",
            pady=5,
        )
        variable.trace_add(
            "write",
            lambda *_args: self._field_changed(),
        )
        self.upload_variables[
            field_name
        ] = (
            "text",
            variable,
        )

    def _field_changed(
        self,
    ):
        if self._updating_conditions:
            return

        self._save_uploaded_values()
        self._refresh_conditions()

    def _save_uploaded_values(
        self,
    ):
        if self.selected_index is None:
            return

        uploaded = self.conflicts[
            self.selected_index
        ][
            "uploaded"
        ]

        for field_name, item in self.upload_variables.items():
            kind = item[
                0
            ]
            variable = item[
                1
            ]

            if kind == "multi":
                uploaded[
                    field_name
                ] = [
                    option
                    for option, choice in variable.items()
                    if choice.get()
                ]
            else:
                uploaded[
                    field_name
                ] = variable.get().strip()

    def _refresh_conditions(
        self,
    ):
        if self.selected_index is None:
            return

        uploaded = self.conflicts[
            self.selected_index
        ][
            "uploaded"
        ]

        self._updating_conditions = True

        try:
            for field_name, item in self.field_frames.items():
                frame = item[
                    0
                ]
                field = item[
                    1
                ]
                parent_field = field.get(
                    "required_if_field"
                )

                if not parent_field:
                    frame.grid()
                    continue

                applies = condition_matches(
                    uploaded,
                    parent_field,
                    field.get(
                        "required_if_operator"
                    ),
                    field.get(
                        "required_if_value"
                    ),
                )

                if applies:
                    frame.grid()
                else:
                    frame.grid_remove()
        finally:
            self._updating_conditions = False

    def _set_decision(
        self,
        decision,
    ):
        selected = self.table.selection()

        if not selected:
            return

        self._save_uploaded_values()

        conflict = self.conflicts[
            int(
                selected[
                    0
                ]
            )
        ]
        key = (
            conflict[
                "patient_id"
            ],
            conflict[
                "surgery_id"
            ],
        )
        self.decisions[
            key
        ] = decision

        conflict[
            "changed_fields"
        ] = _changed_fields(
            conflict[
                "existing"
            ][
                "metadata"
            ],
            conflict[
                "uploaded"
            ],
            self.fields,
        )

        self._refresh_table()

    def _confirm(
        self,
    ):
        self._save_uploaded_values()

        if len(
            self.decisions
        ) != len(
            self.conflicts
        ):
            return

        self.result = dict(
            self.decisions
        )
        self.destroy()


class SurgicalUploadReviewDialog(
    tk.Toplevel
):
    """Final preview of Surgical import actions."""

    def __init__(
        self,
        parent,
        rows,
    ):
        super().__init__(
            parent
        )
        self.rows = rows
        self.result = False

        self.title(
            "Review Surgical Metadata Upload"
        )
        self.geometry(
            "1000x620"
        )
        self.minsize(
            820,
            520,
        )
        self.transient(
            parent
        )
        self.grab_set()

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
        )

        ttk.Label(
            root,
            text="Review Surgical Metadata Upload",
            font=("", 17, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            root,
            text=(
                "Nothing has been saved yet. Review the final action "
                "for every selected Surgical record."
            ),
            wraplength=920,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(5, 10),
        )

        columns = (
            "patient",
            "surgery",
            "action",
        )

        tree = ttk.Treeview(
            root,
            columns=columns,
            show="headings",
        )
        tree.grid(
            row=2,
            column=0,
            sticky="nsew",
        )
        tree.heading(
            "patient",
            text="Patient",
        )
        tree.heading(
            "surgery",
            text="Surgery ID",
        )
        tree.heading(
            "action",
            text="Final Action",
        )
        tree.column(
            "patient",
            width=160,
        )
        tree.column(
            "surgery",
            width=180,
        )
        tree.column(
            "action",
            width=540,
        )

        for row in rows:
            resolution = row.get(
                "resolution",
                "new",
            )

            if resolution == "keep":
                action = "Keep existing stored record"
            elif resolution == "replace":
                action = "Replace existing record with uploaded version"
            else:
                action = "Import new Surgical record"

            tree.insert(
                "",
                "end",
                values=(
                    row[
                        "patient_id"
                    ],
                    row[
                        "surgery_id"
                    ],
                    action,
                ),
            )

        actions = ttk.Frame(
            root
        )
        actions.grid(
            row=3,
            column=0,
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
            text="Confirm Import",
            command=self._confirm,
        ).pack(
            side="right",
            padx=(0, 8),
        )

    def _confirm(
        self,
    ):
        self.result = True
        self.destroy()


def import_surgical_file(
    parent,
    dictionary,
    repository,
    metadata_store,
    site_id,
    expected_patient_id,
):
    expected_patient_id = str(
        expected_patient_id
        or ""
    ).strip()

    if not expected_patient_id:
        messagebox.showwarning(
            "Patient Required",
            (
                "Select a CoCANoT Patient ID before "
                "uploading Surgical metadata."
            ),
            parent=parent,
        )
        return None

    path = filedialog.askopenfilename(
        parent=parent,
        title="Select Surgical metadata file",
        filetypes=(
            ("Metadata files", "*.csv *.xlsx"),
            ("CSV files", "*.csv"),
            ("Excel files", "*.xlsx"),
        ),
    )

    if not path:
        return None

    try:
        loaded = load_metadata_file(
            path
        )
    except MetadataFileError as exc:
        messagebox.showerror(
            "Could not load Surgical metadata",
            str(exc),
            parent=parent,
        )
        return None

    if not loaded["rows"]:
        messagebox.showinfo(
            "No Surgical records found",
            "The selected file does not contain any data rows.",
            parent=parent,
        )
        return None

    validator = MetadataValidator(
        dictionary
    )

    records = [
        normalize_record(
            dictionary,
            "Surgical",
            uploaded,
        )
        for uploaded in loaded["rows"]
    ]

    uploaded_patient_ids = sorted({
        str(
            record.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()
        for record in records
        if str(
            record.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()
        and str(
            record.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip() != expected_patient_id
    })

    if uploaded_patient_ids:
        shown = ", ".join(
            uploaded_patient_ids
        )

        confirmed = messagebox.askyesno(
            "Patient ID Does Not Match",
            (
                "The uploaded Surgical metadata contains "
                f"CoCANoT Patient ID(s) {shown}, but you are "
                f"currently reviewing Patient {expected_patient_id}.\n\n"
                "If you continue, every selected Surgical record "
                f"will be assigned to Patient {expected_patient_id}. "
                "The uploaded Patient ID will not be used."
            ),
            parent=parent,
        )

        if not confirmed:
            return None

    for record in records:
        record[
            "CoCANoT Patient ID"
        ] = expected_patient_id

    fields = dictionary[
        "tables"
    ][
        "Surgical"
    ][
        "fields"
    ]

    while True:
        reviewed = {
            "records": None
        }

        def validate_for_review(
            record,
        ):
            return _validation_errors(
                validator,
                record,
            )

        def review_finished(
            final_records,
        ):
            final_records = [
                dict(
                    record
                )
                for record in final_records
            ]

            for record in final_records:
                record[
                    "CoCANoT Patient ID"
                ] = expected_patient_id

            duplicate_errors = (
                _selected_duplicate_errors(
                    final_records
                )
            )

            if duplicate_errors:
                messagebox.showerror(
                    "Duplicate Surgical IDs",
                    (
                        "The selected upload contains duplicate "
                        "Surgery IDs for the Patient Explorer patient. "
                        "Each Surgical record must have a unique "
                        "Surgery ID:\n\n"
                        + "\n".join(
                            duplicate_errors[:20]
                        )
                    ),
                    parent=parent,
                )
                return False

            reviewed[
                "records"
            ] = final_records
            return True

        review = ImportReviewWindow(
            parent=parent,
            table_name="Surgical",
            records=records,
            fields=fields,
            validate_record=validate_for_review,
            on_import=review_finished,
            preferred_patient_id=expected_patient_id,
        )

        parent.wait_window(
            review
        )

        reviewed_records = reviewed[
            "records"
        ]

        if reviewed_records is None:
            return None

        records = reviewed_records

        (
            conflicts,
            resolutions,
        ) = _existing_conflicts(
            repository,
            site_id,
            records,
            fields,
        )

        if conflicts:
            comparison = SurgicalConflictComparisonDialog(
                parent,
                conflicts,
                fields,
            )
            parent.wait_window(
                comparison
            )

            if comparison.result is None:
                return None

            resolutions.update(
                comparison.result
            )

        prepared = []

        for record in records:
            patient_id = str(
                record.get(
                    "CoCANoT Patient ID"
                )
                or ""
            ).strip()
            surgery_id = str(
                record.get(
                    "Surgery ID"
                )
                or ""
            ).strip()
            key = (
                patient_id,
                surgery_id,
            )

            prepared.append({
                "patient_id": patient_id,
                "surgery_id": surgery_id,
                "metadata": record,
                "resolution": resolutions.get(
                    key,
                    "new",
                ),
            })

        if not prepared:
            return None

        assessment_id = reconcile_clinical_assessment(
            parent,
            dictionary,
            metadata_store,
            site_id,
            expected_patient_id,
            return_to="Surgical Metadata Review",
        )

        if assessment_id == "back":
            continue

        if assessment_id is None:
            return None

        break

    repository.create_patient(
        site_id,
        expected_patient_id,
    )

    final_errors = []

    for item in prepared:
        if item[
            "resolution"
        ] == "keep":
            continue

        record = item[
            "metadata"
        ]
        record[
            "Clinical Assessment ID"
        ] = assessment_id

        validation = validator.validate_record(
            "Surgical",
            record,
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

        if not problems:
            continue

        details = "; ".join(
            (
                f"{problem['field_name']}: "
                f"{problem['message']}"
            )
            for problem in problems[:5]
        )

        final_errors.append(
            (
                f"Patient {item['patient_id']}, "
                f"Surgery {item['surgery_id']}: "
                f"{details}"
            )
        )

    if final_errors:
        messagebox.showerror(
            "Surgical metadata needs attention",
            "\n".join(
                final_errors[:20]
            ),
            parent=parent,
        )
        return None

    final_review = SurgicalUploadReviewDialog(
        parent,
        prepared,
    )
    parent.wait_window(
        final_review
    )

    if not final_review.result:
        return None

    updated = 0
    imported = 0

    for item in prepared:
        resolution = item[
            "resolution"
        ]

        if resolution == "keep":
            continue

        repository.save_record(
            site_id,
            "Surgical",
            item[
                "metadata"
            ],
            source="surgical_upload",
        )

        imported += 1

        if resolution == "replace":
            updated += 1

    return {
        "imported": imported,
        "updated": updated,
        "patient_ids": [
            expected_patient_id
        ],
    }


def _validation_errors(
    validator,
    record,
):
    """Return review-window errors for one Surgical record."""

    draft = dict(
        record
    )
    draft[
        "Clinical Assessment ID"
    ] = "PENDING"

    validation = validator.validate_record(
        "Surgical",
        draft,
    )

    errors = {}

    for result in validation[
        "results"
    ]:
        if result[
            "status"
        ] not in {
            "invalid",
            "missing_required",
        }:
            continue

        field_name = result[
            "field_name"
        ]

        if field_name == "Clinical Assessment ID":
            continue

        errors[
            field_name
        ] = result[
            "message"
        ]

    patient_id = str(
        record.get(
            "CoCANoT Patient ID"
        )
        or ""
    ).strip()

    if not patient_id:
        errors[
            "CoCANoT Patient ID"
        ] = "A value is required for this field."

    return errors
