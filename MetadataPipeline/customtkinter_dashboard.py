#!/usr/bin/env python3
"""CustomTkinter presentation layer for CoCANoT Metadata Management.

Save this file as:
    MetadataPipeline/customtkinter_dashboard.py

The existing MetadataPipeline/dashboard.py remains the source of business logic.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from MetadataPipeline.dashboard import MetadataDashboard as LegacyMetadataDashboard
from MetadataPipeline.views.metadata_home import MetadataBulkHome
from MetadataPipeline.views.patient_explorer import PatientExplorer


__all__ = ["MetadataDashboard"]


class Palette:
    BG = "#F4F7FB"
    SURFACE = "#FFFFFF"
    SURFACE_ALT = "#F8FAFD"
    BORDER = "#DCE5EF"
    TEXT = "#17263A"
    MUTED = "#66788D"
    PRIMARY = "#2563EB"
    PRIMARY_HOVER = "#1D4ED8"
    SUCCESS = "#15803D"
    WARNING = "#B45309"
    DANGER = "#B91C1C"
    SOFT_BLUE = "#EAF1FF"
    SOFT_GREEN = "#EAF7EE"
    SOFT_AMBER = "#FFF5E6"


def card(master, **kwargs):
    return ctk.CTkFrame(
        master,
        fg_color=kwargs.pop("fg_color", Palette.SURFACE),
        corner_radius=14,
        border_width=1,
        border_color=Palette.BORDER,
        **kwargs,
    )


def title(master, text, size=24):
    return ctk.CTkLabel(
        master,
        text=text,
        text_color=Palette.TEXT,
        font=("Arial", size, "bold"),
        anchor="w",
    )


def subtitle(master, text, wraplength=900):
    return ctk.CTkLabel(
        master,
        text=text,
        text_color=Palette.MUTED,
        font=("Arial", 12),
        justify="left",
        anchor="w",
        wraplength=wraplength,
    )


def primary_button(master, text, command, **kwargs):
    options = {
        "height": 38,
        "corner_radius": 9,
        "fg_color": Palette.PRIMARY,
        "hover_color": Palette.PRIMARY_HOVER,
        "font": ("Arial", 12, "bold"),
    }
    options.update(kwargs)
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        **options,
    )


def secondary_button(master, text, command, **kwargs):
    options = {
        "height": 36,
        "corner_radius": 9,
        "fg_color": Palette.SURFACE,
        "hover_color": Palette.SURFACE_ALT,
        "text_color": Palette.TEXT,
        "border_width": 1,
        "border_color": Palette.BORDER,
        "font": ("Arial", 11, "bold"),
    }
    options.update(kwargs)
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        **options,
    )



class MetadataDashboard(LegacyMetadataDashboard):
    """Modern metadata dashboard that reuses the existing data-management logic."""

    def _build_interface(self):
        self.configure(style="TFrame")

        self.shell = ctk.CTkFrame(self, fg_color=Palette.BG, corner_radius=0)
        self.shell.pack(fill="both", expand=True)
        self.shell.grid_columnconfigure(0, weight=1)
        self.shell.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(
            self.shell,
            fg_color=Palette.SURFACE,
            corner_radius=0,
            height=78,
        )
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)

        heading = ctk.CTkFrame(header, fg_color="transparent")
        heading.grid(row=0, column=0, sticky="w", padx=22, pady=13)

        title(heading, "Metadata Management", 23).pack(anchor="w")
        subtitle(
            heading,
            "Create, review, and validate patient metadata from the active CoCANoT dictionary.",
        ).pack(anchor="w", pady=(2, 0))

        site_box = ctk.CTkFrame(
            header,
            fg_color=Palette.SURFACE_ALT,
            corner_radius=10,
            border_width=1,
            border_color=Palette.BORDER,
        )
        site_box.grid(row=0, column=1, sticky="e", padx=22, pady=14)

        ctk.CTkLabel(
            site_box,
            textvariable=self.site_var,
            text_color=Palette.TEXT,
            font=("Arial", 11, "bold"),
        ).pack(side="left", padx=(12, 8), pady=8)

        secondary_button(
            site_box,
            "Change Site",
            self._change_site,
            width=100,
            height=30,
        ).pack(side="left", padx=(0, 6), pady=5)

        self.content = ctk.CTkFrame(
            self.shell,
            fg_color="transparent",
            corner_radius=0,
        )
        self.content.grid(row=1, column=0, sticky="nsew", padx=18, pady=18)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

    def _clear_content(self):
        self._unbind_patient_explorer_mousewheel()

        for child in self.content.winfo_children():
            child.destroy()

        self.current_view = None
        self.explorer = None

    def _show_home(self):
        self._clear_content()

        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure((0, 1), weight=1, uniform="meta")
        page.grid_rowconfigure(2, weight=1)

        nav = ctk.CTkFrame(page, fg_color="transparent")
        nav.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))

        if self.on_back is not None:
            secondary_button(nav, "← Back", self.on_back, width=88).pack(side="left")

        title(page, "What would you like to do?", 26).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 16)
        )

        manage = card(page)
        manage.grid(row=2, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        manage.grid_columnconfigure(0, weight=1)
        manage.grid_rowconfigure(3, weight=1)

        badge = ctk.CTkFrame(manage, width=48, height=48, corner_radius=12, fg_color=Palette.SOFT_BLUE)
        badge.grid(row=0, column=0, sticky="w", padx=18, pady=(18, 12))
        badge.grid_propagate(False)
        ctk.CTkLabel(badge, text="PT", text_color=Palette.PRIMARY, font=("Arial", 16, "bold")).place(
            relx=.5, rely=.5, anchor="center"
        )

        title(manage, "Manage one patient", 18).grid(row=1, column=0, sticky="w", padx=18)
        subtitle(
            manage,
            "Find an existing patient or add a new one, then review clinical, surgical, imaging, and electrophysiology records in one place.",
            430,
        ).grid(row=2, column=0, sticky="nw", padx=18, pady=(8, 18))
        primary_button(
            manage,
            "Open Patient Workspace",
            self._show_patient_explorer,
        ).grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 18))

        bulk = card(page)
        bulk.grid(row=2, column=1, sticky="nsew", padx=(8, 0), pady=(0, 8))
        bulk.grid_columnconfigure(0, weight=1)
        bulk.grid_rowconfigure(3, weight=1)

        badge2 = ctk.CTkFrame(bulk, width=48, height=48, corner_radius=12, fg_color=Palette.SOFT_GREEN)
        badge2.grid(row=0, column=0, sticky="w", padx=18, pady=(18, 12))
        badge2.grid_propagate(False)
        ctk.CTkLabel(badge2, text="CSV", text_color=Palette.SUCCESS, font=("Arial", 14, "bold")).place(
            relx=.5, rely=.5, anchor="center"
        )

        title(bulk, "Bulk metadata upload", 18).grid(row=1, column=0, sticky="w", padx=18)
        subtitle(
            bulk,
            "Import metadata for multiple records using the same dictionary-driven validation rules used by the patient workspace.",
            430,
        ).grid(row=2, column=0, sticky="nw", padx=18, pady=(8, 18))
        primary_button(
            bulk,
            "Open Bulk Upload",
            self._show_bulk_home,
        ).grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 18))

        quick = card(page, fg_color=Palette.SURFACE_ALT)
        quick.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        quick.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            quick,
            text="Dictionary-driven",
            text_color=Palette.TEXT,
            font=("Arial", 12, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=(16, 10), pady=14)
        subtitle(
            quick,
            "Required fields, allowed values, conditional fields, and validation rules remain sourced from CoCANoT_Metadata_Phase1.xlsx.",
            900,
        ).grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=14)

        self.current_view = page

    def _show_bulk_home(self):
        self._clear_content()

        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure((0, 1), weight=1, uniform="bulk")
        page.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(page, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        secondary_button(top, "← Back", self._show_home, width=88).pack(side="left")

        title(page, "Bulk metadata upload", 25).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 14)
        )

        options = [
            ("Clinical assessments", "Import clinical metadata for multiple patients.", lambda: self._show_batch_import("Clinical"), Palette.SOFT_BLUE),
            ("Surgical records", "Import surgical metadata in batches.", lambda: self._show_batch_import("Surgical"), Palette.SOFT_GREEN),
            ("Imaging workflow", "Open the imaging processing workflow for new imaging records.", self._open_imaging_workflow, Palette.SOFT_AMBER),
            ("Electrophysiology workflow", "Open the electrophysiology processing workflow for new recordings.", self._open_electrophysiology_workflow, Palette.SOFT_BLUE),
        ]

        for index, (name, desc, command, tint) in enumerate(options):
            box = card(page)
            box.grid(
                row=2 + index // 2,
                column=index % 2,
                sticky="nsew",
                padx=(0, 8) if index % 2 == 0 else (8, 0),
                pady=8,
            )
            box.grid_columnconfigure(0, weight=1)
            ctk.CTkFrame(box, width=8, height=54, corner_radius=4, fg_color=tint).grid(
                row=0, column=0, sticky="w", padx=16, pady=(16, 8)
            )
            title(box, name, 17).grid(row=1, column=0, sticky="w", padx=16)
            subtitle(box, desc, 400).grid(row=2, column=0, sticky="w", padx=16, pady=(6, 14))
            primary_button(box, "Open", command).grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))

        self.current_view = page


def main():
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.title("CoCANoT Metadata Management")
    root.geometry("1280x900")
    root.minsize(980, 700)

    initial_view = "patient_explorer" if "--patient-explorer" in sys.argv else "home"

    app = MetadataDashboard(root, initial_view=initial_view)
    app.pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
