"""Site-level batch import for Clinical and Surgical metadata."""

from __future__ import annotations

import re
import tkinter as tk
from collections import defaultdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from MetadataPipeline.ingestion.batch_ingestion import (
    validate_uploaded_metadata,
)
from MetadataPipeline.validation import MetadataValidator
from MetadataPipeline.validation.conditions import condition_matches
from MetadataPipeline.views.import_review import ImportReviewWindow


RECORD_ID_FIELDS = {
    "Clinical": "Clinical Assessment ID",
    "Surgical": "Surgery ID",
}


class MetadataBatchImport(ttk.Frame):
    """Import and validate metadata for one or more participants."""

    def __init__(
        self,
        parent,
        dictionary,
        repository,
        metadata_store,
        site_id_getter,
        on_back,
        table_name,
        on_import_complete=None,
    ):
        super().__init__(parent)

        self.dictionary = dictionary
        self.repository = repository
        self.metadata_store = metadata_store
        self.site_id_getter = site_id_getter
        self.on_back = on_back
        self.table_name = str(table_name or "").strip()

        if self.table_name not in RECORD_ID_FIELDS:
            raise ValueError(
                "MetadataBatchImport table_name must be 'Clinical' or 'Surgical'."
            )

        self.on_import_complete = on_import_complete

        self.loaded = None
        self.records = []
        self.validation_errors = []
        self.file_var = tk.StringVar(
            value="No file selected"
        )
        self.summary_var = tk.StringVar(
            value=f"Select a {self.table_name} CSV/XLSX file to begin."
        )

        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        self._build_header()
        self._build_file_section()
        self._build_summary()
        self._build_patient_table()
        self._build_actions()

    def _build_header(self):
        header = ttk.Frame(self)
        header.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text=f"{self.table_name} Metadata Batch Import",
            font=("", 22, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Button(
            header,
            text="Back to Bulk Upload",
            command=self.on_back,
        ).grid(
            row=0,
            column=1,
            sticky="e",
        )

        ttk.Label(
            self,
            text=(
                f"Import {self.table_name} metadata for one or more participants. "
                f"Validation follows MR {self.table_name} from the active "
                "CoCANoT metadata dictionary."
            ),
            wraplength=950,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(5, 14),
        )

    def _build_file_section(self):
        section = ttk.LabelFrame(
            self,
            text="1. Upload",
            padding=12,
        )
        section.grid(
            row=2,
            column=0,
            sticky="ew",
        )
        section.columnconfigure(1, weight=1)

        ttk.Button(
            section,
            text="Select CSV/XLSX File",
            command=self._select_file,
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            section,
            textvariable=self.file_var,
        ).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(12, 0),
        )

    def _build_summary(self):
        section = ttk.LabelFrame(
            self,
            text="2. Validate",
            padding=12,
        )
        section.grid(
            row=3,
            column=0,
            sticky="ew",
            pady=(12, 0),
        )

        ttk.Label(
            section,
            textvariable=self.summary_var,
            wraplength=950,
        ).pack(
            anchor="w",
        )

    def _build_patient_table(self):
        section = ttk.LabelFrame(
            self,
            text="3. Review Participants",
            padding=12,
        )
        section.grid(
            row=4,
            column=0,
            sticky="nsew",
            pady=(12, 0),
        )
        section.columnconfigure(0, weight=1)
        section.rowconfigure(0, weight=1)

        columns = (
            "patient",
            "records",
            "ready",
            "attention",
            "status",
        )

        self.table = ttk.Treeview(
            section,
            columns=columns,
            show="headings",
        )
        self.table.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        headings = {
            "patient": "Patient",
            "records": "Records",
            "ready": "Ready",
            "attention": "Need Correction",
            "status": "Status",
        }
        widths = {
            "patient": 180,
            "records": 110,
            "ready": 110,
            "attention": 150,
            "status": 180,
        }

        for column in columns:
            self.table.heading(
                column,
                text=headings[column],
            )
            self.table.column(
                column,
                width=widths[column],
                anchor="center" if column != "patient" else "w",
            )

        scrollbar = ttk.Scrollbar(
            section,
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

    def _build_actions(self):
        footer = ttk.Frame(self)
        footer.grid(
            row=5,
            column=0,
            sticky="ew",
            pady=(12, 0),
        )

        self.review_button = ttk.Button(
            footer,
            text="Review Records",
            command=self._review_records,
            state="disabled",
        )
        self.review_button.pack(
            side="right",
        )

    def _select_file(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Select metadata file",
            filetypes=(
                ("Metadata files", "*.csv *.xlsx"),
                ("CSV files", "*.csv"),
                ("Excel files", "*.xlsx"),
            ),
        )

        if not path:
            return

        try:
            loaded = validate_uploaded_metadata(
                self.dictionary,
                path,
            )
        except Exception as exc:
            messagebox.showerror(
                "Could not load metadata",
                str(exc),
                parent=self,
            )
            return

        detected_table = str(loaded.get("table_name") or "").strip()

        if detected_table != self.table_name:
            messagebox.showerror(
                "Wrong metadata type",
                (
                    f"This upload pathway accepts {self.table_name} metadata only. "
                    f"The selected file was detected as "
                    f"{detected_table or 'an unknown metadata type'}."
                ),
                parent=self,
            )
            return

        self.loaded = loaded
        self.records = [
            dict(row["record"])
            for row in loaded["rows"]
        ]
        self.file_var.set(
            Path(path).name
        )

        self._refresh_summary()

    def _refresh_summary(self):
        for item in self.table.get_children():
            self.table.delete(item)

        if not self.loaded:
            self.summary_var.set(
                f"Select a {self.table_name} CSV/XLSX file to begin."
            )
            self.review_button.configure(
                state="disabled"
            )
            return

        table_name = self.loaded["table_name"]
        patient_rows = defaultdict(
            lambda: {
                "records": 0,
                "ready": 0,
                "errors": 0,
            }
        )

        total_ready = 0
        total_errors = 0

        for row in self.loaded["rows"]:
            record = row["record"]
            validation = row["validation"]
            patient_id = str(
                record.get("CoCANoT Patient ID") or ""
            ).strip() or "(blank)"

            errors = self._blocking_validation_errors(
                validation
            )

            patient_rows[patient_id]["records"] += 1

            if errors:
                patient_rows[patient_id]["errors"] += 1
                total_errors += 1
            else:
                patient_rows[patient_id]["ready"] += 1
                total_ready += 1

        for patient_id in sorted(patient_rows):
            counts = patient_rows[patient_id]
            status = (
                "Ready"
                if counts["errors"] == 0
                else "Correction required"
            )

            self.table.insert(
                "",
                "end",
                values=(
                    patient_id,
                    counts["records"],
                    counts["ready"],
                    counts["errors"],
                    status,
                ),
            )

        self.summary_var.set(
            (
                f"{table_name} metadata detected • "
                f"{len(patient_rows)} participant"
                f"{'' if len(patient_rows) == 1 else 's'} • "
                f"{len(self.records)} record"
                f"{'' if len(self.records) == 1 else 's'} • "
                f"{total_ready} ready • "
                f"{total_errors} need correction"
            )
        )

        self.review_button.configure(
            state="normal"
        )

    def _review_records(self):
        if not self.loaded or not self.records:
            return

        table_name = self.loaded["table_name"]
        fields = self.dictionary["tables"][
            table_name
        ]["fields"]
        validator = MetadataValidator(
            self.dictionary
        )

        def validate_record(record):
            validation = validator.validate_record(
                table_name,
                record,
            )

            errors = {}

            for result in validation["results"]:
                if result["status"] not in {
                    "invalid",
                    "missing_required",
                }:
                    continue

                field_name = result["field_name"]

                # Surgical Clinical Assessment linkage is reconciled
                # after the uploaded Surgical metadata itself is reviewed.
                if (
                    table_name == "Surgical"
                    and field_name == "Clinical Assessment ID"
                ):
                    continue

                errors[field_name] = result["message"]

            return errors

        def duplicate_checker(record):
            return self._record_exists(
                table_name,
                record,
            )

        def status_getter(record):
            if table_name != "Surgical":
                return (
                    "Ready",
                    "",
                )

            patient_id = self._patient_id(
                record
            )

            latest = self.metadata_store.latest_clinical_assessment(
                self.site_id_getter(),
                patient_id,
            )

            if latest is None:
                return (
                    "Clinical Assessment Required",
                    "Add or upload Clinical metadata",
                )

            return (
                "Clinical Review Required",
                f"Current: {latest['assessment_id']}",
            )

        reviewed = {
            "records": None
        }

        def review_finished(final_records):
            final_records = [
                dict(record)
                for record in final_records
            ]

            duplicate_errors = self._duplicate_errors(
                table_name,
                final_records,
            )

            if duplicate_errors:
                messagebox.showerror(
                    "Duplicate record IDs",
                    "\n".join(
                        duplicate_errors[:20]
                    ),
                    parent=self,
                )
                return False

            if table_name == "Clinical":
                format_errors = self._clinical_id_errors(
                    final_records
                )

                if format_errors:
                    messagebox.showerror(
                        "Clinical Assessment IDs need attention",
                        "\n".join(
                            format_errors[:20]
                        ),
                        parent=self,
                    )
                    return False

            reviewed["records"] = final_records
            return True

        review = ImportReviewWindow(
            parent=self,
            table_name=table_name,
            records=self.records,
            fields=fields,
            validate_record=validate_record,
            on_import=review_finished,
            duplicate_checker=duplicate_checker,
            status_getter=status_getter,
            import_button_text=(
                "Continue to Clinical Review"
                if table_name == "Surgical"
                else "Import Validated Records"
            ),
        )
        self.wait_window(
            review
        )

        final_records = reviewed["records"]

        if final_records is None:
            return

        if table_name == "Surgical":
            final_records = self._reconcile_surgical_clinical(
                final_records
            )

            if final_records is None:
                return

        manual_lines = self._manual_review_lines(
            table_name,
            final_records,
            validator,
        )

        if manual_lines:
            confirmed = messagebox.askyesno(
                "Review free-text metadata",
                (
                    "Please confirm these free-text values are appropriate "
                    "and do not contain PHI:\n\n"
                    + "\n\n".join(
                        manual_lines[:30]
                    )
                ),
                parent=self,
            )

            if not confirmed:
                return

        if table_name == "Clinical":
            imported = self._import_clinical(
                final_records
            )
        else:
            imported = self._import_surgical(
                final_records
            )

        if imported is None:
            return

        if self.on_import_complete:
            self.on_import_complete()

        messagebox.showinfo(
            "Metadata import complete",
            (
                f"Imported {imported['saved']} record"
                f"{'' if imported['saved'] == 1 else 's'} "
                f"for {imported['patients']} participant"
                f"{'' if imported['patients'] == 1 else 's'}.\n\n"
                f"New: {imported['new']}\n"
                f"Replaced existing: {imported['replaced']}\n"
                f"Kept existing: {imported['kept']}"
            ),
            parent=self,
        )

        self.loaded = None
        self.records = []
        self.file_var.set(
            "No file selected"
        )
        self._refresh_summary()

    def _record_exists(
        self,
        table_name,
        record,
    ):
        site_id = self.site_id_getter()
        patient_id = self._patient_id(
            record
        )
        record_id = self._record_id(
            table_name,
            record,
        )

        if not patient_id or not record_id:
            return False

        if table_name == "Clinical":
            return (
                self.metadata_store.clinical_assessment(
                    site_id,
                    patient_id,
                    record_id,
                )
                is not None
            )

        return (
            self.repository.get_record(
                site_id,
                table_name,
                record_id,
                patient_id=patient_id,
            )
            is not None
        )

    def _reconcile_surgical_clinical(
        self,
        records,
    ):
        from MetadataPipeline.forms.clinical_assessment import (
            reconcile_clinical_assessment,
        )

        site_id = self.site_id_getter()
        grouped = defaultdict(
            list
        )

        for record in records:
            grouped[
                self._patient_id(
                    record
                )
            ].append(
                record
            )

        resolved_records = []

        for patient_id in sorted(
            grouped
        ):
            patient_records = grouped[
                patient_id
            ]

            assessment_id = reconcile_clinical_assessment(
                self,
                self.dictionary,
                self.metadata_store,
                site_id,
                patient_id,
                return_to="Surgical Metadata Review",
            )

            if assessment_id in {
                None,
                "back",
            }:
                return None

            for record in patient_records:
                record[
                    "Clinical Assessment ID"
                ] = assessment_id
                resolved_records.append(
                    record
                )

        return resolved_records

    def _import_clinical(self, records):
        site_id = self.site_id_getter()
        fields = self.dictionary["tables"]["Clinical"]["fields"]

        decisions = self._resolve_existing_records(
            "Clinical",
            records,
            fields,
        )

        if decisions is None:
            return None

        grouped = defaultdict(list)
        replace_ids = defaultdict(set)
        new_count = 0
        replaced = 0
        kept = 0

        for record in records:
            patient_id = self._patient_id(record)
            assessment_id = self._record_id(
                "Clinical",
                record,
            )
            key = (
                patient_id,
                assessment_id,
            )
            decision = decisions.get(
                key,
                "new",
            )

            if decision == "keep":
                kept += 1
                continue

            if decision == "replace":
                replaced += 1
                replace_ids[patient_id].add(
                    assessment_id
                )
            else:
                new_count += 1

            grouped[patient_id].append(
                record
            )

        try:
            for patient_id, patient_records in grouped.items():
                self.metadata_store.import_clinical_assessments(
                    site_id,
                    patient_id,
                    patient_records,
                    replace_existing_ids=replace_ids[
                        patient_id
                    ],
                )
        except ValueError as exc:
            messagebox.showerror(
                "Clinical metadata could not be imported",
                str(exc),
                parent=self,
            )
            return None

        return {
            "saved": new_count + replaced,
            "new": new_count,
            "replaced": replaced,
            "kept": kept,
            "patients": len({
                self._patient_id(record)
                for record in records
            }),
        }

    def _import_surgical(self, records):
        site_id = self.site_id_getter()
        fields = self.dictionary["tables"]["Surgical"]["fields"]

        reference_errors = self._surgical_reference_errors(
            records
        )

        if reference_errors:
            messagebox.showerror(
                "Clinical Assessment references need attention",
                (
                    "Each Surgical record must reference an existing "
                    "Clinical Assessment for the same participant.\n\n"
                    + "\n".join(
                        reference_errors[:20]
                    )
                ),
                parent=self,
            )
            return None

        decisions = self._resolve_existing_records(
            "Surgical",
            records,
            fields,
        )

        if decisions is None:
            return None

        new_count = 0
        replaced = 0
        kept = 0
        saved = 0

        for record in records:
            patient_id = self._patient_id(
                record
            )
            surgery_id = self._record_id(
                "Surgical",
                record,
            )
            key = (
                patient_id,
                surgery_id,
            )
            decision = decisions.get(
                key,
                "new",
            )

            if decision == "keep":
                kept += 1
                continue

            if decision == "replace":
                replaced += 1
            else:
                new_count += 1

            self.repository.save_record(
                site_id,
                "Surgical",
                record,
                source="metadata_batch_import",
            )
            saved += 1

        return {
            "saved": saved,
            "new": new_count,
            "replaced": replaced,
            "kept": kept,
            "patients": len({
                self._patient_id(record)
                for record in records
            }),
        }

    def _resolve_existing_records(
        self,
        table_name,
        records,
        fields,
    ):
        site_id = self.site_id_getter()
        decisions = {}
        conflicts = []

        for record in records:
            patient_id = self._patient_id(
                record
            )
            record_id = self._record_id(
                table_name,
                record,
            )

            if table_name == "Clinical":
                existing = self.metadata_store.clinical_assessment(
                    site_id,
                    patient_id,
                    record_id,
                )
                existing_metadata = (
                    existing["metadata"]
                    if existing
                    else None
                )
            else:
                existing = self.repository.get_record(
                    site_id,
                    table_name,
                    record_id,
                    patient_id=patient_id,
                )
                existing_metadata = (
                    existing["metadata"]
                    if existing
                    else None
                )

            if existing_metadata is None:
                continue

            changed = self._changed_fields(
                existing_metadata,
                record,
                fields,
            )
            key = (
                patient_id,
                record_id,
            )

            if not changed:
                decisions[key] = "keep"
                continue

            conflicts.append({
                "patient_id": patient_id,
                "record_id": record_id,
                "existing": existing_metadata,
                "uploaded": record,
            })

        if not conflicts:
            return decisions

        validator = MetadataValidator(
            self.dictionary
        )

        dialog = BatchSideBySideConflictDialog(
            self,
            table_name=table_name,
            conflicts=conflicts,
            fields=fields,
            validate_record=lambda record: validator.validate_record(
                table_name,
                record,
            ),
        )
        self.wait_window(
            dialog
        )

        if dialog.result is None:
            return None

        decisions.update(
            dialog.result
        )
        return decisions

    def _surgical_reference_errors(
        self,
        records,
    ):
        site_id = self.site_id_getter()
        errors = []

        for record in records:
            patient_id = self._patient_id(
                record
            )
            surgery_id = self._record_id(
                "Surgical",
                record,
            )
            assessment_id = str(
                record.get(
                    "Clinical Assessment ID"
                )
                or ""
            ).strip()

            if not assessment_id:
                errors.append(
                    f"Patient {patient_id}, Surgery {surgery_id}: "
                    "Clinical Assessment ID is blank."
                )
                continue

            if not self.metadata_store.clinical_assessment_id_exists(
                site_id,
                patient_id,
                assessment_id,
            ):
                errors.append(
                    f"Patient {patient_id}, Surgery {surgery_id}: "
                    f"{assessment_id} does not exist for this patient."
                )

        return errors

    @staticmethod
    def _manual_review_lines(
        table_name,
        records,
        validator,
    ):
        lines = []

        for record in records:
            validation = validator.validate_record(
                table_name,
                record,
            )
            patient_id = str(
                record.get(
                    "CoCANoT Patient ID"
                )
                or ""
            ).strip()

            for result in validation["results"]:
                if result["status"] != "manual_review":
                    continue

                field_name = result["field_name"]
                value = record.get(
                    field_name
                )

                if value in (
                    None,
                    "",
                    [],
                ):
                    continue

                lines.append(
                    f"Patient {patient_id} — "
                    f"{field_name}: {_display_value(value)}"
                )

        return lines

    @staticmethod
    def _blocking_validation_errors(
        validation,
    ):
        return [
            result
            for result in validation["results"]
            if result["status"] in {
                "invalid",
                "missing_required",
            }
        ]

    @staticmethod
    def _patient_id(record):
        return str(
            record.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()

    @staticmethod
    def _record_id(
        table_name,
        record,
    ):
        field_name = RECORD_ID_FIELDS[
            table_name
        ]
        return str(
            record.get(
                field_name
            )
            or ""
        ).strip().upper()

    def _duplicate_errors(
        self,
        table_name,
        records,
    ):
        seen = set()
        errors = []

        for record in records:
            patient_id = self._patient_id(
                record
            )
            record_id = self._record_id(
                table_name,
                record,
            )
            key = (
                patient_id,
                record_id,
            )

            if key in seen:
                errors.append(
                    f"{record_id or '(blank ID)'} appears more than once "
                    f"for Patient {patient_id or '(blank)'}."
                )
                continue

            seen.add(
                key
            )

        return errors

    def _clinical_id_errors(
        self,
        records,
    ):
        errors = []

        for record in records:
            patient_id = self._patient_id(
                record
            )
            assessment_id = self._record_id(
                "Clinical",
                record,
            )
            match = re.fullmatch(
                r"CA-(\d+)",
                assessment_id,
            )

            if match is None:
                errors.append(
                    f"Patient {patient_id}: {assessment_id or '(blank)'} "
                    "must use the format CA-001, CA-002, and so on."
                )
                continue

            number = int(
                match.group(1)
            )
            canonical = f"CA-{number:03d}"

            if number < 1 or canonical != assessment_id:
                errors.append(
                    f"Patient {patient_id}: use canonical ID {canonical}."
                )

        return errors

    @staticmethod
    def _changed_fields(
        existing,
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

            left = _normalized(
                existing.get(
                    field_name
                )
            )
            right = _normalized(
                uploaded.get(
                    field_name
                )
            )

            if left != right:
                changed.append(
                    field_name
                )

        return changed



class BatchSideBySideConflictDialog(tk.Toplevel):
    """Compare stored and uploaded records with an editable uploaded column."""

    def __init__(
        self,
        parent,
        table_name,
        conflicts,
        fields,
        validate_record,
    ):
        super().__init__(parent)

        self.table_name = table_name
        self.conflicts = conflicts
        self.fields = fields
        self.validate_record = validate_record

        self.result = None
        self.decisions = {}
        self.current_index = 0

        self.variables = {}
        self.field_frames = {}
        self.error_labels = {}
        self._updating = False

        self.title(
            f"Compare Existing {table_name} Metadata"
        )
        self.geometry(
            "1180x820"
        )
        self.minsize(
            950,
            650,
        )
        self.transient(
            parent.winfo_toplevel()
        )
        self.protocol(
            "WM_DELETE_WINDOW",
            self._cancel,
        )

        self.columnconfigure(
            0,
            weight=1,
        )
        self.rowconfigure(
            2,
            weight=1,
        )

        self._build_header()
        self._build_column_headers()
        self._build_comparison_area()
        self._build_footer()

        self.update_idletasks()
        self.grab_set()

        self._load_current_conflict()

    def _build_header(self):
        header = ttk.Frame(
            self,
            padding=(18, 16, 18, 10),
        )
        header.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        header.columnconfigure(
            0,
            weight=1,
        )

        self.title_label = ttk.Label(
            header,
            text="",
            font=("", 16, "bold"),
        )
        self.title_label.grid(
            row=0,
            column=0,
            sticky="w",
        )

        self.progress_label = ttk.Label(
            header,
            text="",
        )
        self.progress_label.grid(
            row=0,
            column=1,
            sticky="e",
        )

        ttk.Label(
            header,
            text=(
                "The stored version is shown on the left. "
                "Review or edit the uploaded version on the right, "
                "then choose which version to keep."
            ),
            wraplength=1050,
        ).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(5, 0),
        )

    def _build_column_headers(self):
        headings = ttk.Frame(
            self,
            padding=(18, 0, 34, 6),
        )
        headings.grid(
            row=1,
            column=0,
            sticky="ew",
        )
        headings.columnconfigure(
            0,
            weight=2,
        )
        headings.columnconfigure(
            1,
            weight=3,
        )
        headings.columnconfigure(
            2,
            weight=3,
        )

        ttk.Label(
            headings,
            text="Field",
            font=("", 11, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            headings,
            text="Existing",
            font=("", 11, "bold"),
        ).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(12, 12),
        )

        ttk.Label(
            headings,
            text="Uploaded",
            font=("", 11, "bold"),
        ).grid(
            row=0,
            column=2,
            sticky="w",
        )

    def _build_comparison_area(self):
        outer = ttk.Frame(
            self,
            padding=(18, 0, 18, 0),
        )
        outer.grid(
            row=2,
            column=0,
            sticky="nsew",
        )
        outer.columnconfigure(
            0,
            weight=1,
        )
        outer.rowconfigure(
            0,
            weight=1,
        )

        self.canvas = tk.Canvas(
            outer,
            highlightthickness=0,
        )
        self.canvas.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        scrollbar = ttk.Scrollbar(
            outer,
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

        self.form = ttk.Frame(
            self.canvas,
        )
        self.form_window = self.canvas.create_window(
            (0, 0),
            window=self.form,
            anchor="nw",
        )

        self.form.bind(
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
                self.form_window,
                width=event.width,
            ),
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
            padding=(18, 10, 18, 16),
        )
        footer.grid(
            row=3,
            column=0,
            sticky="ew",
        )
        footer.columnconfigure(
            0,
            weight=1,
        )

        self.status_label = ttk.Label(
            footer,
            text="",
            wraplength=620,
        )
        self.status_label.grid(
            row=0,
            column=0,
            sticky="w",
        )

        actions = ttk.Frame(
            footer
        )
        actions.grid(
            row=0,
            column=1,
            sticky="e",
        )

        ttk.Button(
            actions,
            text="Cancel",
            command=self._cancel,
        ).pack(
            side="right",
        )

        ttk.Button(
            actions,
            text="Use Uploaded Version",
            command=lambda: self._choose(
                "replace"
            ),
        ).pack(
            side="right",
            padx=(0, 8),
        )

        ttk.Button(
            actions,
            text="Keep Existing",
            command=lambda: self._choose(
                "keep"
            ),
        ).pack(
            side="right",
            padx=(0, 8),
        )

    def _load_current_conflict(self):
        conflict = self.conflicts[
            self.current_index
        ]

        self.title_label.configure(
            text=(
                f"Patient {conflict['patient_id']}  •  "
                f"{conflict['record_id']}"
            )
        )

        self.progress_label.configure(
            text=(
                f"Record {self.current_index + 1} "
                f"of {len(self.conflicts)}"
            )
        )

        for child in self.form.winfo_children():
            child.destroy()

        self.variables = {}
        self.field_frames = {}
        self.error_labels = {}

        self.form.columnconfigure(
            0,
            weight=2,
        )
        self.form.columnconfigure(
            1,
            weight=3,
        )
        self.form.columnconfigure(
            2,
            weight=3,
        )

        existing = conflict[
            "existing"
        ]
        uploaded = conflict[
            "uploaded"
        ]

        row = 0

        for field in self.fields:
            field_name = field.get(
                "field_name"
            )

            if not field_name:
                continue

            if self._is_true(
                field.get(
                    "system_generated"
                )
            ) and not (
                self.table_name == "Clinical"
                and field_name == "Clinical Assessment ID"
            ):
                continue

            frame = ttk.Frame(
                self.form,
            )
            frame.grid(
                row=row,
                column=0,
                columnspan=3,
                sticky="ew",
                pady=(0, 1),
            )
            frame.columnconfigure(
                0,
                weight=2,
            )
            frame.columnconfigure(
                1,
                weight=3,
            )
            frame.columnconfigure(
                2,
                weight=3,
            )

            self.field_frames[
                field_name
            ] = frame

            prompt = (
                field.get(
                    "ui_prompt"
                )
                or field_name
            )

            ttk.Label(
                frame,
                text=prompt,
                wraplength=260,
                anchor="nw",
            ).grid(
                row=0,
                column=0,
                sticky="nw",
                padx=(0, 12),
                pady=7,
            )

            ttk.Label(
                frame,
                text=_display_value(
                    existing.get(
                        field_name
                    )
                ),
                wraplength=330,
                anchor="nw",
            ).grid(
                row=0,
                column=1,
                sticky="nw",
                padx=(0, 12),
                pady=7,
            )

            self._add_uploaded_editor(
                frame,
                field,
                uploaded,
            )

            error_label = ttk.Label(
                frame,
                text="",
                foreground="red",
                wraplength=330,
            )
            error_label.grid(
                row=1,
                column=2,
                sticky="w",
                pady=(0, 7),
            )

            self.error_labels[
                field_name
            ] = error_label

            row += 1

        self._save_uploaded()
        self._refresh_conditions()
        self._validate_uploaded()
        self.canvas.yview_moveto(
            0
        )

    def _add_uploaded_editor(
        self,
        parent,
        field,
        uploaded,
    ):
        field_name = field[
            "field_name"
        ]
        input_type = (
            field.get(
                "input_type"
            )
            or "free_text"
        )

        identity_field = field_name in {
            "CoCANoT Patient ID",
            RECORD_ID_FIELDS.get(
                self.table_name,
                "",
            ),
        }

        value = uploaded.get(
            field_name
        )

        if input_type == "multi_select":
            selected = value

            if type(selected) is str:
                selected = [
                    item.strip()
                    for item in selected.split(
                        ";"
                    )
                    if item.strip()
                ]

            if selected is None:
                selected = []

            container = ttk.Frame(
                parent
            )
            container.grid(
                row=0,
                column=2,
                sticky="ew",
                pady=4,
            )

            choices = {}

            for allowed in self._allowed_values(
                field,
                uploaded,
            ):
                variable = tk.BooleanVar(
                    value=allowed in selected,
                )
                choices[
                    allowed
                ] = variable

                ttk.Checkbutton(
                    container,
                    text=allowed,
                    variable=variable,
                    command=self._field_changed,
                    state=(
                        "disabled"
                        if identity_field
                        else "normal"
                    ),
                ).pack(
                    anchor="w",
                )

            self.variables[
                field_name
            ] = choices
            return

        if value is None:
            value = ""

        variable = tk.StringVar(
            value=str(
                value
            )
        )
        self.variables[
            field_name
        ] = variable

        if input_type == "single_select":
            widget = ttk.Combobox(
                parent,
                textvariable=variable,
                values=self._allowed_values(
                    field,
                    uploaded,
                ),
                state=(
                    "disabled"
                    if identity_field
                    else "readonly"
                ),
            )
        else:
            widget = ttk.Entry(
                parent,
                textvariable=variable,
                state=(
                    "disabled"
                    if identity_field
                    else "normal"
                ),
            )

        widget.grid(
            row=0,
            column=2,
            sticky="ew",
            pady=4,
        )

        if not identity_field:
            variable.trace_add(
                "write",
                lambda *_args: self._field_changed(),
            )

    def _field_changed(self):
        if self._updating:
            return

        self._save_uploaded()
        self._refresh_conditions()
        self._validate_uploaded()

    def _save_uploaded(self):
        if not self.conflicts:
            return

        uploaded = self.conflicts[
            self.current_index
        ]["uploaded"]

        for field_name, variable in self.variables.items():
            if type(variable) is dict:
                uploaded[
                    field_name
                ] = [
                    value
                    for value, choice in variable.items()
                    if choice.get()
                ]
            else:
                uploaded[
                    field_name
                ] = variable.get().strip()

    def _refresh_conditions(self):
        uploaded = self.conflicts[
            self.current_index
        ]["uploaded"]

        self._updating = True

        try:
            for field in self.fields:
                field_name = field.get(
                    "field_name"
                )
                frame = self.field_frames.get(
                    field_name
                )

                if frame is None:
                    continue

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
                    continue

                frame.grid_remove()
                self._clear_value(
                    field_name,
                    uploaded,
                )
        finally:
            self._updating = False

    def _clear_value(
        self,
        field_name,
        uploaded,
    ):
        variable = self.variables.get(
            field_name
        )

        if variable is None:
            return

        if type(variable) is dict:
            for choice in variable.values():
                if choice.get():
                    choice.set(
                        False
                    )

            uploaded[
                field_name
            ] = []
            return

        if variable.get():
            variable.set(
                ""
            )

        uploaded[
            field_name
        ] = ""

    def _validate_uploaded(self):
        self._save_uploaded()

        uploaded = self.conflicts[
            self.current_index
        ]["uploaded"]

        validation = self.validate_record(
            uploaded
        )

        blocking = {}

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

            blocking[
                result["field_name"]
            ] = result[
                "message"
            ]

        for field_name, label in self.error_labels.items():
            label.configure(
                text=blocking.get(
                    field_name,
                    ""
                )
            )

        if blocking:
            self.status_label.configure(
                text=(
                    f"{len(blocking)} uploaded field"
                    f"{'' if len(blocking) == 1 else 's'} "
                    "need correction before the uploaded version can be used."
                )
            )
        else:
            self.status_label.configure(
                text="Uploaded version passes automatic validation."
            )

        return not blocking

    def _choose(
        self,
        decision,
    ):
        self._save_uploaded()

        if (
            decision == "replace"
            and not self._validate_uploaded()
        ):
            messagebox.showerror(
                "Uploaded metadata needs correction",
                (
                    "Correct the highlighted uploaded values before "
                    "using the uploaded version."
                ),
                parent=self,
            )
            return

        conflict = self.conflicts[
            self.current_index
        ]
        key = (
            conflict["patient_id"],
            conflict["record_id"],
        )

        self.decisions[
            key
        ] = decision

        if self.current_index + 1 < len(
            self.conflicts
        ):
            self.current_index += 1
            self._load_current_conflict()
            return

        self.result = dict(
            self.decisions
        )
        self.destroy()

    def _allowed_values(
        self,
        field,
        uploaded,
    ):
        values = field.get(
            "allowed_values",
            [],
        )

        if field.get(
            "validation_method"
        ) != "conditional_allowed_values":
            return (
                values
                if type(values) is list
                else []
            )

        mapping = field.get(
            "conditional_allowed_values",
            {},
        )

        if type(mapping) is not dict:
            return (
                values
                if type(values) is list
                else []
            )

        parent = self._conditional_parent(
            field,
            mapping,
        )

        if parent is None:
            return (
                values
                if type(values) is list
                else []
            )

        parent_value = uploaded.get(
            parent[
                "field_name"
            ]
        )

        conditional = mapping.get(
            str(
                parent_value
            )
        )

        if type(conditional) is list:
            return conditional

        return []

    def _conditional_parent(
        self,
        child_field,
        mapping,
    ):
        mapping_keys = {
            str(key)
            for key in mapping
        }

        candidates = []

        for field in self.fields:
            if field.get(
                "field_order"
            ) >= child_field.get(
                "field_order"
            ):
                continue

            allowed = field.get(
                "allowed_values",
                [],
            )

            allowed_text = {
                str(value)
                for value in (
                    allowed
                    if type(allowed) is list
                    else []
                )
            }

            if (
                mapping_keys
                and mapping_keys.issubset(
                    allowed_text
                )
            ):
                candidates.append(
                    field
                )

        if not candidates:
            return None

        candidates.sort(
            key=lambda field: field[
                "field_order"
            ],
            reverse=True,
        )

        return candidates[
            0
        ]

    @staticmethod
    def _is_true(
        value,
    ):
        if value is True:
            return True

        if value is None:
            return False

        return str(
            value
        ).strip().lower() in {
            "true",
            "yes",
            "1",
        }

    def _cancel(self):
        self.result = None
        self.destroy()

    def _mousewheel(
        self,
        event,
    ):
        if event.delta:
            self.canvas.yview_scroll(
                int(
                    -1 * (
                        event.delta / 120
                    )
                ),
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
