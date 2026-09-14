"""Patient metadata and linked-data explorer."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from MetadataPipeline.storage.data_link_store import (
    PatientDataLinkStore,
)
from MetadataPipeline.storage.record_deletion import (
    RecordDeletionService,
)

from .patient_data_review import PatientDataReview
from .record_table import RecordTable


class PatientExplorer(ttk.Frame):
    """Show all locally stored data for one Site + Patient."""

    def __init__(
        self,
        parent,
        repository,
        site_id_getter,
        on_open_record,
        on_open_clinical,
        on_add_clinical,
        on_upload_clinical,
        on_add_surgical,
        on_upload_surgical,
        on_add_imaging,
        on_add_electrophysiology,
        on_add_patient,
    ):
        super().__init__(parent)

        self.repository = repository
        self.site_id_getter = site_id_getter
        self.on_open_record = on_open_record
        self.on_open_clinical = on_open_clinical
        self.on_add_clinical = on_add_clinical
        self.on_upload_clinical = on_upload_clinical
        self.on_add_surgical = on_add_surgical
        self.on_upload_surgical = on_upload_surgical
        self.on_add_imaging = on_add_imaging
        self.on_add_electrophysiology = on_add_electrophysiology
        self.on_add_patient = on_add_patient
        self.data_links = PatientDataLinkStore()
        self.record_deletion = RecordDeletionService()

        self.patient_var = tk.StringVar()
        self._loaded_patient_id = ""

        self.columnconfigure(0, weight=1)

        lookup = ttk.LabelFrame(
            self,
            text="Patient Data Review",
            padding=10,
        )
        lookup.grid(row=0, column=0, sticky="ew")
        lookup.columnconfigure(1, weight=1)

        ttk.Label(
            lookup,
            text="CoCANoT Patient ID",
        ).grid(row=0, column=0, sticky="w")

        self.patient_combo = ttk.Combobox(
            lookup,
            textvariable=self.patient_var,
            state="readonly",
        )
        self.patient_combo.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(8, 8),
        )
        self.patient_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.load_patient(),
        )

        ttk.Button(
            lookup,
            text="Load Patient",
            command=self.load_patient,
        ).grid(row=0, column=2)

        ttk.Button(
            lookup,
            text="+ Add New Patient",
            command=self.on_add_patient,
        ).grid(
            row=0,
            column=3,
            padx=(6, 0),
        )

        ttk.Button(
            lookup,
            text="Refresh",
            command=self.refresh_patient_ids,
        ).grid(
            row=0,
            column=4,
            padx=(6, 0),
        )

        self.clinical_table = RecordTable(
            self,
            "Clinical Assessments",
            on_open=self.on_open_clinical,
            add_text="Add Clinical Assessment",
            on_add=self.on_add_clinical,
            secondary_add_text="Upload Clinical Assessments",
            on_secondary_add=self.on_upload_clinical,
            on_delete=self._delete_clinical_record,
        )
        self.clinical_table.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )

        self.surgical_table = RecordTable(
            self,
            "Surgical Records",
            on_open=lambda record: self.on_open_record(
                "Surgical",
                record,
            ),
            add_text="Add Surgical Record",
            on_add=self.on_add_surgical,
            secondary_add_text="Upload Surgical CSV/XLSX",
            on_secondary_add=self.on_upload_surgical,
            on_delete=lambda record: self._delete_metadata_record(
                "Surgical",
                record,
            ),
        )
        self.surgical_table.grid(
            row=2,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )

        self.imaging_table = RecordTable(
            self,
            "Imaging Data",
            on_open=lambda record: self._open_patient_data(
                "Imaging",
                record,
            ),
            open_text="Review Patient Data",
            add_text="Add Imaging Data",
            on_add=self.on_add_imaging,
            on_delete=lambda record: self._delete_metadata_record(
                "Imaging",
                record,
            ),
        )
        self.imaging_table.grid(
            row=3,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )

        self.ephys_table = RecordTable(
            self,
            "Electrophysiology Data",
            on_open=lambda record: self._open_patient_data(
                "Electrophysiology",
                record,
            ),
            open_text="Review Patient Data",
            add_text="Add Electrophysiology Data",
            on_add=self.on_add_electrophysiology,
            on_delete=lambda record: self._delete_metadata_record(
                "Electrophysiology",
                record,
            ),
        )
        self.ephys_table.grid(
            row=4,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )

        self.refresh_patient_ids()

        if self.current_patient_id():
            self.load_patient()

    def _open_patient_data(
        self,
        table_name,
        record,
    ):
        PatientDataReview(
            self,
            table_name=table_name,
            record=record,
            on_edit_metadata=lambda: self.on_open_record(
                table_name,
                record,
            ),
            on_delete=lambda selected_record: self._delete_metadata_record(
                table_name,
                selected_record,
            ),
        )

    def _delete_metadata_record(
        self,
        table_name,
        record,
    ):
        patient_id = str(
            record.get(
                "patient_id",
                "",
            )
            or ""
        ).strip()
        record_id = str(
            record.get(
                "record_id",
                "",
            )
            or ""
        ).strip()

        label = {
            "Surgical": "Surgical record",
            "Imaging": "Imaging record",
            "Electrophysiology": "Electrophysiology record",
        }.get(
            table_name,
            "record",
        )

        if not messagebox.askyesno(
            f"Delete {label}?",
            (
                f"Patient: {patient_id}\n"
                f"Record: {record_id}\n\n"
                "This removes the CoCANoT record from the local database. "
                "For Imaging and Electrophysiology, its saved data link "
                "will also be removed.\n\n"
                "The actual NIfTI, EDF, JSON, TSV, and other files on disk "
                "will NOT be deleted.\n\n"
                "Delete this record?"
            ),
            parent=self.winfo_toplevel(),
        ):
            return False

        deleted = self.record_deletion.delete_metadata_record(
            self.site_id_getter(),
            patient_id,
            table_name,
            record_id,
        )

        if not deleted:
            messagebox.showerror(
                "Record not deleted",
                "The selected record could not be found in the local database.",
                parent=self.winfo_toplevel(),
            )
            return False

        if table_name in {
            "Imaging",
            "Electrophysiology",
        }:
            self.data_links.delete_link(
                self.site_id_getter(),
                patient_id,
                table_name,
                record_id,
            )

        self.load_patient()

        messagebox.showinfo(
            "Record deleted",
            (
                f"{label} {record_id} was removed from the local database.\n\n"
                "Processed data files on disk were left unchanged."
            ),
            parent=self.winfo_toplevel(),
        )
        return True

    def _delete_clinical_record(
        self,
        record,
    ):
        patient_id = str(
            record.get(
                "patient_id",
                "",
            )
            or ""
        ).strip()
        assessment_id = str(
            record.get(
                "record_id",
                "",
            )
            or ""
        ).strip()

        references = (
            self.record_deletion.clinical_assessment_references(
                self.site_id_getter(),
                patient_id,
                assessment_id,
            )
        )

        if references:
            counts = {}

            for reference in references:
                table_name = reference[
                    "table_name"
                ]
                counts[
                    table_name
                ] = counts.get(
                    table_name,
                    0,
                ) + 1

            details = "\n".join(
                f"{table_name}: {count}"
                for table_name, count in counts.items()
            )

            messagebox.showwarning(
                "Clinical Assessment is in use",
                (
                    f"{assessment_id} cannot be deleted because other "
                    "records currently reference it.\n\n"
                    f"{details}\n\n"
                    "Reassign those records to another Clinical Assessment "
                    "before deleting this assessment."
                ),
                parent=self.winfo_toplevel(),
            )
            return False

        if (
            self.record_deletion.clinical_assessment_count(
                self.site_id_getter(),
                patient_id,
            )
            <= 1
        ):
            messagebox.showwarning(
                "Clinical Assessment required",
                (
                    f"{assessment_id} is the only Clinical Assessment "
                    f"for Patient {patient_id}.\n\n"
                    "A patient must retain at least one Clinical Assessment, "
                    "so this assessment cannot be deleted."
                ),
                parent=self.winfo_toplevel(),
            )
            return False

        if not messagebox.askyesno(
            "Delete Clinical Assessment?",
            (
                f"Patient: {patient_id}\n"
                f"Clinical Assessment: {assessment_id}\n\n"
                "This permanently removes the assessment from the local "
                "CoCANoT database.\n\n"
                "Delete this Clinical Assessment?"
            ),
            parent=self.winfo_toplevel(),
        ):
            return False

        result = self.record_deletion.delete_clinical_assessment(
            self.site_id_getter(),
            patient_id,
            assessment_id,
        )

        if not result.get(
            "deleted"
        ):
            messagebox.showerror(
                "Assessment not deleted",
                "The Clinical Assessment could not be deleted.",
                parent=self.winfo_toplevel(),
            )
            return False

        self.load_patient()

        messagebox.showinfo(
            "Clinical Assessment deleted",
            f"{assessment_id} was removed from the local database.",
            parent=self.winfo_toplevel(),
        )
        return True

    def refresh_patient_ids(
        self,
        preferred_patient_id=None,
    ):
        patient_ids = self.repository.patient_ids_for_site(
            self.site_id_getter()
        )

        self.patient_combo.configure(
            values=tuple(patient_ids)
        )

        current = str(
            preferred_patient_id
            or self.patient_var.get()
            or ""
        ).strip()

        if current in patient_ids:
            self.patient_var.set(current)
        elif patient_ids:
            self.patient_var.set(patient_ids[0])
        else:
            self.patient_var.set("")
            self._loaded_patient_id = ""
            self.clear()
            return

    def current_patient_id(self):
        return self.patient_var.get().strip()

    def loaded_patient_id(self):
        return self._loaded_patient_id.strip()

    def load_patient(self):
        patient_id = self.current_patient_id()

        if not patient_id:
            self._loaded_patient_id = ""
            self.clear()
            return

        summary = self.repository.patient_summary(
            self.site_id_getter(),
            patient_id,
        )

        self._loaded_patient_id = patient_id

        clinical_records = summary["Clinical"]

        self.clinical_table.set_records(
            clinical_records,
            lambda record: self._clinical_summary(
                record,
                current_record=(
                    bool(clinical_records)
                    and record["record_id"]
                    == clinical_records[0]["record_id"]
                ),
            ),
        )
        self.surgical_table.set_records(
            summary["Surgical"],
            self._surgical_summary,
        )
        self.imaging_table.set_records(
            summary["Imaging"],
            self._imaging_summary,
        )
        self.ephys_table.set_records(
            summary["Electrophysiology"],
            self._ephys_summary,
        )

    def clear(self):
        self._loaded_patient_id = ""
        empty = []

        self.clinical_table.set_records(
            empty,
            lambda _record: "",
        )
        self.surgical_table.set_records(
            empty,
            lambda _record: "",
        )
        self.imaging_table.set_records(
            empty,
            lambda _record: "",
        )
        self.ephys_table.set_records(
            empty,
            lambda _record: "",
        )

    @staticmethod
    def _clinical_summary(
        record,
        current_record=False,
    ):
        metadata = record["metadata"]

        values = [
            (
                "Status",
                "Current"
                if current_record
                else "Previous",
            ),
            (
                "Visit Type",
                metadata.get("Visit Type"),
            ),
            (
                "Primary Diagnosis",
                metadata.get("Primary Diagnosis"),
            ),
        ]

        return " | ".join(
            f"{label}: {value}"
            for label, value in values
            if value not in (None, "")
        )

    @staticmethod
    def _surgical_summary(record):
        metadata = record["metadata"]

        values = (
            ("Surgery ID", metadata.get("Surgery ID")),
            (
                "Intent",
                metadata.get("Intent of Surgery (multiselect)"),
            ),
            (
                "Type",
                metadata.get("Type(s) of surgery (multiselect)"),
            ),
        )

        return " | ".join(
            f"{label}: {PatientExplorer._display_summary_value(value)}"
            for label, value in values
            if value not in (None, "", [])
        )

    @staticmethod
    def _imaging_summary(record):
        metadata = record["metadata"]

        values = (
            ("Image ID", metadata.get("Image ID")),
            (
                "Modality",
                metadata.get("Imaging Modality"),
            ),
            (
                "Purpose",
                metadata.get("Purpose of Imaging (multiselect)"),
            ),
        )

        return " | ".join(
            f"{label}: {PatientExplorer._display_summary_value(value)}"
            for label, value in values
            if value not in (None, "", [])
        )

    @staticmethod
    def _ephys_summary(record):
        metadata = record["metadata"]

        values = (
            (
                "Recording ID",
                metadata.get("Recording ID"),
            ),
            (
                "Modality",
                metadata.get("Recording Modality"),
            ),
            (
                "Purpose",
                metadata.get("Purpose of Recording"),
            ),
        )

        return " | ".join(
            f"{label}: {PatientExplorer._display_summary_value(value)}"
            for label, value in values
            if value not in (None, "", [])
        )

    @staticmethod
    def _display_summary_value(value):
        if type(value) is list:
            return ", ".join(
                str(item)
                for item in value
            )

        return str(value)
