"""Site ID and access-code validation for the development build."""

import csv
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ACCESS_FILE = PROJECT_ROOT / "config" / "site_access.csv"


def normalize_site_id(value):
    return str(value or "").strip().upper()


def validate_site_access(
    site_id,
    access_code,
    access_file=DEFAULT_ACCESS_FILE,
):
    site_id = normalize_site_id(site_id)
    access_code = str(access_code or "").strip()

    if not site_id or not access_code:
        return False

    access_file = Path(access_file)

    if not access_file.is_file():
        raise FileNotFoundError(
            f"Site access file not found: {access_file}"
        )

    with access_file.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        reader = csv.DictReader(handle)

        for row in reader:
            row_site = normalize_site_id(row.get("site_id"))
            row_code = str(row.get("access_code") or "").strip()

            if row_site == site_id and row_code == access_code:
                return True

    return False


class SiteAccessView(ttk.Frame):
    def __init__(self, parent, on_success):
        super().__init__(parent, padding=28)

        self.on_success = on_success
        self.site_var = tk.StringVar()
        self.code_var = tk.StringVar()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        card = ttk.Frame(self, padding=28)
        card.grid(row=0, column=0)

        ttk.Label(
            card,
            text="CoCANoT",
            font=("", 24, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        ttk.Label(
            card,
            text="Connect to Your Site",
            font=("", 15, "bold"),
        ).grid(row=1, column=0, sticky="w", pady=(0, 18))

        ttk.Label(card, text="Site ID").grid(
            row=2,
            column=0,
            sticky="w",
        )

        site_entry = ttk.Entry(
            card,
            textvariable=self.site_var,
            width=36,
        )
        site_entry.grid(
            row=3,
            column=0,
            sticky="ew",
            pady=(4, 12),
        )

        ttk.Label(card, text="Access Code").grid(
            row=4,
            column=0,
            sticky="w",
        )

        code_entry = ttk.Entry(
            card,
            textvariable=self.code_var,
            show="•",
            width=36,
        )
        code_entry.grid(
            row=5,
            column=0,
            sticky="ew",
            pady=(4, 18),
        )

        ttk.Button(
            card,
            text="Continue",
            command=self._submit,
        ).grid(row=6, column=0, sticky="ew")

        ttk.Label(
            card,
            text=(
                "Your Site ID identifies the participating center. "
                "This development build validates access against "
                "config/site_access.csv."
            ),
            wraplength=390,
        ).grid(
            row=7,
            column=0,
            sticky="w",
            pady=(16, 0),
        )

        site_entry.focus_set()
        site_entry.bind(
            "<Return>",
            lambda event: code_entry.focus_set(),
        )
        code_entry.bind(
            "<Return>",
            lambda event: self._submit(),
        )

    def _submit(self):
        site_id = normalize_site_id(self.site_var.get())
        access_code = self.code_var.get()

        try:
            valid = validate_site_access(
                site_id,
                access_code,
            )
        except Exception as exc:
            messagebox.showerror(
                "Site Access Error",
                str(exc),
                parent=self,
            )
            return

        if not valid:
            messagebox.showerror(
                "Access Denied",
                (
                    "The Site ID and Access Code did not match "
                    "an authorized development site."
                ),
                parent=self,
            )
            return

        self.on_success(site_id)
