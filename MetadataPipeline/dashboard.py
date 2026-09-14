#!/usr/bin/env python3
"""CoCANoT metadata management dashboard."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk


METADATA_PIPELINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = METADATA_PIPELINE_DIR.parent

project_root = str(PROJECT_ROOT)

while project_root in sys.path:
    sys.path.remove(project_root)

sys.path.insert(0, project_root)

from MetadataPipeline.forms.clinical_assessment import (
    ClinicalAssessmentDialog,
    import_clinical_file,
    reconcile_clinical_assessment,
    tracked_clinical_fields,
)
from MetadataPipeline.forms.surgical_import import (
    import_surgical_file,
)
from MetadataPipeline.storage import LocalMetadataStore
from MetadataPipeline.storage.record_repository import (
    MetadataRepository,
)
from MetadataPipeline.views.batch_import import MetadataBatchImport
from MetadataPipeline.views.clinical_review import ClinicalAssessmentReview
from MetadataPipeline.views.metadata_editor import MetadataEditor
from MetadataPipeline.views.metadata_home import MetadataHome
from MetadataPipeline.views.patient_explorer import PatientExplorer
from MetadataPipeline.validation.dictionary_loader import load_dictionary


METADATA_DICTIONARY = (
    METADATA_PIPELINE_DIR
    / "dictionaries"
    / "CoCANoT_Metadata_Phase1.xlsx"
)


class MetadataDashboard(ttk.Frame):
    """Manage locally stored CoCANoT metadata."""

    def __init__(
        self,
        parent,
        site_id="",
        on_back=None,
        initial_view="home",
    ):
        super().__init__(parent)

        self.on_back = on_back
        self.initial_view = initial_view

        self.dictionary = load_dictionary(
            METADATA_DICTIONARY
        )
        self.metadata_store = LocalMetadataStore()
        self.repository = MetadataRepository()

        self.site_id = str(site_id or "").strip()

        if self.site_id:
            self.site_id = self.metadata_store.set_site_id(
                self.site_id
            )
        else:
            self.site_id = self._require_site_id()

        if not self.site_id:
            # When embedded in the unified app, close only this page.
            # Standalone mode still closes the root window.
            if self.on_back is not None:
                self.after_idle(self.on_back)
            else:
                self.after_idle(self.winfo_toplevel().destroy)
            return

        self.site_var = tk.StringVar(
            value=f"Site: {self.site_id}"
        )

        self.explorer = None
        self.current_view = None

        # Track application-level mousewheel bindings created by the
        # patient explorer.  These must be explicitly removed before the
        # explorer canvas (or this dashboard) is destroyed.
        self._wheel_bindings = []
        self._wheel_canvas = None

        self._build_interface()

        if self.initial_view == "patient_explorer":
            self._show_patient_explorer(
                external_entry=True
            )
        else:
            self._show_home()

    def _require_site_id(self):
        site_id = self.metadata_store.get_site_id()

        if site_id:
            return site_id

        value = simpledialog.askstring(
            "CoCANoT Site Setup",
            "Enter the Site ID for this local installation.",
            parent=self,
        )

        if value is None:
            return ""

        try:
            return self.metadata_store.set_site_id(
                value
            )
        except ValueError as exc:
            messagebox.showerror(
                "Site ID required",
                str(exc),
                parent=self,
            )
            return ""

    def _build_interface(self):
        shell = ttk.Frame(self)
        shell.pack(
            fill="both",
            expand=True,
        )
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(
            shell,
            padding=(16, 14, 16, 10),
        )
        header.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="Patient Data Review",
            font=("", 22, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            header,
            textvariable=self.site_var,
        ).grid(
            row=0,
            column=1,
            padx=(10, 8),
        )

        ttk.Button(
            header,
            text="Change Site",
            command=self._change_site,
        ).grid(
            row=0,
            column=2,
        )

        self.content = ttk.Frame(
            shell,
            padding=(16, 6, 16, 16),
        )
        self.content.grid(
            row=1,
            column=0,
            sticky="nsew",
        )
        self.content.columnconfigure(
            0,
            weight=1,
        )
        self.content.rowconfigure(
            0,
            weight=1,
        )

    def _clear_content(self):
        # A Tk binding can outlive the widget captured by its callback.
        # Remove our toplevel mousewheel bindings before destroying the
        # canvas/view that they reference.
        self._unbind_patient_explorer_mousewheel()

        for child in self.content.winfo_children():
            child.destroy()

        self.current_view = None
        self.explorer = None

    def destroy(self):
        # Navigation in the unified application destroys whole pages.
        # Ensure no wheel callback still points at this dashboard's canvas.
        self._unbind_patient_explorer_mousewheel()
        super().destroy()

    def _bind_patient_explorer_mousewheel(self, canvas):
        self._unbind_patient_explorer_mousewheel()

        try:
            if not canvas.winfo_exists():
                return
            bind_target = self.winfo_toplevel()
        except tk.TclError:
            return

        self._wheel_canvas = canvas

        mousewheel_id = bind_target.bind(
            "<MouseWheel>",
            self._on_patient_explorer_mousewheel,
            add="+",
        )
        button4_id = bind_target.bind(
            "<Button-4>",
            self._on_patient_explorer_mousewheel_linux,
            add="+",
        )
        button5_id = bind_target.bind(
            "<Button-5>",
            self._on_patient_explorer_mousewheel_linux,
            add="+",
        )

        self._wheel_bindings = [
            (bind_target, "<MouseWheel>", mousewheel_id),
            (bind_target, "<Button-4>", button4_id),
            (bind_target, "<Button-5>", button5_id),
        ]

    def _unbind_patient_explorer_mousewheel(self):
        bindings = getattr(self, "_wheel_bindings", [])

        for bind_target, sequence, funcid in bindings:
            if not funcid:
                continue
            try:
                bind_target.unbind(sequence, funcid)
            except tk.TclError:
                # The toplevel may already be in the process of closing.
                pass

        self._wheel_bindings = []
        self._wheel_canvas = None

    def _event_is_inside_patient_explorer(self, event):
        canvas = self._wheel_canvas

        if canvas is None:
            return False

        try:
            if not canvas.winfo_exists():
                self._unbind_patient_explorer_mousewheel()
                return False

            widget = event.widget
            while widget is not None:
                if widget is canvas:
                    return True

                parent_name = widget.winfo_parent()
                if not parent_name:
                    break

                widget = widget._nametowidget(parent_name)

        except (tk.TclError, KeyError):
            return False

        return False

    def _scroll_patient_explorer(self, units):
        canvas = self._wheel_canvas

        if canvas is None:
            return

        try:
            if not canvas.winfo_exists():
                self._unbind_patient_explorer_mousewheel()
                return

            if units:
                canvas.yview_scroll(units, "units")
        except tk.TclError:
            # The canvas can disappear during navigation between the event
            # being queued and the callback being executed.
            self._unbind_patient_explorer_mousewheel()

    def _on_patient_explorer_mousewheel(self, event):
        if not self._event_is_inside_patient_explorer(event):
            return

        delta = getattr(event, "delta", 0)
        if not delta:
            return

        # Windows commonly reports +/-120; macOS can report smaller values.
        if abs(delta) >= 120:
            units = int(-delta / 120)
        else:
            units = -1 if delta > 0 else 1

        self._scroll_patient_explorer(units)

    def _on_patient_explorer_mousewheel_linux(self, event):
        if not self._event_is_inside_patient_explorer(event):
            return

        if event.num == 4:
            self._scroll_patient_explorer(-1)
        elif event.num == 5:
            self._scroll_patient_explorer(1)

    def _show_home(self):
        self._clear_content()

        page = ttk.Frame(
            self.content
        )
        page.grid(
            row=0,
            column=0,
            sticky="nsew",
        )
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)

        if self.on_back is not None:
            navigation = ttk.Frame(page)
            navigation.grid(
                row=0,
                column=0,
                sticky="ew",
                pady=(0, 10),
            )

            ttk.Button(
                navigation,
                text="Back",
                command=self.on_back,
            ).pack(side="left")

        self.current_view = MetadataHome(
            page,
            on_open_patient_explorer=self._show_patient_explorer,
            on_open_batch_import=self._show_batch_import,
        )
        self.current_view.grid(
            row=1,
            column=0,
            sticky="nsew",
        )

    def _show_patient_explorer(
        self,
        external_entry=False,
    ):
        self._clear_content()

        scroll_container = ttk.Frame(
            self.content
        )
        scroll_container.grid(
            row=0,
            column=0,
            sticky="nsew",
        )
        scroll_container.columnconfigure(
            0,
            weight=1,
        )
        scroll_container.rowconfigure(
            0,
            weight=1,
        )

        canvas = tk.Canvas(
            scroll_container,
            highlightthickness=0,
        )
        canvas.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        scrollbar = ttk.Scrollbar(
            scroll_container,
            orient="vertical",
            command=canvas.yview,
        )
        scrollbar.grid(
            row=0,
            column=1,
            sticky="ns",
        )

        canvas.configure(
            yscrollcommand=scrollbar.set,
        )

        page = ttk.Frame(
            canvas,
            padding=(0, 0, 8, 8),
        )
        page.columnconfigure(
            0,
            weight=1,
        )

        window_id = canvas.create_window(
            (0, 0),
            window=page,
            anchor="nw",
        )

        def update_scroll_region(_event=None):
            canvas.configure(
                scrollregion=canvas.bbox(
                    "all"
                )
            )

        def resize_page(event):
            canvas.itemconfigure(
                window_id,
                width=event.width,
            )

        page.bind(
            "<Configure>",
            update_scroll_region,
        )
        canvas.bind(
            "<Configure>",
            resize_page,
        )

        # Bind through the toplevel with removable binding IDs rather than
        # bind_all().  _clear_content() and destroy() explicitly remove
        # these callbacks before the canvas is destroyed.
        self._bind_patient_explorer_mousewheel(canvas)

        navigation = ttk.Frame(
            page
        )
        navigation.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 10),
        )

        ttk.Button(
            navigation,
            text="Back",
            command=(
                self.on_back
                if external_entry
                and self.on_back is not None
                else self._show_home
            ),
        ).pack(
            side="left",
        )

        self.explorer = PatientExplorer(
            page,
            repository=self.repository,
            site_id_getter=lambda: self.site_id,
            on_open_record=self._open_record,
            on_open_clinical=self._open_clinical_record,
            on_add_clinical=self._add_clinical_assessment,
            on_upload_clinical=self._upload_clinical_assessments,
            on_add_surgical=self._add_surgical_record,
            on_upload_surgical=self._upload_surgical_records,
            on_add_patient=self._add_new_patient,
        )
        self.explorer.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        self.current_view = scroll_container

    def _show_batch_import(self):
        self._clear_content()

        self.current_view = MetadataBatchImport(
            self.content,
            dictionary=self.dictionary,
            repository=self.repository,
            metadata_store=self.metadata_store,
            site_id_getter=lambda: self.site_id,
            on_back=self._show_home,
        )
        self.current_view.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

    def _selected_patient_id(self):
        if self.explorer is None:
            return ""

        patient_id = self.explorer.loaded_patient_id()

        if patient_id:
            return patient_id

        return self.explorer.current_patient_id()

    def _change_site(self):
        value = simpledialog.askstring(
            "Change CoCANoT Site",
            "Enter the Site ID for this local installation.",
            initialvalue=self.site_id,
            parent=self,
        )

        if value is None:
            return

        try:
            self.site_id = self.metadata_store.set_site_id(
                value
            )
        except ValueError as exc:
            messagebox.showerror(
                "Site ID required",
                str(exc),
                parent=self,
            )
            return

        self.site_var.set(
            f"Site: {self.site_id}"
        )
        self._show_home()

    def _add_new_patient(self):
        patient_id = (
            simpledialog.askstring(
                "Add New CoCANoT Patient",
                "Enter the new CoCANoT Patient ID.",
                parent=self,
            )
            or ""
        ).strip()

        if not patient_id:
            return

        if self.repository.patient_exists(
            self.site_id,
            patient_id,
        ):
            messagebox.showinfo(
                "Patient already exists",
                (
                    f"Patient {patient_id} already exists "
                    f"for site {self.site_id}."
                ),
                parent=self,
            )
            self._refresh_patient(
                patient_id
            )
            return

        self._choose_new_patient_clinical_method(
            patient_id
        )

    def _choose_new_patient_clinical_method(
        self,
        patient_id,
    ):
        dialog = tk.Toplevel(
            self
        )
        dialog.title(
            "Clinical Assessment"
        )
        dialog.transient(
            self
        )
        dialog.grab_set()
        dialog.resizable(
            False,
            False,
        )

        frame = ttk.Frame(
            dialog,
            padding=18,
        )
        frame.pack(
            fill="both",
            expand=True,
        )

        ttk.Label(
            frame,
            text=f"Patient {patient_id}",
            font=("", 13, "bold"),
        ).pack(
            anchor="w",
        )

        ttk.Label(
            frame,
            text=(
                "A Clinical Assessment is required before "
                "the patient is added. Enter the metadata "
                "manually or upload it from a CSV/XLSX file."
            ),
            wraplength=430,
        ).pack(
            anchor="w",
            pady=(6, 16),
        )

        buttons = ttk.Frame(
            frame
        )
        buttons.pack(
            fill="x",
        )

        ttk.Button(
            buttons,
            text="Enter Clinical Assessment",
            command=lambda: self._enter_new_patient_clinical(
                dialog,
                patient_id,
            ),
        ).pack(
            side="left",
            padx=(0, 8),
        )

        ttk.Button(
            buttons,
            text="Upload Clinical Metadata",
            command=lambda: self._upload_new_patient_clinical(
                dialog,
                patient_id,
            ),
        ).pack(
            side="left",
            padx=(0, 8),
        )

        ttk.Button(
            buttons,
            text="Cancel",
            command=dialog.destroy,
        ).pack(
            side="right",
        )

    def _enter_new_patient_clinical(
        self,
        choice_dialog,
        patient_id,
    ):
        choice_dialog.destroy()

        assessment_id = reconcile_clinical_assessment(
            self,
            self.dictionary,
            self.metadata_store,
            self.site_id,
            patient_id,
        )

        if assessment_id is None:
            return

        self._finish_new_patient(
            patient_id,
            assessment_id,
        )

    def _upload_new_patient_clinical(
        self,
        choice_dialog,
        patient_id,
    ):
        choice_dialog.destroy()

        imported = import_clinical_file(
            self,
            self.dictionary,
            self.metadata_store,
            self.site_id,
            {patient_id},
        )

        assessment_id = (
            imported.get(patient_id)
            if imported
            else None
        )

        if not assessment_id:
            return

        self._finish_new_patient(
            patient_id,
            assessment_id,
        )

    def _finish_new_patient(
        self,
        patient_id,
        assessment_id,
    ):
        self.repository.create_patient(
            self.site_id,
            patient_id,
        )

        self._refresh_patient(
            patient_id
        )

        messagebox.showinfo(
            "Patient added",
            (
                f"Patient {patient_id} was added to site "
                f"{self.site_id} with Clinical Assessment "
                f"{assessment_id}."
            ),
            parent=self,
        )

    def _add_clinical_assessment(self):
        patient_id = self._selected_patient_id()

        if not patient_id:
            messagebox.showwarning(
                "Patient Required",
                (
                    "Select a CoCANoT Patient ID before "
                    "adding a Clinical Assessment."
                ),
                parent=self,
            )
            return

        assessment_id = reconcile_clinical_assessment(
            self,
            self.dictionary,
            self.metadata_store,
            self.site_id,
            patient_id,
        )

        if assessment_id is None:
            return

        self._refresh_patient(
            patient_id
        )

    def _upload_clinical_assessments(self):
        patient_id = self._selected_patient_id()

        if not patient_id:
            messagebox.showwarning(
                "Patient Required",
                (
                    "Select a CoCANoT Patient ID before "
                    "uploading Clinical Assessments."
                ),
                parent=self,
            )
            return

        imported = import_clinical_file(
            self,
            self.dictionary,
            self.metadata_store,
            self.site_id,
            {patient_id},
        )

        if not imported:
            return

        self._refresh_patient(
            patient_id
        )

        assessment_id = imported.get(
            patient_id
        )

        if assessment_id:
            messagebox.showinfo(
                "Clinical metadata imported",
                (
                    f"Clinical Assessment metadata for Patient "
                    f"{patient_id} was imported successfully.\n\n"
                    f"Current Clinical Assessment: {assessment_id}"
                ),
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Clinical metadata imported",
                "The selected Clinical Assessment records were imported.",
                parent=self,
            )

    def _add_surgical_record(self):
        patient_id = self._selected_patient_id()

        if not patient_id:
            patient_id = (
                simpledialog.askstring(
                    "CoCANoT Patient ID",
                    "Enter the patient ID for the new Surgical record.",
                    parent=self,
                )
                or ""
            ).strip()

        if not patient_id:
            return

        MetadataEditor(
            self,
            dictionary=self.dictionary,
            repository=self.repository,
            site_id=self.site_id,
            table_name="Surgical",
            patient_id=patient_id,
            on_saved=lambda _record: self._refresh_patient(
                patient_id
            ),
        )

    def _upload_surgical_records(self):
        patient_id = self._selected_patient_id()

        if not patient_id:
            messagebox.showwarning(
                "Patient Required",
                (
                    "Select a CoCANoT Patient ID before "
                    "uploading Surgical metadata."
                ),
                parent=self,
            )
            return

        result = import_surgical_file(
            self,
            self.dictionary,
            self.repository,
            self.metadata_store,
            self.site_id,
            expected_patient_id=patient_id,
        )

        if result is None:
            return

        self._refresh_patient(
            patient_id
        )

        imported = result["imported"]
        updated = result["updated"]
        new_count = imported - updated

        messagebox.showinfo(
            "Surgical metadata imported",
            (
                f"Imported {imported} Surgical record"
                f"{'' if imported == 1 else 's'}.\n\n"
                f"New: {new_count}\n"
                f"Updated existing: {updated}"
            ),
            parent=self,
        )

    def _open_clinical_record(
        self,
        record,
    ):
        latest = self.metadata_store.latest_clinical_assessment(
            self.site_id,
            record["patient_id"],
        )

        editable = (
            latest is not None
            and latest["assessment_id"]
            == record["record_id"]
        )

        ClinicalAssessmentReview(
            self,
            dictionary=self.dictionary,
            record=record,
            editable=editable,
            on_edit=self._edit_clinical_record,
        )

    def _edit_clinical_record(
        self,
        record,
    ):
        patient_id = record[
            "patient_id"
        ]

        editor = ClinicalAssessmentDialog(
            self,
            self.dictionary,
            patient_id,
            existing_metadata=record[
                "metadata"
            ],
        )

        self.wait_window(
            editor
        )

        if editor.result is None:
            return

        tracked_fields = tracked_clinical_fields(
            self.dictionary
        )

        saved = self.metadata_store.save_clinical_assessment(
            self.site_id,
            patient_id,
            editor.result,
            tracked_fields,
        )

        if saved["action"] == "created_new_assessment":
            messagebox.showinfo(
                "New Clinical Assessment created",
                (
                    f"{patient_id} was assigned "
                    f"{saved['assessment_id']} because one or more "
                    "tracked clinical fields changed."
                ),
                parent=self,
            )
        elif saved["action"] == "corrected_existing":
            messagebox.showinfo(
                "Clinical Assessment updated",
                (
                    f"Changes were saved to "
                    f"{saved['assessment_id']}."
                ),
                parent=self,
            )

        self._refresh_patient(
            patient_id
        )

    def _open_record(
        self,
        table_name,
        record,
    ):
        MetadataEditor(
            self,
            dictionary=self.dictionary,
            repository=self.repository,
            site_id=self.site_id,
            table_name=table_name,
            record=record,
            on_saved=lambda _record: self._refresh_patient(
                record["patient_id"]
            ),
        )

    def _refresh_patient(
        self,
        patient_id,
    ):
        if self.explorer is None:
            return

        self.explorer.refresh_patient_ids(
            patient_id
        )
        self.explorer.patient_var.set(
            patient_id
        )
        self.explorer.load_patient()


def main():
    root = tk.Tk()
    root.title("CoCANoT Metadata Management")
    root.geometry("1250x900")
    root.minsize(950, 700)

    initial_view = (
        "patient_explorer"
        if "--patient-explorer" in sys.argv
        else "home"
    )

    app = MetadataDashboard(
        root,
        initial_view=initial_view,
    )
    app.pack(fill="both", expand=True)

    root.mainloop()


if __name__ == "__main__":
    main()
