"""Bug-report form for the CoCANoT development build."""

import platform
import sys
import tkinter as tk
import urllib.parse
import webbrowser
from tkinter import messagebox, ttk

from app.bug_store import BugStore


BUG_REPORT_EMAIL = "arifi020@umn.edu"

WORKFLOWS = (
    "General / Home",
    "Imaging",
    "Electrophysiology",
    "Metadata",
    "Patient Data Review",
)


class BugReportWindow(tk.Toplevel):
    def __init__(self, parent, site_id):
        super().__init__(parent)

        self.site_id = site_id
        self.store = BugStore()

        self.workflow_var = tk.StringVar(
            value=WORKFLOWS[0]
        )
        self.summary_var = tk.StringVar()
        self.include_diagnostics_var = tk.BooleanVar(
            value=True
        )

        self.title("Report a Bug")
        self.geometry("720x650")
        self.minsize(620, 560)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._build()

    def _build(self):
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(7, weight=1)

        ttk.Label(
            root,
            text="Report a Bug",
            font=("", 18, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            root,
            text=(
                "Please avoid entering patient names, dates of birth, "
                "medical record numbers, or other protected health information."
            ),
            wraplength=650,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(4, 14),
        )

        ttk.Label(root, text="Workflow").grid(
            row=2,
            column=0,
            sticky="w",
        )

        ttk.Combobox(
            root,
            textvariable=self.workflow_var,
            values=WORKFLOWS,
            state="readonly",
        ).grid(
            row=3,
            column=0,
            sticky="ew",
            pady=(4, 12),
        )

        ttk.Label(
            root,
            text="Short description",
        ).grid(row=4, column=0, sticky="w")

        ttk.Entry(
            root,
            textvariable=self.summary_var,
        ).grid(
            row=5,
            column=0,
            sticky="ew",
            pady=(4, 12),
        )

        ttk.Label(
            root,
            text="What happened?",
        ).grid(row=6, column=0, sticky="w")

        self.description_text = tk.Text(
            root,
            height=8,
            wrap="word",
        )
        self.description_text.grid(
            row=7,
            column=0,
            sticky="nsew",
            pady=(4, 12),
        )

        ttk.Label(
            root,
            text="What did you expect to happen?",
        ).grid(row=8, column=0, sticky="w")

        self.expected_text = tk.Text(
            root,
            height=5,
            wrap="word",
        )
        self.expected_text.grid(
            row=9,
            column=0,
            sticky="ew",
            pady=(4, 10),
        )

        ttk.Checkbutton(
            root,
            text="Include safe technical diagnostics",
            variable=self.include_diagnostics_var,
        ).grid(row=10, column=0, sticky="w")

        ttk.Label(
            root,
            text=(
                "Diagnostics include site ID, operating system, "
                "Python version, and workflow. Patient metadata and "
                "data filenames are not included automatically."
            ),
            wraplength=650,
        ).grid(
            row=11,
            column=0,
            sticky="w",
            pady=(2, 14),
        )

        buttons = ttk.Frame(root)
        buttons.grid(
            row=12,
            column=0,
            sticky="e",
        )

        ttk.Button(
            buttons,
            text="Cancel",
            command=self.destroy,
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            buttons,
            text="Submit Bug Report",
            command=self._submit,
        ).pack(side="left")

    def _technical_details(self):
        if not self.include_diagnostics_var.get():
            return {}

        return {
            "site_id": self.site_id,
            "workflow": self.workflow_var.get(),
            "operating_system": platform.platform(),
            "python_version": sys.version.split()[0],
        }

    def _submit(self):
        summary = self.summary_var.get().strip()
        description = self.description_text.get(
            "1.0",
            "end",
        ).strip()
        expected = self.expected_text.get(
            "1.0",
            "end",
        ).strip()

        if not summary:
            messagebox.showerror(
                "Missing Information",
                "Enter a short description of the problem.",
                parent=self,
            )
            return

        if not description:
            messagebox.showerror(
                "Missing Information",
                "Describe what happened.",
                parent=self,
            )
            return

        technical_details = self._technical_details()

        try:
            result = self.store.save_report(
                site_id=self.site_id,
                workflow=self.workflow_var.get(),
                summary=summary,
                description=description,
                expected_behavior=expected,
                technical_details=technical_details,
            )
        except Exception as exc:
            messagebox.showerror(
                "Could Not Save Bug Report",
                str(exc),
                parent=self,
            )
            return

        email_opened = self._open_email(
            result["bug_id"],
            summary,
            description,
            expected,
            technical_details,
        )

        self.store.update_status(
            result["bug_id"],
            (
                "Email Prepared"
                if email_opened
                else "Saved Locally"
            ),
        )

        messagebox.showinfo(
            "Bug Report Saved",
            (
                f"Bug report {result['bug_id']} was saved locally.\n\n"
                + (
                    "A prepared email was opened in your default mail app. "
                    "Please send it to complete the report."
                    if email_opened
                    else (
                        "The default mail app could not be opened. "
                        "The report remains saved locally."
                    )
                )
            ),
            parent=self,
        )

        self.destroy()

    def _open_email(
        self,
        bug_id,
        summary,
        description,
        expected,
        technical_details,
    ):
        subject = (
            f"[CoCANoT Bug] {self.site_id} - "
            f"{self.workflow_var.get()} - {summary}"
        )

        lines = [
            f"Bug ID: {bug_id}",
            f"Site: {self.site_id}",
            f"Workflow: {self.workflow_var.get()}",
            "",
            "Problem:",
            description,
            "",
            "Expected behavior:",
            expected or "(not provided)",
        ]

        if technical_details:
            lines.extend(
                [
                    "",
                    "Technical diagnostics:",
                ]
            )

            for key, value in technical_details.items():
                lines.append(f"{key}: {value}")

        body = "\n".join(lines)

        mailto = (
            f"mailto:{BUG_REPORT_EMAIL}"
            f"?subject={urllib.parse.quote(subject)}"
            f"&body={urllib.parse.quote(body)}"
        )

        try:
            return bool(webbrowser.open(mailto))
        except Exception:
            return False
