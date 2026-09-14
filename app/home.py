"""Main CoCANoT workflow selection screen."""

from tkinter import ttk

from app.bug_report import BugReportWindow


class CoCANoTHome(ttk.Frame):
    """Choose a workflow inside the unified CoCANoT window."""

    def __init__(
        self,
        parent,
        site_id,
        on_imaging,
        on_ephys,
        on_metadata,
        on_review_patients,
        on_sign_out,
    ):
        super().__init__(parent, padding=20)

        self.site_id = site_id
        self.on_imaging = on_imaging
        self.on_ephys = on_ephys
        self.on_metadata = on_metadata
        self.on_review_patients = on_review_patients
        self.on_sign_out = on_sign_out

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_workflows()
        self._build_support()

    def _build_header(self):
        header = ttk.Frame(self)
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 18),
        )
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="CoCANoT",
            font=("", 22, "bold"),
        ).grid(row=0, column=0, sticky="w")

        actions = ttk.Frame(header)
        actions.grid(row=0, column=1, sticky="e")

        ttk.Label(
            actions,
            text=f"Site: {self.site_id}",
        ).pack(side="left", padx=(0, 12))

        ttk.Button(
            actions,
            text="Sign Out",
            command=self.on_sign_out,
        ).pack(side="left")

        ttk.Label(
            header,
            text="Select a Workflow",
            font=("", 15, "bold"),
        ).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(18, 0),
        )

    def _build_workflows(self):
        grid = ttk.Frame(self)
        grid.grid(
            row=1,
            column=0,
            sticky="nsew",
        )
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        self._workflow_card(
            grid,
            0,
            0,
            "Imaging",
            (
                "De-identify, review, validate, and "
                "organize MRI and CT data."
            ),
            "Open Imaging",
            self.on_imaging,
        )

        self._workflow_card(
            grid,
            0,
            1,
            "Electrophysiology",
            (
                "De-identify, review, validate, and "
                "organize electrophysiology recordings."
            ),
            "Open Electrophysiology",
            self.on_ephys,
        )

        self._workflow_card(
            grid,
            1,
            0,
            "Metadata",
            (
                "Enter, import, validate, and manage "
                "CoCANoT metadata."
            ),
            "Open Metadata",
            self.on_metadata,
        )

        self._workflow_card(
            grid,
            1,
            1,
            "Patient Data Review",
            (
                "Review clinical, surgical, imaging, and "
                "electrophysiology data for one participant."
            ),
            "Review Patients",
            self.on_review_patients,
        )

    def _workflow_card(
        self,
        parent,
        row,
        column,
        title,
        description,
        button_text,
        command,
    ):
        card = ttk.LabelFrame(
            parent,
            text=title,
            padding=16,
        )
        card.grid(
            row=row,
            column=column,
            sticky="nsew",
            padx=(
                0 if column == 0 else 8,
                8 if column == 0 else 0,
            ),
            pady=8,
        )
        card.columnconfigure(0, weight=1)

        ttk.Label(
            card,
            text=description,
            wraplength=410,
        ).grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 14),
        )

        ttk.Button(
            card,
            text=button_text,
            command=command,
        ).grid(
            row=1,
            column=0,
            sticky="ew",
        )

    def _build_support(self):
        support = ttk.LabelFrame(
            self,
            text="Support",
            padding=14,
        )
        support.grid(
            row=2,
            column=0,
            sticky="ew",
            pady=(18, 0),
        )
        support.columnconfigure(0, weight=1)

        ttk.Label(
            support,
            text="Found a problem while using CoCANoT?",
        ).grid(row=0, column=0, sticky="w")

        ttk.Button(
            support,
            text="Report a Bug",
            command=self._report_bug,
        ).grid(
            row=0,
            column=1,
            sticky="e",
            padx=(12, 0),
        )

    def _report_bug(self):
        BugReportWindow(
            self,
            site_id=self.site_id,
        )
