"""Editable review window for uploaded CoCANoT metadata."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from MetadataPipeline.validation.conditions import (
    condition_matches,
)


class ImportReviewWindow(tk.Toplevel):
    """Review and correct uploaded metadata before it is imported."""

    RECORD_ID_FIELDS = {
        "Clinical": "Clinical Assessment ID",
        "Surgical": "Surgery ID",
        "Imaging": "Image ID",
        "Electrophysiology": "Recording ID",
    }

    def __init__(
        self,
        parent,
        table_name,
        records,
        fields,
        validate_record,
        on_import,
        preferred_patient_id=None,
        preferred_patient_ids=None,
        duplicate_checker=None,
        status_getter=None,
        import_button_text="Import Validated Records",
    ):
        super().__init__(parent)

        self.table_name = table_name
        self.fields = fields
        self.validate_record = validate_record
        self.on_import = on_import
        self.duplicate_checker = duplicate_checker
        self.status_getter = status_getter
        self.import_button_text = import_button_text
        self.preferred_patient_ids = {
            str(patient_id).strip()
            for patient_id in (
                preferred_patient_ids
                or []
            )
            if str(patient_id).strip()
        }

        preferred_patient_id = str(
            preferred_patient_id
            or ""
        ).strip()

        if preferred_patient_id:
            self.preferred_patient_ids.add(
                preferred_patient_id
            )

        self.records = []

        for row_number, record in enumerate(
            records,
            start=2,
        ):
            data = dict(record)
            duplicate = self._is_duplicate(
                data
            )

            self.records.append({
                "row_number": row_number,
                "data": data,
                "errors": {},
                "duplicate": duplicate,
                "include": (
                    self._include_by_default(
                        data
                    )
                    and not duplicate
                ),
            })

        self.selected_index = None
        self.variables = {}
        self.field_frames = {}
        self.error_labels = {}
        self._updating_conditions = False

        self.title(f"Review {table_name} Metadata")
        self.geometry("1100x780")
        self.minsize(900, 650)
        self.transient(parent)
        self.grab_set()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()
        self._build_footer()

        self._validate_all()
        self._refresh_table()

        if self.records:
            self.after(50, lambda: self._select_row(0))

    def _build_header(self):
        header = ttk.Frame(
            self,
            padding=(14, 14, 14, 8),
        )
        header.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text=f"Review Uploaded {self.table_name} Metadata",
            font=("", 15, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        self.summary_label = ttk.Label(
            header,
            text="",
        )
        self.summary_label.grid(
            row=1,
            column=0,
            sticky="w",
            pady=(5, 0),
        )

    def _build_body(self):
        body = ttk.Panedwindow(
            self,
            orient=tk.VERTICAL,
        )
        body.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=14,
            pady=(0, 8),
        )

        table_section = ttk.Frame(body)
        editor_section = ttk.Frame(body)

        body.add(table_section, weight=1)
        body.add(editor_section, weight=2)

        self._build_table(table_section)
        self._build_editor(editor_section)

    def _build_table(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        columns = (
            "include",
            "row",
            "patient",
            "record",
            "status",
            "problems",
        )

        self.table = ttk.Treeview(
            parent,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        self.table.heading("include", text="Include")
        self.table.heading("row", text="Spreadsheet Row")
        self.table.heading("patient", text="Patient")
        self.table.heading("record", text="Record ID")
        self.table.heading("status", text="Status")
        self.table.heading("problems", text="Problems")

        self.table.column("include", width=70, anchor="center", stretch=False)
        self.table.column("row", width=110, anchor="center", stretch=False)
        self.table.column("patient", width=120, stretch=False)
        self.table.column("record", width=140, stretch=False)
        self.table.column("status", width=90, anchor="center", stretch=False)
        self.table.column("problems", width=450)

        scrollbar = ttk.Scrollbar(
            parent,
            orient="vertical",
            command=self.table.yview,
        )

        self.table.configure(
            yscrollcommand=scrollbar.set,
        )

        self.table.grid(
            row=0,
            column=0,
            sticky="nsew",
        )
        scrollbar.grid(
            row=0,
            column=1,
            sticky="ns",
        )

        self.table.bind(
            "<<TreeviewSelect>>",
            self._table_selection_changed,
        )
        self.table.bind(
            "<Double-1>",
            self._toggle_include,
        )

    def _build_editor(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        self.record_label = ttk.Label(
            parent,
            text="Selected Record",
            font=("", 12, "bold"),
        )
        self.record_label.grid(
            row=0,
            column=0,
            sticky="w",
            pady=(10, 5),
        )

        canvas_frame = ttk.Frame(parent)
        canvas_frame.grid(
            row=1,
            column=0,
            sticky="nsew",
        )
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            canvas_frame,
            highlightthickness=0,
        )

        scrollbar = ttk.Scrollbar(
            canvas_frame,
            orient="vertical",
            command=self.canvas.yview,
        )

        self.canvas.configure(
            yscrollcommand=scrollbar.set,
        )

        self.canvas.grid(
            row=0,
            column=0,
            sticky="nsew",
        )
        scrollbar.grid(
            row=0,
            column=1,
            sticky="ns",
        )

        self.editor_frame = ttk.Frame(
            self.canvas,
            padding=(6, 6, 12, 12),
        )

        self.editor_window = self.canvas.create_window(
            (0, 0),
            window=self.editor_frame,
            anchor="nw",
        )

        self.editor_frame.bind(
            "<Configure>",
            self._update_scroll_region,
        )
        self.canvas.bind(
            "<Configure>",
            self._resize_editor,
        )
        self.canvas.bind(
            "<MouseWheel>",
            self._mousewheel,
        )
        self.canvas.bind(
            "<Button-4>",
            self._mousewheel_linux,
        )
        self.canvas.bind(
            "<Button-5>",
            self._mousewheel_linux,
        )

    def _build_footer(self):
        footer = ttk.Frame(
            self,
            padding=(14, 4, 14, 14),
        )
        footer.grid(
            row=2,
            column=0,
            sticky="ew",
        )

        ttk.Button(
            footer,
            text="Revalidate Record",
            command=self._revalidate_selected,
        ).pack(
            side="left",
        )

        ttk.Button(
            footer,
            text="Cancel",
            command=self.destroy,
        ).pack(
            side="right",
        )

        self.import_button = ttk.Button(
            footer,
            text=self.import_button_text,
            command=self._finish_import,
        )
        self.import_button.pack(
            side="right",
            padx=(0, 8),
        )

    def _validate_all(self):
        for record in self.records:
            record["errors"] = self._run_validation(
                record["data"]
            )

    def _run_validation(self, data):
        errors = self.validate_record(data)

        if not errors:
            return {}

        return dict(errors)

    def _revalidate_selected(self):
        if self.selected_index is None:
            return

        self._save_current_editor()
        self._refresh_conditions()

        record = self.records[self.selected_index]
        record["errors"] = self._run_validation(
            record["data"]
        )

        self._refresh_table()
        self._build_record_editor()

        if not record["errors"]:
            messagebox.showinfo(
                "Record Valid",
                "This record now passes validation.",
                parent=self,
            )

    def _refresh_table(self):
        current = self.selected_index

        for item in self.table.get_children():
            self.table.delete(item)

        for index, record in enumerate(self.records):
            data = record["data"]
            errors = record["errors"]

            patient_id = str(
                data.get("CoCANoT Patient ID") or ""
            ).strip()

            record_id = self._get_record_id(data)

            record["duplicate"] = self._is_duplicate(
                data
            )

            if errors:
                status = "Error"
                problems = "; ".join(
                    errors.keys()
                )
            elif record["duplicate"]:
                status = "Duplicate"
                problems = "Existing record"
            elif not record["include"]:
                status = "Excluded"
                problems = ""
            else:
                status, problems = self._custom_status(
                    data
                )

            self.table.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    "Yes" if record["include"] else "No",
                    record["row_number"],
                    patient_id,
                    record_id,
                    status,
                    problems,
                ),
            )

        self._update_summary()

        if current is not None:
            item = str(current)

            if self.table.exists(item):
                self.table.selection_set(item)
                self.table.see(item)

    def _update_summary(self):
        ready = 0
        errors = 0
        duplicates = 0
        review = 0
        excluded = 0

        for record in self.records:
            data = record["data"]
            record["duplicate"] = self._is_duplicate(
                data
            )

            if record["errors"]:
                errors += 1
                continue

            if record["duplicate"]:
                duplicates += 1
                continue

            if not record["include"]:
                excluded += 1
                continue

            status, _problems = self._custom_status(
                data
            )

            if status == "Ready":
                ready += 1
            else:
                review += 1

        pieces = [
            f"{ready} ready",
            f"{errors} need correction",
            f"{duplicates} duplicate"
            f"{'' if duplicates == 1 else 's'}",
        ]

        if review:
            pieces.append(
                f"{review} need review"
            )

        pieces.append(
            f"{excluded} excluded"
        )

        self.summary_label.configure(
            text="   •   ".join(
                pieces
            )
        )

        self.import_button.configure(
            state="disabled" if errors else "normal"
        )

    def _table_selection_changed(
        self,
        _event=None,
    ):
        selection = self.table.selection()

        if not selection:
            return

        index = int(selection[0])

        if index == self.selected_index:
            return

        self._select_row(index)

    def _select_row(self, index):
        self._save_current_editor()

        self.selected_index = index

        self.table.selection_set(str(index))
        self.table.see(str(index))

        self._build_record_editor()

    def _toggle_include(self, event):
        item = self.table.identify_row(event.y)

        if not item:
            return

        index = int(item)
        record = self.records[index]

        record["include"] = not record["include"]

        self._refresh_table()

    def _build_record_editor(self):
        for child in self.editor_frame.winfo_children():
            child.destroy()

        self.variables = {}
        self.field_frames = {}
        self.error_labels = {}

        if self.selected_index is None:
            return

        record = self.records[self.selected_index]
        data = record["data"]
        errors = record["errors"]

        patient_id = str(
            data.get("CoCANoT Patient ID") or ""
        ).strip()

        record_id = self._get_record_id(data)

        title = patient_id

        if record_id:
            title = (
                f"{title} / {record_id}"
                if title
                else record_id
            )

        self.record_label.configure(
            text=(
                f"Selected Record: {title}"
                if title
                else "Selected Record"
            )
        )

        self.editor_frame.columnconfigure(
            0,
            weight=1,
        )

        row = 0

        for field in self.fields:
            field_name = field.get("field_name")

            if not field_name:
                continue

            if self._is_true(
                field.get("system_generated")
            ) and not (
                self.table_name == "Clinical"
                and field_name == "Clinical Assessment ID"
            ):
                continue

            field_frame = ttk.Frame(
                self.editor_frame,
            )
            field_frame.grid(
                row=row,
                column=0,
                sticky="ew",
                pady=(3, 5),
            )
            field_frame.columnconfigure(
                1,
                weight=1,
            )

            self.field_frames[
                field_name
            ] = field_frame

            prompt = (
                field.get("ui_prompt")
                or field_name
            )

            if self._field_required(
                field,
                data,
            ):
                prompt += " *"

            ttk.Label(
                field_frame,
                text=prompt,
                anchor="nw",
                wraplength=300,
            ).grid(
                row=0,
                column=0,
                sticky="nw",
                padx=(0, 12),
                pady=(5, 2),
            )

            input_type = (
                field.get("input_type")
                or "free_text"
            )

            if input_type == "single_select":
                self._add_single_select(
                    field_frame,
                    field,
                    data,
                )
            elif input_type == "multi_select":
                self._add_multi_select(
                    field_frame,
                    field,
                    data,
                )
            else:
                self._add_text_field(
                    field_frame,
                    field,
                    data,
                )

            error_label = ttk.Label(
                field_frame,
                text=errors.get(
                    field_name,
                    "",
                ),
                foreground="red",
                wraplength=550,
            )
            error_label.grid(
                row=1,
                column=1,
                sticky="w",
                pady=(0, 6),
            )

            self.error_labels[
                field_name
            ] = error_label

            row += 1

        self._save_current_editor()
        self._refresh_conditions()

    def _add_text_field(
        self,
        parent,
        field,
        data,
    ):
        field_name = field["field_name"]

        value = data.get(
            field_name,
            "",
        )

        if value is None:
            value = ""

        variable = tk.StringVar(
            value=str(value),
        )

        self.variables[
            field_name
        ] = variable

        entry = ttk.Entry(
            parent,
            textvariable=variable,
        )
        entry.grid(
            row=0,
            column=1,
            sticky="ew",
            pady=(5, 2),
        )

        variable.trace_add(
            "write",
            lambda *_args: self._field_changed(),
        )

    def _add_single_select(
        self,
        parent,
        field,
        data,
    ):
        field_name = field["field_name"]

        value = data.get(
            field_name,
            "",
        )

        if value is None:
            value = ""

        variable = tk.StringVar(
            value=str(value),
        )

        self.variables[
            field_name
        ] = variable

        combo = ttk.Combobox(
            parent,
            textvariable=variable,
            values=self._allowed_values(field),
            state="readonly",
        )
        combo.grid(
            row=0,
            column=1,
            sticky="ew",
            pady=(5, 2),
        )

        variable.trace_add(
            "write",
            lambda *_args: self._field_changed(),
        )

    def _add_multi_select(
        self,
        parent,
        field,
        data,
    ):
        field_name = field["field_name"]

        selected = data.get(
            field_name,
            [],
        )

        if type(selected) is str:
            selected = [
                value.strip()
                for value in selected.split(";")
                if value.strip()
            ]

        if selected is None:
            selected = []

        choices = {}

        container = ttk.Frame(
            parent
        )
        container.grid(
            row=0,
            column=1,
            sticky="ew",
            pady=(5, 2),
        )

        for value in self._allowed_values(field):
            variable = tk.BooleanVar(
                value=value in selected,
            )

            choices[value] = variable

            ttk.Checkbutton(
                container,
                text=value,
                variable=variable,
                command=self._field_changed,
            ).pack(
                anchor="w",
            )

        self.variables[
            field_name
        ] = choices

    def _field_changed(self):
        if self._updating_conditions:
            return

        self._save_current_editor()
        self._refresh_conditions()
        self._revalidate_live()

    def _save_current_editor(self):
        if self.selected_index is None:
            return

        if not self.variables:
            return

        data = self.records[
            self.selected_index
        ]["data"]

        for field_name, variable in self.variables.items():
            if type(variable) is dict:
                data[field_name] = [
                    value
                    for value, choice in variable.items()
                    if choice.get()
                ]
            else:
                data[
                    field_name
                ] = variable.get().strip()

    def _revalidate_live(self):
        """Revalidate the selected record and update errors immediately."""

        if self.selected_index is None:
            return

        record = self.records[
            self.selected_index
        ]

        record["errors"] = self._run_validation(
            record["data"]
        )

        for field_name, label in self.error_labels.items():
            label.configure(
                text=record["errors"].get(
                    field_name,
                    "",
                )
            )

        self._refresh_table()

    def _refresh_conditions(self):
        if self.selected_index is None:
            return

        data = self.records[
            self.selected_index
        ]["data"]

        self._updating_conditions = True

        try:
            changed = True

            while changed:
                changed = False

                for field in self.fields:
                    field_name = field.get(
                        "field_name"
                    )

                    frame = self.field_frames.get(
                        field_name
                    )

                    if frame is None:
                        continue

                    applies = self._field_applies(
                        field,
                        data,
                    )

                    if applies:
                        frame.grid()
                        continue

                    frame.grid_remove()

                    if self._clear_field_value(
                        field_name,
                        data,
                    ):
                        changed = True

        finally:
            self._updating_conditions = False

    def _field_applies(
        self,
        field,
        data,
    ):
        parent_field = field.get(
            "required_if_field"
        )

        if not parent_field:
            return True

        return condition_matches(
            data,
            parent_field,
            field.get(
                "required_if_operator"
            ),
            field.get(
                "required_if_value"
            ),
        )

    def _field_required(
        self,
        field,
        data,
    ):
        if self._is_true(
            field.get("required")
        ):
            return True

        if not field.get(
            "required_if_field"
        ):
            return False

        return self._field_applies(
            field,
            data,
        )

    def _clear_field_value(
        self,
        field_name,
        data,
    ):
        variable = self.variables.get(
            field_name
        )

        if variable is None:
            return False

        changed = False

        if type(variable) is dict:
            for choice in variable.values():
                if choice.get():
                    choice.set(False)
                    changed = True

            if data.get(field_name):
                data[field_name] = []
                changed = True

            return changed

        if variable.get():
            variable.set("")
            changed = True

        if data.get(field_name):
            data[field_name] = ""
            changed = True

        return changed

    def _allowed_values(
        self,
        field,
    ):
        values = field.get(
            "allowed_values",
            [],
        )

        if type(values) is list:
            return values

        return []

    def _is_true(
        self,
        value,
    ):
        if value is True:
            return True

        if value is None:
            return False

        return str(value).strip().lower() in {
            "true",
            "yes",
            "1",
        }

    def _get_record_id(
        self,
        data,
    ):
        field_name = self.RECORD_ID_FIELDS.get(
            self.table_name,
            "",
        )

        if not field_name:
            return ""

        return str(
            data.get(
                field_name,
                ""
            )
            or ""
        ).strip()

    def _is_duplicate(
        self,
        record,
    ):
        if self.duplicate_checker is None:
            return False

        try:
            return bool(
                self.duplicate_checker(
                    record
                )
            )
        except Exception:
            return False

    def _custom_status(
        self,
        record,
    ):
        if self.status_getter is None:
            return (
                "Ready",
                "",
            )

        result = self.status_getter(
            record
        )

        if type(result) is tuple:
            status = str(
                result[0]
                or "Ready"
            ).strip()
            problems = str(
                result[1]
                if len(result) > 1
                else ""
            ).strip()

            return (
                status,
                problems,
            )

        return (
            str(
                result
                or "Ready"
            ).strip(),
            "",
        )

    def _include_by_default(
        self,
        record,
    ):
        if not self.preferred_patient_ids:
            return True

        patient_id = str(
            record.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()

        return (
            patient_id
            in self.preferred_patient_ids
        )

    def _confirm_other_patients(
        self,
        final_records,
    ):
        if not self.preferred_patient_ids:
            return True

        other_patient_ids = sorted({
            str(
                record.get(
                    "CoCANoT Patient ID"
                )
                or ""
            ).strip()
            for record in final_records
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
            ).strip()
            not in self.preferred_patient_ids
        })

        if not other_patient_ids:
            return True

        current_patients = ", ".join(
            sorted(
                self.preferred_patient_ids
            )
        )

        additional_patients = ", ".join(
            other_patient_ids
        )

        if (
            self.table_name in {
                "Clinical",
                "Surgical",
            }
            and len(
                self.preferred_patient_ids
            ) == 1
        ):
            current_patient = next(
                iter(
                    self.preferred_patient_ids
                )
            )

            if self.table_name == "Clinical":
                record_label = "Clinical Assessment"
            else:
                record_label = "Surgical"

            return messagebox.askyesno(
                f"Confirm {record_label} Patient ID",
                (
                    f"The selected {record_label} rows include "
                    f"CoCANoT Patient ID"
                    f"{'s' if len(other_patient_ids) != 1 else ''} "
                    f"{additional_patients}, but Patient "
                    f"{current_patient} is selected in Patient Explorer.\n\n"
                    "If this was intentional, continue and the selected "
                    f"{record_label} rows will be assigned to Patient "
                    f"{current_patient}.\n\n"
                    "Continue?"
                ),
                parent=self,
            )

        return messagebox.askyesno(
            "Confirm Additional Patients",
            (
                "The selected rows include CoCANoT Patient ID"
                f"{'s' if len(other_patient_ids) != 1 else ''} "
                f"{additional_patients}, while the current "
                "submission is for Patient"
                f"{'s' if len(self.preferred_patient_ids) != 1 else ''} "
                f"{current_patients}.\n\n"
                f"Import {self.table_name} metadata for the "
                "selected additional patient"
                f"{'s' if len(other_patient_ids) != 1 else ''}?"
            ),
            parent=self,
        )

    def _finish_import(self):
        self._save_current_editor()
        self._refresh_conditions()

        invalid = []

        for record in self.records:
            if not record["include"]:
                continue

            record["errors"] = self._run_validation(
                record["data"]
            )

            if record["errors"]:
                invalid.append(record)

        if invalid:
            self._refresh_table()

            messagebox.showerror(
                "Metadata Needs Review",
                (
                    f"{len(invalid)} included record"
                    f"{'' if len(invalid) == 1 else 's'} "
                    "still contain validation errors."
                ),
                parent=self,
            )
            return

        final_records = [
            record["data"]
            for record in self.records
            if record["include"]
        ]

        if not final_records:
            messagebox.showwarning(
                "Nothing to Import",
                "No records are selected for import.",
                parent=self,
            )
            return

        if not self._confirm_other_patients(
            final_records
        ):
            return

        result = self.on_import(
            final_records
        )

        if result is False:
            return

        self.destroy()

    def _update_scroll_region(
        self,
        _event=None,
    ):
        self.canvas.configure(
            scrollregion=self.canvas.bbox(
                "all"
            ),
        )

    def _resize_editor(
        self,
        event,
    ):
        self.canvas.itemconfigure(
            self.editor_window,
            width=event.width,
        )

    def _mousewheel(
        self,
        event,
    ):
        if event.delta:
            self.canvas.yview_scroll(
                int(-1 * (event.delta / 120)),
                "units",
            )

    def _mousewheel_linux(
        self,
        event,
    ):
        if event.num == 4:
            self.canvas.yview_scroll(
                -1,
                "units",
            )
        elif event.num == 5:
            self.canvas.yview_scroll(
                1,
                "units",
            )
