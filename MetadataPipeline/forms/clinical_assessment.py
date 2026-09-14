"""Clinical Assessment entry and reconciliation for local dashboards."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

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


class ClinicalAssessmentDialog(tk.Toplevel):
    """Dictionary-driven Clinical Assessment editor."""

    def __init__(
        self,
        parent,
        dictionary,
        patient_id,
        existing_metadata=None,
    ):
        super().__init__(parent)
        self.dictionary = dictionary
        self.patient_id = str(patient_id).strip()
        self.existing_metadata = dict(
            existing_metadata or {}
        )
        self.rules = dictionary["tables"]["Clinical"][
            "fields"
        ]
        self.validator = MetadataValidator(dictionary)
        self.controls = {}
        self.result = None

        self.title(
            f"Clinical Assessment — {self.patient_id}"
        )
        self.geometry("1000x820")
        self.minsize(820, 650)
        self.transient(parent)
        self.grab_set()

        self._build_interface()
        self._populate_existing()
        self._refresh_conditional_fields()

    def _build_interface(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        ttk.Label(
            root,
            text=f"Clinical Assessment for {self.patient_id}",
            font=("", 17, "bold"),
        ).grid(row=0, column=0, sticky="w")

        shell = ttk.Frame(root)
        shell.grid(
            row=1,
            column=0,
            sticky="nsew",
            pady=(10, 0),
        )
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        canvas = tk.Canvas(
            shell,
            highlightthickness=0,
        )
        canvas.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(
            shell,
            orient="vertical",
            command=canvas.yview,
        )
        scroll.grid(row=0, column=1, sticky="ns")
        canvas.configure(
            yscrollcommand=scroll.set
        )

        body = ttk.Frame(canvas)
        body_id = canvas.create_window(
            (0, 0),
            window=body,
            anchor="nw",
        )
        body.columnconfigure(0, weight=1)

        body.bind(
            "<Configure>",
            lambda _event: canvas.configure(
                scrollregion=canvas.bbox("all")
            ),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(
                body_id,
                width=event.width,
            ),
        )

        row_index = 0

        for rule in self.rules:
            field_name = rule["field_name"]

            if field_name in {
                "CoCANoT Patient ID",
                "Clinical Assessment ID",
            }:
                continue

            frame = ttk.Frame(body)
            frame.grid(
                row=row_index,
                column=0,
                sticky="ew",
                pady=4,
            )
            frame.columnconfigure(1, weight=1)
            row_index += 1

            if rule["required"]:
                marker = " *"
            elif rule.get("required_if_field"):
                marker = " * when applicable"
            else:
                marker = ""

            ttk.Label(
                frame,
                text=str(rule["ui_prompt"]) + marker,
                wraplength=360,
            ).grid(
                row=0,
                column=0,
                sticky="nw",
                padx=(0, 8),
            )

            help_text = str(
                rule.get("help_text") or ""
            ).strip()

            if help_text:
                ttk.Button(
                    frame,
                    text="?",
                    width=3,
                    command=lambda item=rule: (
                        messagebox.showinfo(
                            str(item["field_name"]),
                            str(item["help_text"]),
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
                "frame": frame,
                "rule": rule,
            }

            input_type = rule["input_type"]

            if input_type in {
                "identifier",
                "free_text",
                "numeric",
            }:
                variable = tk.StringVar()

                widget = ttk.Entry(
                    frame,
                    textvariable=variable,
                )
                widget.grid(
                    row=0,
                    column=1,
                    sticky="ew",
                )

                variable.trace_add(
                    "write",
                    lambda *_args: (
                        self._refresh_conditional_fields()
                    ),
                )

                control["variable"] = variable
                control["widget"] = widget

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
                    lambda _event: (
                        self._refresh_conditional_fields()
                    ),
                )

                control["variable"] = variable
                control["widget"] = widget

            elif input_type == "multi_select":
                container = ttk.Frame(
                    frame
                )
                container.grid(
                    row=0,
                    column=1,
                    sticky="ew",
                )
                container.columnconfigure(
                    0,
                    weight=1,
                )

                values = list(
                    rule.get(
                        "allowed_values",
                        [],
                    )
                )

                listbox = tk.Listbox(
                    container,
                    selectmode="extended",
                    exportselection=False,
                    height=min(
                        max(
                            len(values),
                            4,
                        ),
                        7,
                    ),
                )
                listbox.grid(
                    row=0,
                    column=0,
                    sticky="ew",
                )

                for value in values:
                    listbox.insert(
                        "end",
                        value,
                    )

                listbox.bind(
                    "<<ListboxSelect>>",
                    lambda _event: (
                        self._refresh_conditional_fields()
                    ),
                )

                bar = ttk.Scrollbar(
                    container,
                    orient="vertical",
                    command=listbox.yview,
                )
                bar.grid(
                    row=0,
                    column=1,
                    sticky="ns",
                )

                listbox.configure(
                    yscrollcommand=bar.set,
                )

                control["widget"] = listbox

            self.controls[
                field_name
            ] = control

        actions = ttk.Frame(root)
        actions.grid(
            row=2,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )

        ttk.Button(
            actions,
            text="Cancel",
            command=self.destroy,
        ).pack(
            side="right"
        )

        ttk.Button(
            actions,
            text="Save Clinical Assessment",
            command=self._save,
        ).pack(
            side="right",
            padx=(0, 8),
        )

    def _populate_existing(self):
        for (
            field_name,
            control,
        ) in self.controls.items():
            value = self.existing_metadata.get(
                field_name
            )

            if value is None:
                continue

            rule = control["rule"]

            if (
                rule["input_type"]
                == "multi_select"
            ):
                listbox = control[
                    "widget"
                ]

                values = (
                    value
                    if type(value) is list
                    else [value]
                )

                for index in range(
                    listbox.size()
                ):
                    if (
                        listbox.get(index)
                        in values
                    ):
                        listbox.selection_set(
                            index
                        )

            else:
                control[
                    "variable"
                ].set(
                    str(value)
                )

    def _current_metadata(self):
        metadata = {
            "CoCANoT Patient ID": (
                self.patient_id
            ),
            "Clinical Assessment ID": (
                "PENDING"
            ),
        }

        for rule in self.rules:
            field_name = rule[
                "field_name"
            ]

            if field_name in {
                "CoCANoT Patient ID",
                "Clinical Assessment ID",
            }:
                continue

            control = self.controls[
                field_name
            ]

            if (
                rule["input_type"]
                == "multi_select"
            ):
                listbox = control[
                    "widget"
                ]

                metadata[
                    field_name
                ] = [
                    str(
                        listbox.get(
                            index
                        )
                    )
                    for index
                    in listbox.curselection()
                ]

            else:
                metadata[
                    field_name
                ] = (
                    control[
                        "variable"
                    ]
                    .get()
                    .strip()
                )

        return metadata

    def _refresh_conditional_fields(self):
        """
        Show conditional fields when their rule applies.

        If a conditional field no longer applies, clear its previous
        value before hiding it. This prevents hidden values from being
        included in validation or stored metadata.
        """
        metadata = self._current_metadata()

        for (
            field_name,
            control,
        ) in self.controls.items():
            rule = control["rule"]
            parent = rule.get(
                "required_if_field"
            )
            frame = control[
                "frame"
            ]

            if not parent:
                frame.grid()
                continue

            applies = condition_matches(
                metadata,
                parent,
                rule[
                    "required_if_operator"
                ],
                rule[
                    "required_if_value"
                ],
            )

            if applies:
                frame.grid()
                continue

            self._clear_control(
                control
            )
            frame.grid_remove()

    @staticmethod
    def _clear_control(
        control,
    ):
        """
        Clear a conditional field when it becomes hidden.

        This handles both regular text/select fields and multiselect
        listboxes.
        """
        rule = control[
            "rule"
        ]

        if (
            rule["input_type"]
            == "multi_select"
        ):
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
        ):
            variable.set(
                ""
            )

    def _save(self):
        metadata = self._current_metadata()

        validation = (
            self.validator.validate_record(
                "Clinical",
                metadata,
            )
        )

        problems = [
            result
            for result
            in validation[
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
                "Clinical metadata needs attention",
                "\n".join(
                    (
                        f"{item['field_name']}: "
                        f"{item['message']}"
                    )
                    for item
                    in problems[:12]
                ),
                parent=self,
            )
            return

        manual_fields = [
            result[
                "field_name"
            ]
            for result
            in validation[
                "results"
            ]
            if result[
                "status"
            ] == "manual_review"
        ]

        if manual_fields:
            lines = [
                (
                    f"{field_name}: "
                    f"{metadata.get(field_name) or '(blank)'}"
                )
                for field_name
                in manual_fields
                if metadata.get(
                    field_name
                )
            ]

            if lines:
                confirmed = (
                    messagebox.askyesno(
                        "Confirm free-text clinical metadata",
                        (
                            "Please confirm these free-text values "
                            "do not contain PHI:\n\n"
                            + "\n\n".join(
                                lines
                            )
                        ),
                        parent=self,
                    )
                )

                if not confirmed:
                    return

        metadata.pop(
            "Clinical Assessment ID",
            None,
        )

        self.result = metadata
        self.destroy()


class ExistingClinicalAssessmentDialog(
    tk.Toplevel
):
    """Show the latest stored assessment and let the user keep or edit it."""

    def __init__(
        self,
        parent,
        patient_id,
        assessment,
        tracked_fields,
        return_to="Metadata Review",
    ):
        super().__init__(parent)
        self.result = None
        self.return_to = str(
            return_to
            or "Metadata Review"
        ).strip()

        self.title(
            f"Clinical Assessment — {patient_id}"
        )
        self.geometry("820x620")
        self.minsize(700, 520)
        self.transient(parent)
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
            text=(
                f"Previous clinical data found for "
                f"{patient_id}"
            ),
            font=("", 16, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            root,
            text=(
                f"Latest Clinical Assessment: "
                f"{assessment['assessment_id']}\n"
                "Review the tracked clinical fields below. "
                "Keep this assessment if they have not changed."
            ),
            wraplength=760,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(6, 10),
        )

        summary = tk.Text(
            root,
            wrap="word",
            state="normal",
        )
        summary.grid(
            row=2,
            column=0,
            sticky="nsew",
        )

        metadata = assessment[
            "metadata"
        ]
        lines = []

        for field_name in tracked_fields:
            value = metadata.get(
                field_name
            )

            if type(value) is list:
                shown = ", ".join(
                    str(item)
                    for item in value
                )

            elif value in (
                None,
                "",
            ):
                shown = "(blank)"

            else:
                shown = str(
                    value
                )

            lines.append(
                f"{field_name}\n  {shown}\n"
            )

        summary.insert(
            "1.0",
            "\n".join(lines),
        )
        summary.configure(
            state="disabled"
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
            text=f"Back to {self.return_to}",
            command=lambda: self._finish(
                "back"
            ),
        ).pack(
            side="right"
        )

        ttk.Button(
            actions,
            text="Upload Clinical Metadata",
            command=lambda: self._finish(
                "upload"
            ),
        ).pack(
            side="right",
            padx=(0, 8),
        )

        ttk.Button(
            actions,
            text="Edit Existing Values",
            command=lambda: self._finish(
                "edit"
            ),
        ).pack(
            side="right",
            padx=(0, 8),
        )

        ttk.Button(
            actions,
            text=(
                f"No Changes — Keep "
                f"{assessment['assessment_id']}"
            ),
            command=lambda: self._finish(
                "keep"
            ),
        ).pack(
            side="right",
            padx=(0, 8),
        )

    def _finish(
        self,
        value,
    ):
        self.result = value
        self.destroy()


def tracked_clinical_fields(
    dictionary,
):
    return [
        rule["field_name"]
        for rule
        in dictionary[
            "tables"
        ][
            "Clinical"
        ][
            "fields"
        ]
        if rule.get(
            "creates_new_clinical_assessment_if_changed"
        )
    ]


def reconcile_clinical_assessment(
    parent,
    dictionary,
    store,
    site_id,
    patient_id,
    return_to="Metadata Review",
):
    """Return the Clinical Assessment ID to attach to one patient."""

    tracked_fields = (
        tracked_clinical_fields(
            dictionary
        )
    )

    while True:
        latest = (
            store.latest_clinical_assessment(
                site_id,
                patient_id,
            )
        )

        if latest is None:
            dialog = (
                ClinicalAssessmentDialog(
                    parent,
                    dictionary,
                    patient_id,
                )
            )

            parent.wait_window(
                dialog
            )

            if dialog.result is None:
                return None

            saved = (
                store.save_clinical_assessment(
                    site_id,
                    patient_id,
                    dialog.result,
                    tracked_fields,
                )
            )

            return saved[
                "assessment_id"
            ]

        choice = (
            ExistingClinicalAssessmentDialog(
                parent,
                patient_id,
                latest,
                tracked_fields,
                return_to=return_to,
            )
        )

        parent.wait_window(
            choice
        )

        if choice.result is None:
            return None

        if choice.result == "back":
            return "back"

        if choice.result == "keep":
            return latest[
                "assessment_id"
            ]

        if choice.result == "upload":
            imported = import_clinical_file(
                parent,
                dictionary,
                store,
                site_id,
                {
                    patient_id
                },
            )

            assessment_id = (
                imported.get(
                    patient_id
                )
                if imported
                else None
            )

            if assessment_id:
                return assessment_id

            continue

        editor = ClinicalAssessmentDialog(
            parent,
            dictionary,
            patient_id,
            existing_metadata=latest[
                "metadata"
            ],
        )

        parent.wait_window(
            editor
        )

        if editor.result is None:
            continue

        saved = store.save_clinical_assessment(
            site_id,
            patient_id,
            editor.result,
            tracked_fields,
        )

        action = saved[
            "action"
        ]

        if (
            action
            == "created_new_assessment"
        ):
            messagebox.showinfo(
                "New Clinical Assessment created",
                (
                    f"{patient_id} was assigned "
                    f"{saved['assessment_id']} because one or "
                    "more tracked clinical fields changed."
                ),
                parent=parent,
            )

        elif (
            action
            == "corrected_existing"
        ):
            messagebox.showinfo(
                "Clinical Assessment updated",
                (
                    f"Changes were saved to "
                    f"{saved['assessment_id']}. No tracked "
                    "clinical field changed, so a new "
                    "Clinical Assessment ID was not created."
                ),
                parent=parent,
            )

        return saved[
            "assessment_id"
        ]


def _display_value(
    value,
):
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


def _changed_fields(
    current,
    uploaded,
    rules,
):
    changed = []

    for rule in rules:
        field_name = rule[
            "field_name"
        ]

        if field_name in {
            "CoCANoT Patient ID",
            "Clinical Assessment ID",
        }:
            continue

        if (
            store_normalized(
                current.get(
                    field_name
                )
            )
            != store_normalized(
                uploaded.get(
                    field_name
                )
            )
        ):
            changed.append(
                field_name
            )

    return changed


def store_normalized(
    value,
):
    if type(value) is list:
        return sorted(
            [
                store_normalized(
                    item
                )
                for item in value
            ],
            key=lambda item: str(
                item
            ),
        )

    if type(value) is dict:
        return {
            key: store_normalized(
                item
            )
            for key, item
            in sorted(
                value.items()
            )
        }

    if type(value) is str:
        return value.strip()

    return value


class ClinicalChangeReviewDialog(
    tk.Toplevel
):
    """Scrollable comparison of uploaded versus existing Clinical metadata."""

    def __init__(
        self,
        parent,
        row,
    ):
        super().__init__(
            parent
        )
        self.row = row

        patient_id = row[
            "patient_id"
        ]
        latest = row.get(
            "latest"
        )

        self.title(
            f"Clinical Metadata Changes — {patient_id}"
        )
        self.geometry(
            "820x680"
        )
        self.minsize(
            680,
            520,
        )
        self.transient(
            parent
        )
        self.grab_set()

        self._build_interface()

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

        patient_id = self.row[
            "patient_id"
        ]
        latest = self.row.get(
            "latest"
        )

        ttk.Label(
            root,
            text=(
                f"Clinical Metadata — "
                f"Patient {patient_id}"
            ),
            font=("", 17, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        if latest is None:
            intro = (
                "No existing Clinical Assessment was found "
                f"for Patient {patient_id}. The uploaded values "
                f"below will create {self.row['result_id']}."
            )

        else:
            intro = (
                f"Latest Clinical Assessment: "
                f"{latest['assessment_id']}. "
                "The values below show what changed in the upload."
            )

        ttk.Label(
            root,
            text=intro,
            wraplength=760,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(5, 10),
        )

        shell = ttk.Frame(
            root
        )
        shell.grid(
            row=2,
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

        self.body = ttk.Frame(
            self.canvas
        )

        self.body_id = (
            self.canvas.create_window(
                (0, 0),
                window=self.body,
                anchor="nw",
            )
        )

        self.body.columnconfigure(
            0,
            weight=1,
        )

        self.body.bind(
            "<Configure>",
            lambda _event: (
                self.canvas.configure(
                    scrollregion=(
                        self.canvas.bbox(
                            "all"
                        )
                    )
                )
            ),
        )

        self.canvas.bind(
            "<Configure>",
            lambda event: (
                self.canvas.itemconfigure(
                    self.body_id,
                    width=event.width,
                )
            ),
        )

        self.bind(
            "<MouseWheel>",
            self._scroll_with_wheel,
            add="+",
        )
        self.bind(
            "<Button-4>",
            self._scroll_with_wheel,
            add="+",
        )
        self.bind(
            "<Button-5>",
            self._scroll_with_wheel,
            add="+",
        )

        self._populate_changes()

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
            text="Close",
            command=self.destroy,
        ).pack(
            side="right"
        )

    def _populate_changes(
        self,
    ):
        current = (
            self.row.get(
                "current"
            )
            or {}
        )

        uploaded = self.row[
            "record"
        ]
        changed_fields = self.row[
            "changed_fields"
        ]
        latest = self.row.get(
            "latest"
        )

        if latest is None:
            fields = [
                field_name
                for (
                    field_name,
                    value,
                ) in uploaded.items()
                if field_name not in {
                    "CoCANoT Patient ID",
                    "Clinical Assessment ID",
                }
                and value not in (
                    None,
                    "",
                    [],
                )
            ]

        else:
            fields = changed_fields

        if not fields:
            ttk.Label(
                self.body,
                text=(
                    "No clinical values changed."
                ),
            ).grid(
                row=0,
                column=0,
                sticky="w",
                pady=6,
            )
            return

        for (
            index,
            field_name,
        ) in enumerate(
            fields
        ):
            card = ttk.Frame(
                self.body,
                padding=(8, 8),
            )
            card.grid(
                row=index,
                column=0,
                sticky="ew",
                pady=(0, 6),
            )
            card.columnconfigure(
                0,
                weight=1,
            )

            ttk.Label(
                card,
                text=field_name,
                font=("", 11, "bold"),
                wraplength=720,
            ).grid(
                row=0,
                column=0,
                sticky="w",
            )

            if latest is not None:
                ttk.Label(
                    card,
                    text=(
                        "Existing: "
                        + _display_value(
                            current.get(
                                field_name
                            )
                        )
                    ),
                    wraplength=720,
                ).grid(
                    row=1,
                    column=0,
                    sticky="w",
                    pady=(3, 0),
                )

                uploaded_row = 2

            else:
                uploaded_row = 1

            ttk.Label(
                card,
                text=(
                    "Uploaded: "
                    + _display_value(
                        uploaded.get(
                            field_name
                        )
                    )
                ),
                wraplength=720,
            ).grid(
                row=uploaded_row,
                column=0,
                sticky="w",
                pady=(3, 0),
            )

    def _scroll_with_wheel(
        self,
        event,
    ):
        pointer = (
            self.winfo_containing(
                self.winfo_pointerx(),
                self.winfo_pointery(),
            )
        )

        if not self._is_in_scroll_area(
            pointer
        ):
            return None

        if getattr(
            event,
            "num",
            None,
        ) == 4:
            units = -3

        elif getattr(
            event,
            "num",
            None,
        ) == 5:
            units = 3

        else:
            delta = getattr(
                event,
                "delta",
                0,
            )

            if delta == 0:
                return None

            if abs(delta) >= 120:
                units = (
                    -int(
                        delta / 120
                    )
                    * 3
                )

            else:
                units = (
                    -1
                    if delta > 0
                    else 1
                )

        self.canvas.yview_scroll(
            units,
            "units",
        )

        return "break"

    def _is_in_scroll_area(
        self,
        widget,
    ):
        current = widget

        while current is not None:
            if current in {
                self.canvas,
                self.body,
            }:
                return True

            parent_name = (
                current.winfo_parent()
            )

            if not parent_name:
                break

            try:
                current = (
                    current.nametowidget(
                        parent_name
                    )
                )
            except KeyError:
                break

        return False


class ClinicalUploadReviewDialog(
    tk.Toplevel
):
    """Preview selected longitudinal Clinical Assessments before import."""

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
            "Review Clinical Metadata Upload"
        )
        self.geometry(
            "1100x700"
        )
        self.minsize(
            900,
            560,
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
            text=(
                "Review Clinical Metadata Upload"
            ),
            font=("", 17, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            root,
            text=(
                "Nothing has been saved yet. The selected Clinical "
                "Assessments are shown below in longitudinal order. "
                "Current is the highest Clinical Assessment ID for "
                "this patient; earlier assessments are Previous."
            ),
            wraplength=1020,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(5, 10),
        )

        columns = (
            "patient",
            "assessment",
            "status",
            "action",
        )

        tree = ttk.Treeview(
            root,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        tree.grid(
            row=2,
            column=0,
            sticky="nsew",
        )

        headings = {
            "patient": "Patient",
            "assessment": (
                "Clinical Assessment ID"
            ),
            "status": "Status",
            "action": "Proposed Action",
        }

        widths = {
            "patient": 170,
            "assessment": 210,
            "status": 140,
            "action": 500,
        }

        for column in columns:
            tree.heading(
                column,
                text=headings[
                    column
                ],
            )
            tree.column(
                column,
                width=widths[
                    column
                ],
                anchor="w",
            )

        for (
            index,
            row,
        ) in enumerate(
            rows
        ):
            tree.insert(
                "",
                "end",
                iid=str(
                    index
                ),
                values=(
                    row[
                        "patient_id"
                    ],
                    row[
                        "assessment_id"
                    ],
                    row[
                        "status"
                    ],
                    row[
                        "summary"
                    ],
                ),
            )

        tree.bind(
            "<Double-1>",
            lambda _event: (
                self._show_details(
                    tree
                )
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
            side="right"
        )

        ttk.Button(
            actions,
            text="Confirm Import",
            command=self._confirm,
        ).pack(
            side="right",
            padx=(0, 8),
        )

        ttk.Button(
            actions,
            text="View Selected Changes",
            command=lambda: (
                self._show_details(
                    tree
                )
            ),
        ).pack(
            side="left"
        )

    def _show_details(
        self,
        tree,
    ):
        selected = (
            tree.selection()
        )

        if not selected:
            return

        row = self.rows[
            int(
                selected[0]
            )
        ]

        ClinicalChangeReviewDialog(
            self,
            row,
        )

    def _confirm(
        self,
    ):
        self.result = True
        self.destroy()


def _prepare_uploaded_clinical_rows(
    dictionary,
    store,
    site_id,
    loaded_rows,
    expected_patient_ids,
):
    validator = (
        MetadataValidator(
            dictionary
        )
    )

    tracked_fields = (
        tracked_clinical_fields(
            dictionary
        )
    )

    rules = dictionary[
        "tables"
    ][
        "Clinical"
    ][
        "fields"
    ]

    prepared = []

    for (
        row_number,
        uploaded,
    ) in enumerate(
        loaded_rows,
        start=2,
    ):
        record = normalize_record(
            dictionary,
            "Clinical",
            uploaded,
        )

        patient_id = str(
            record.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()

        if not patient_id:
            raise ValueError(
                f"Clinical upload row "
                f"{row_number} is missing "
                "CoCANoT Patient ID."
            )

        if (
            patient_id
            not in expected_patient_ids
        ):
            continue

        record[
            "Clinical Assessment ID"
        ] = "PENDING"

        validation = (
            validator.validate_record(
                "Clinical",
                record,
            )
        )

        problems = [
            result
            for result
            in validation[
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
            raise ValueError(
                f"Clinical upload row "
                f"{row_number} for "
                f"{patient_id} is invalid: "
                + "; ".join(
                    item[
                        "message"
                    ]
                    for item
                    in problems[:8]
                )
            )

        manual_fields = [
            result[
                "field_name"
            ]
            for result
            in validation[
                "results"
            ]
            if result[
                "status"
            ] == "manual_review"
            and record.get(
                result[
                    "field_name"
                ]
            )
        ]

        record.pop(
            "Clinical Assessment ID",
            None,
        )

        latest = (
            store.latest_clinical_assessment(
                site_id,
                patient_id,
            )
        )

        current = (
            dict(
                latest[
                    "metadata"
                ]
            )
            if latest
            is not None
            else {}
        )

        changed = _changed_fields(
            current,
            record,
            rules,
        )

        tracked_changed = [
            field_name
            for field_name
            in changed
            if field_name
            in tracked_fields
        ]

        if latest is None:
            result_id = "CA-001"
            summary = (
                "Create first Clinical Assessment"
            )

        elif tracked_changed:
            result_id = (
                f"CA-"
                f"{int(latest['assessment_number']) + 1:03d}"
            )

            summary = (
                "Create new assessment — tracked change: "
                + ", ".join(
                    tracked_changed
                )
            )

        elif changed:
            result_id = (
                latest[
                    "assessment_id"
                ]
            )

            summary = (
                "Update existing assessment — "
                "no tracked field changed"
            )

        else:
            result_id = (
                latest[
                    "assessment_id"
                ]
            )

            summary = (
                "No changes — keep existing assessment"
            )

        prepared.append(
            {
                "patient_id": (
                    patient_id
                ),
                "record": (
                    record
                ),
                "latest": (
                    latest
                ),
                "current": (
                    current
                ),
                "existing_id": (
                    latest[
                        "assessment_id"
                    ]
                    if latest
                    is not None
                    else ""
                ),
                "result_id": (
                    result_id
                ),
                "summary": (
                    summary
                ),
                "changed_fields": (
                    changed
                ),
                "tracked_changed_fields": (
                    tracked_changed
                ),
                "manual_fields": (
                    manual_fields
                ),
            }
        )

    return prepared


def _clinical_assessment_number(
    assessment_id,
):
    value = str(
        assessment_id
        or ""
    ).strip().upper()

    if not value.startswith(
        "CA-"
    ):
        return None

    number = value[3:]

    if not number.isdigit():
        return None

    parsed = int(
        number
    )

    if parsed < 1:
        return None

    if (
        value
        != f"CA-{parsed:03d}"
    ):
        return None

    return parsed


def _selected_clinical_duplicate_errors(
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

        assessment_id = str(
            record.get(
                "Clinical Assessment ID"
            )
            or ""
        ).strip().upper()

        key = (
            patient_id,
            assessment_id,
        )

        if key in seen:
            errors.append(
                f"{assessment_id} appears more than once "
                f"for Patient {patient_id} in the selected rows."
            )
            continue

        seen.add(
            key
        )

    return errors


def _clinical_existing_conflicts(
    store,
    site_id,
    records,
    rules,
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

        assessment_id = str(
            record.get(
                "Clinical Assessment ID"
            )
            or ""
        ).strip().upper()

        existing = (
            store.clinical_assessment(
                site_id,
                patient_id,
                assessment_id,
            )
        )

        if existing is None:
            continue

        uploaded = record

        uploaded[
            "CoCANoT Patient ID"
        ] = patient_id

        uploaded[
            "Clinical Assessment ID"
        ] = assessment_id

        existing_metadata = dict(
            existing[
                "metadata"
            ]
        )

        changed = _changed_fields(
            existing_metadata,
            uploaded,
            rules,
        )

        key = (
            patient_id,
            assessment_id,
        )

        if not changed:
            resolutions[
                key
            ] = "keep"
            continue

        conflicts.append(
            {
                "patient_id": (
                    patient_id
                ),
                "assessment_id": (
                    assessment_id
                ),
                "existing": (
                    existing
                ),
                "uploaded": (
                    uploaded
                ),
                "changed_fields": (
                    changed
                ),
            }
        )

    return (
        conflicts,
        resolutions,
    )


class ClinicalDuplicateComparisonDialog(
    tk.Toplevel
):
    """Compare stored and uploaded Clinical Assessments side by side."""

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

        self.title(
            "Resolve Existing Clinical Assessments"
        )
        self.geometry(
            "1180x780"
        )
        self.minsize(
            980,
            650,
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
            text=(
                "Resolve Existing Clinical Assessments"
            ),
            font=("", 17, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            root,
            text=(
                "Each conflict is shown field by field in Clinical "
                "dictionary order. The stored assessment is on the left "
                "and the uploaded assessment is on the right. You may edit "
                "the uploaded values before choosing which version to keep."
            ),
            wraplength=1080,
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
            side="right"
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
            "assessment",
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
            "assessment": (
                "Clinical Assessment ID"
            ),
            "differences": (
                "Changed Fields"
            ),
            "decision": (
                "Decision"
            ),
        }

        widths = {
            "patient": 130,
            "assessment": 190,
            "differences": 500,
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
            text=(
                "Select a conflict to compare"
            ),
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
            lambda _event: (
                self.canvas.configure(
                    scrollregion=(
                        self.canvas.bbox(
                            "all"
                        )
                    )
                )
            ),
        )

        self.canvas.bind(
            "<Configure>",
            lambda event: (
                self.canvas.itemconfigure(
                    self.comparison_window,
                    width=event.width,
                )
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
            command=lambda: (
                self._set_decision(
                    "keep"
                )
            ),
        ).pack(
            side="left"
        )

        ttk.Button(
            choice_bar,
            text="Use Uploaded Version",
            command=lambda: (
                self._set_decision(
                    "replace"
                )
            ),
        ).pack(
            side="left",
            padx=(8, 0),
        )

    def _refresh_table(
        self,
    ):
        current = (
            self.table.selection()
        )

        for item in (
            self.table.get_children()
        ):
            self.table.delete(
                item
            )

        for (
            index,
            conflict,
        ) in enumerate(
            self.conflicts
        ):
            key = (
                conflict[
                    "patient_id"
                ],
                conflict[
                    "assessment_id"
                ],
            )

            decision = (
                self.decisions.get(
                    key,
                    "Choose",
                )
            )

            if decision == "keep":
                shown_decision = (
                    "Keep Existing"
                )

            elif decision == "replace":
                shown_decision = (
                    "Use Uploaded"
                )

            else:
                shown_decision = (
                    "Choose"
                )

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
                        "assessment_id"
                    ],
                    ", ".join(
                        conflict[
                            "changed_fields"
                        ]
                    ),
                    shown_decision,
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
        selected = (
            self.table.selection()
        )

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
        self.selected_index = (
            index
        )
        self._build_field_comparison()

    def _build_field_comparison(
        self,
    ):
        for child in (
            self.comparison_body.winfo_children()
        ):
            child.destroy()

        self.upload_variables = {}

        if (
            self.selected_index
            is None
        ):
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
                f"Patient "
                f"{conflict['patient_id']} / "
                f"{conflict['assessment_id']}"
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

            ttk.Label(
                self.comparison_body,
                text=field_name,
                wraplength=260,
            ).grid(
                row=row_index,
                column=0,
                sticky="nw",
                padx=(0, 12),
                pady=5,
            )

            current_value = (
                _display_value(
                    existing.get(
                        field_name
                    )
                )
            )

            ttk.Label(
                self.comparison_body,
                text=current_value,
                wraplength=360,
            ).grid(
                row=row_index,
                column=1,
                sticky="nw",
                padx=(0, 12),
                pady=5,
            )

            self._add_uploaded_editor(
                field,
                uploaded,
                row_index,
            )

            row_index += 1

    def _add_uploaded_editor(
        self,
        field,
        uploaded,
        row_index,
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

        value = uploaded.get(
            field_name
        )

        if field_name in {
            "CoCANoT Patient ID",
            "Clinical Assessment ID",
        }:
            ttk.Label(
                self.comparison_body,
                text=_display_value(
                    value
                ),
                wraplength=360,
            ).grid(
                row=row_index,
                column=2,
                sticky="nw",
                pady=5,
            )
            return

        if (
            input_type
            == "single_select"
        ):
            variable = tk.StringVar(
                value=(
                    ""
                    if value
                    is None
                    else str(
                        value
                    )
                )
            )

            widget = ttk.Combobox(
                self.comparison_body,
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
                row=row_index,
                column=2,
                sticky="ew",
                pady=5,
            )

            self.upload_variables[
                field_name
            ] = (
                "single",
                variable,
            )

            return

        if (
            input_type
            == "multi_select"
        ):
            if type(value) is str:
                selected = [
                    item.strip()
                    for item
                    in value.split(
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
                self.comparison_body
            )
            container.grid(
                row=row_index,
                column=2,
                sticky="ew",
                pady=5,
            )

            variables = {}

            for option in field.get(
                "allowed_values",
                [],
            ):
                variable = (
                    tk.BooleanVar(
                        value=(
                            option
                            in selected
                        ),
                    )
                )

                variables[
                    option
                ] = variable

                ttk.Checkbutton(
                    container,
                    text=option,
                    variable=variable,
                ).pack(
                    anchor="w"
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
                if value
                is None
                else str(
                    value
                )
            )
        )

        widget = ttk.Entry(
            self.comparison_body,
            textvariable=variable,
        )
        widget.grid(
            row=row_index,
            column=2,
            sticky="ew",
            pady=5,
        )

        self.upload_variables[
            field_name
        ] = (
            "text",
            variable,
        )

    def _save_uploaded_values(
        self,
    ):
        if (
            self.selected_index
            is None
        ):
            return

        uploaded = self.conflicts[
            self.selected_index
        ][
            "uploaded"
        ]

        for (
            field_name,
            item,
        ) in self.upload_variables.items():
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
                    for (
                        option,
                        choice,
                    )
                    in variable.items()
                    if choice.get()
                ]

            else:
                uploaded[
                    field_name
                ] = (
                    variable.get().strip()
                )

    def _set_decision(
        self,
        decision,
    ):
        selected = (
            self.table.selection()
        )

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
                "assessment_id"
            ],
        )

        self.decisions[
            key
        ] = decision

        existing = conflict[
            "existing"
        ][
            "metadata"
        ]

        uploaded = conflict[
            "uploaded"
        ]

        conflict[
            "changed_fields"
        ] = _changed_fields(
            existing,
            uploaded,
            self.fields,
        )

        self._refresh_table()

    def _confirm(
        self,
    ):
        self._save_uploaded_values()

        if (
            len(
                self.decisions
            )
            != len(
                self.conflicts
            )
        ):
            return

        self.result = dict(
            self.decisions
        )

        self.destroy()


def import_clinical_file(
    parent,
    dictionary,
    store,
    site_id,
    expected_patient_ids,
):
    """Review, correct, and import longitudinal Clinical CSV/XLSX metadata."""

    path = filedialog.askopenfilename(
        parent=parent,
        title=(
            "Select Clinical metadata file"
        ),
        filetypes=(
            (
                "Metadata files",
                "*.csv *.xlsx",
            ),
            (
                "CSV files",
                "*.csv",
            ),
            (
                "Excel files",
                "*.xlsx",
            ),
        ),
    )

    if not path:
        return {}

    try:
        loaded = (
            load_metadata_file(
                path
            )
        )

    except MetadataFileError as exc:
        messagebox.showerror(
            "Could not load Clinical metadata",
            str(
                exc
            ),
            parent=parent,
        )
        return {}

    expected_patient_ids = {
        str(
            patient_id
        ).strip()
        for patient_id
        in expected_patient_ids
        if str(
            patient_id
        ).strip()
    }

    records = [
        normalize_record(
            dictionary,
            "Clinical",
            uploaded,
        )
        for uploaded
        in loaded[
            "rows"
        ]
    ]

    if (
        len(
            expected_patient_ids
        )
        == 1
    ):
        expected_patient_id = next(
            iter(
                expected_patient_ids
            )
        )

        uploaded_patient_ids = sorted(
            {
                str(
                    record.get(
                        "CoCANoT Patient ID"
                    )
                    or ""
                ).strip()
                for record
                in records
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
                != expected_patient_id
            }
        )

        if uploaded_patient_ids:
            shown = ", ".join(
                uploaded_patient_ids
            )

            confirmed = (
                messagebox.askyesno(
                    "Patient ID Does Not Match",
                    (
                        "The uploaded Clinical metadata contains "
                        f"CoCANoT Patient ID(s) {shown}, but you are "
                        f"currently reviewing Patient "
                        f"{expected_patient_id}.\n\n"
                        "If you continue, every selected Clinical Assessment "
                        f"will be assigned to Patient "
                        f"{expected_patient_id}. "
                        "The uploaded Patient ID will not be used."
                    ),
                    parent=parent,
                )
            )

            if not confirmed:
                return {}

        for record in records:
            record[
                "CoCANoT Patient ID"
            ] = expected_patient_id

    if not records:
        messagebox.showinfo(
            "No Clinical records found",
            (
                "The selected file does not "
                "contain any data rows."
            ),
            parent=parent,
        )
        return {}

    validator = MetadataValidator(
        dictionary
    )

    fields = dictionary[
        "tables"
    ][
        "Clinical"
    ][
        "fields"
    ]

    reviewed = {
        "records": None
    }

    def validate_for_review(
        record,
    ):
        assessment_id = str(
            record.get(
                "Clinical Assessment ID"
            )
            or ""
        ).strip().upper()

        errors = {}

        if not assessment_id:
            errors[
                "Clinical Assessment ID"
            ] = (
                "Clinical Assessment ID is required for "
                "Clinical history uploads."
            )

        elif (
            _clinical_assessment_number(
                assessment_id
            )
            is None
        ):
            errors[
                "Clinical Assessment ID"
            ] = (
                "Use the Clinical Assessment ID format "
                "CA-001, CA-002, and so on."
            )

        draft = dict(
            record
        )

        draft[
            "Clinical Assessment ID"
        ] = "PENDING"

        validation = (
            validator.validate_record(
                "Clinical",
                draft,
            )
        )

        for result in (
            validation[
                "results"
            ]
        ):
            if result[
                "status"
            ] not in {
                "invalid",
                "missing_required",
            }:
                continue

            field_name = (
                result[
                    "field_name"
                ]
            )

            if (
                field_name
                == "Clinical Assessment ID"
            ):
                continue

            errors[
                field_name
            ] = result[
                "message"
            ]

        return errors

    def review_finished(
        final_records,
    ):
        final_records = [
            dict(
                record
            )
            for record
            in final_records
        ]

        if (
            len(
                expected_patient_ids
            )
            == 1
        ):
            patient_id = next(
                iter(
                    expected_patient_ids
                )
            )

            for record in (
                final_records
            ):
                record[
                    "CoCANoT Patient ID"
                ] = patient_id

        duplicate_errors = (
            _selected_clinical_duplicate_errors(
                final_records,
            )
        )

        if duplicate_errors:
            messagebox.showerror(
                "Duplicate Clinical Assessment IDs",
                (
                    "The selected upload contains duplicate "
                    "Clinical Assessment IDs. Each Site + Patient "
                    "can only have one row for each Clinical "
                    "Assessment ID:\n\n"
                    + "\n".join(
                        duplicate_errors[
                            :20
                        ]
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
        table_name="Clinical",
        records=records,
        fields=fields,
        validate_record=(
            validate_for_review
        ),
        on_import=(
            review_finished
        ),
        preferred_patient_ids=(
            expected_patient_ids
        ),
    )

    parent.wait_window(
        review
    )

    records = reviewed[
        "records"
    ]

    if records is None:
        return {}

    rules = dictionary[
        "tables"
    ][
        "Clinical"
    ][
        "fields"
    ]

    (
        conflicts,
        resolutions,
    ) = _clinical_existing_conflicts(
        store,
        site_id,
        records,
        rules,
    )

    if conflicts:
        comparison = (
            ClinicalDuplicateComparisonDialog(
                parent,
                conflicts,
                rules,
            )
        )

        parent.wait_window(
            comparison
        )

        if comparison.result is None:
            return {}

        resolutions.update(
            comparison.result
        )

    prepared = (
        _prepare_reviewed_clinical_rows(
            dictionary,
            store,
            site_id,
            records,
            resolutions=(
                resolutions
            ),
        )
    )

    manual_lines = []

    for row in prepared:
        for field_name in (
            row[
                "manual_fields"
            ]
        ):
            manual_lines.append(
                f"{row['patient_id']} — "
                f"{field_name}: "
                f"{_display_value(row['record'].get(field_name))}"
            )

    if manual_lines:
        confirmed = (
            messagebox.askyesno(
                "Review free-text Clinical metadata",
                (
                    "Please confirm these uploaded free-text values are "
                    "appropriate and do not contain PHI:\n\n"
                    + "\n\n".join(
                        manual_lines[
                            :30
                        ]
                    )
                ),
                parent=parent,
            )
        )

        if not confirmed:
            return {}

    change_review = (
        ClinicalUploadReviewDialog(
            parent,
            prepared,
        )
    )

    parent.wait_window(
        change_review
    )

    if not change_review.result:
        return {}

    grouped = {}
    replace_ids = {}

    for row in prepared:
        if (
            row.get(
                "resolution"
            )
            == "keep"
        ):
            continue

        grouped.setdefault(
            row[
                "patient_id"
            ],
            [],
        ).append(
            row[
                "record"
            ]
        )

        if (
            row.get(
                "resolution"
            )
            == "replace"
        ):
            replace_ids.setdefault(
                row[
                    "patient_id"
                ],
                set(),
            ).add(
                row[
                    "assessment_id"
                ]
            )

    try:
        for (
            patient_id,
            patient_records,
        ) in grouped.items():
            store.import_clinical_assessments(
                site_id,
                patient_id,
                patient_records,
                replace_existing_ids=(
                    replace_ids.get(
                        patient_id,
                        set(),
                    )
                ),
            )

    except ValueError as exc:
        messagebox.showerror(
            "Clinical metadata could not be imported",
            str(
                exc
            ),
            parent=parent,
        )
        return {}

    imported = {}

    imported_patient_ids = {
        row[
            "patient_id"
        ]
        for row
        in prepared
    }

    for patient_id in (
        imported_patient_ids
    ):
        latest = (
            store.latest_clinical_assessment(
                site_id,
                patient_id,
            )
        )

        if latest is not None:
            imported[
                patient_id
            ] = latest[
                "assessment_id"
            ]

    return imported


def _prepare_reviewed_clinical_rows(
    dictionary,
    store,
    site_id,
    records,
    resolutions=None,
):
    """Prepare selected Clinical history rows for final longitudinal review."""

    validator = (
        MetadataValidator(
            dictionary
        )
    )

    rules = dictionary[
        "tables"
    ][
        "Clinical"
    ][
        "fields"
    ]

    prepared = []

    resolutions = dict(
        resolutions
        or {}
    )

    existing_max = {}

    patient_ids = {
        str(
            record.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()
        for record
        in records
    }

    for patient_id in (
        patient_ids
    ):
        existing = (
            store.clinical_assessments_for_patient(
                site_id,
                patient_id,
            )
        )

        existing_max[
            patient_id
        ] = max(
            [
                int(
                    item[
                        "assessment_number"
                    ]
                )
                for item
                in existing
            ],
            default=0,
        )

    selected_max = {}

    for record in records:
        patient_id = str(
            record.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()

        assessment_id = str(
            record.get(
                "Clinical Assessment ID"
            )
            or ""
        ).strip().upper()

        assessment_number = (
            _clinical_assessment_number(
                assessment_id
            )
        )

        selected_max[
            patient_id
        ] = max(
            selected_max.get(
                patient_id,
                0,
            ),
            assessment_number
            or 0,
        )

    overall_max = {
        patient_id: max(
            existing_max.get(
                patient_id,
                0,
            ),
            selected_max.get(
                patient_id,
                0,
            ),
        )
        for patient_id
        in patient_ids
    }

    for record in records:
        record = dict(
            record
        )

        patient_id = str(
            record.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()

        assessment_id = str(
            record.get(
                "Clinical Assessment ID"
            )
            or ""
        ).strip().upper()

        assessment_number = (
            _clinical_assessment_number(
                assessment_id
            )
        )

        record[
            "CoCANoT Patient ID"
        ] = patient_id

        record[
            "Clinical Assessment ID"
        ] = assessment_id

        draft = dict(
            record
        )

        draft[
            "Clinical Assessment ID"
        ] = "PENDING"

        validation = (
            validator.validate_record(
                "Clinical",
                draft,
            )
        )

        manual_fields = [
            result[
                "field_name"
            ]
            for result
            in validation[
                "results"
            ]
            if result[
                "status"
            ] == "manual_review"
            and draft.get(
                result[
                    "field_name"
                ]
            )
        ]

        previous_assessments = (
            store.clinical_assessments_for_patient(
                site_id,
                patient_id,
            )
        )

        previous = None
        exact_existing = None

        for item in (
            previous_assessments
        ):
            if int(
                item[
                    "assessment_number"
                ]
            ) == assessment_number:
                exact_existing = item

            if int(
                item[
                    "assessment_number"
                ]
            ) < assessment_number:
                previous = item

        key = (
            patient_id,
            assessment_id,
        )

        resolution = (
            resolutions.get(
                key,
                "new",
            )
        )

        if (
            exact_existing
            is not None
        ):
            current = dict(
                exact_existing[
                    "metadata"
                ]
            )

        else:
            current = (
                dict(
                    previous[
                        "metadata"
                    ]
                )
                if previous
                is not None
                else {}
            )

        changed = _changed_fields(
            current,
            record,
            rules,
        )

        status = (
            "Current"
            if assessment_number
            == overall_max[
                patient_id
            ]
            else "Previous"
        )

        if resolution == "keep":
            summary = (
                "Keep existing stored assessment"
            )

        elif resolution == "replace":
            summary = (
                "Replace existing assessment "
                "with uploaded values"
            )

        else:
            summary = (
                f"Import as "
                f"{status.lower()} "
                "Clinical Assessment"
            )

        comparison_assessment = (
            exact_existing
            if exact_existing
            is not None
            else previous
        )

        prepared.append(
            {
                "patient_id": (
                    patient_id
                ),
                "record": (
                    record
                ),
                "latest": (
                    comparison_assessment
                ),
                "current": (
                    current
                ),
                "existing_id": (
                    comparison_assessment[
                        "assessment_id"
                    ]
                    if comparison_assessment
                    is not None
                    else ""
                ),
                "result_id": (
                    assessment_id
                ),
                "assessment_id": (
                    assessment_id
                ),
                "assessment_number": (
                    assessment_number
                ),
                "status": (
                    status
                ),
                "summary": (
                    summary
                ),
                "changed_fields": (
                    changed
                ),
                "tracked_changed_fields": [],
                "manual_fields": (
                    manual_fields
                ),
                "resolution": (
                    resolution
                ),
            }
        )

    prepared.sort(
        key=lambda row: (
            row[
                "patient_id"
            ],
            row[
                "assessment_number"
            ],
        )
    )

    return prepared


class ClinicalBatchOverviewDialog(
    tk.Toplevel
):
    """Show what is already known before asking for new Clinical data."""

    def __init__(
        self,
        parent,
        patients,
    ):
        super().__init__(
            parent
        )

        self.result = None

        self.title(
            "Clinical Assessment Check"
        )
        self.geometry(
            "900x620"
        )
        self.minsize(
            760,
            520,
        )
        self.transient(
            parent
        )
        self.grab_set()

        existing_count = sum(
            1
            for item
            in patients
            if item[
                "assessment"
            ] is not None
        )

        missing_count = (
            len(
                patients
            )
            - existing_count
        )

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
            text=(
                "Clinical Assessment Check"
            ),
            font=("", 17, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            root,
            text=(
                f"{len(patients)} patients are in this submission. "
                f"{existing_count} already have a Clinical Assessment; "
                f"{missing_count} do not.\n\n"
                "Existing data is shown first. Choose Review One by One "
                "to keep or edit each patient's current assessment, or "
                "Upload Clinical Metadata to reconcile a CSV/XLSX against "
                "the stored assessments."
            ),
            wraplength=840,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(5, 10),
        )

        tree = ttk.Treeview(
            root,
            columns=(
                "patient",
                "assessment",
                "status",
            ),
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
            "assessment",
            text=(
                "Latest Clinical Assessment"
            ),
        )

        tree.heading(
            "status",
            text=(
                "Current Status"
            ),
        )

        tree.column(
            "patient",
            width=180,
        )

        tree.column(
            "assessment",
            width=220,
        )

        tree.column(
            "status",
            width=420,
        )

        ordered = sorted(
            patients,
            key=lambda item: (
                item[
                    "assessment"
                ] is None,
                item[
                    "patient_id"
                ],
            ),
        )

        for item in ordered:
            assessment = item[
                "assessment"
            ]

            tree.insert(
                "",
                "end",
                values=(
                    item[
                        "patient_id"
                    ],
                    (
                        assessment[
                            "assessment_id"
                        ]
                        if assessment
                        is not None
                        else "None"
                    ),
                    (
                        "Existing clinical data found"
                        if assessment
                        is not None
                        else "Clinical metadata needed"
                    ),
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
            side="right"
        )

        ttk.Button(
            actions,
            text="Upload Clinical Metadata",
            command=lambda: (
                self._finish(
                    "upload"
                )
            ),
        ).pack(
            side="right",
            padx=(0, 8),
        )

        ttk.Button(
            actions,
            text="Review One by One",
            command=lambda: (
                self._finish(
                    "review"
                )
            ),
        ).pack(
            side="right",
            padx=(0, 8),
        )

    def _finish(
        self,
        result,
    ):
        self.result = result
        self.destroy()


def review_clinical_batch(
    parent,
    store,
    site_id,
    patient_ids,
):
    patients = [
        {
            "patient_id": (
                patient_id
            ),
            "assessment": (
                store.latest_clinical_assessment(
                    site_id,
                    patient_id,
                )
            ),
        }
        for patient_id
        in patient_ids
    ]

    dialog = (
        ClinicalBatchOverviewDialog(
            parent,
            patients,
        )
    )

    parent.wait_window(
        dialog
    )

    return dialog.result


def _legacy_import_missing_clinical_file(
    parent,
    dictionary,
    store,
    site_id,
    expected_patient_ids,
):
    """Import one Clinical CSV/XLSX containing one row per missing patient."""

    path = filedialog.askopenfilename(
        parent=parent,
        title=(
            "Select Clinical metadata file"
        ),
        filetypes=(
            (
                "Metadata files",
                "*.csv *.xlsx",
            ),
            (
                "CSV files",
                "*.csv",
            ),
            (
                "Excel files",
                "*.xlsx",
            ),
        ),
    )

    if not path:
        return {}

    loaded = load_metadata_file(
        path
    )

    validator = (
        MetadataValidator(
            dictionary
        )
    )

    tracked_fields = (
        tracked_clinical_fields(
            dictionary
        )
    )

    imported = {}

    for (
        row_number,
        uploaded,
    ) in enumerate(
        loaded[
            "rows"
        ],
        start=2,
    ):
        record = normalize_record(
            dictionary,
            "Clinical",
            uploaded,
        )

        patient_id = str(
            record.get(
                "CoCANoT Patient ID"
            )
            or ""
        ).strip()

        if (
            patient_id
            not in expected_patient_ids
        ):
            continue

        record[
            "Clinical Assessment ID"
        ] = "PENDING"

        validation = (
            validator.validate_record(
                "Clinical",
                record,
            )
        )

        problems = [
            result
            for result
            in validation[
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
            raise ValueError(
                f"Clinical upload row "
                f"{row_number} for "
                f"{patient_id} is invalid: "
                + "; ".join(
                    item[
                        "message"
                    ]
                    for item
                    in problems[:5]
                )
            )

        record.pop(
            "Clinical Assessment ID",
            None,
        )

        saved = (
            store.save_clinical_assessment(
                site_id,
                patient_id,
                record,
                tracked_fields,
            )
        )

        imported[
            patient_id
        ] = saved[
            "assessment_id"
        ]

    return imported