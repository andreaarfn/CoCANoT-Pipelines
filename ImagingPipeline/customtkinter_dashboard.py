#!/usr/bin/env python3
"""CustomTkinter presentation layer for the CoCANoT Imaging pipeline.

Save this file as:
    ImagingPipeline/customtkinter_dashboard.py

The existing ImagingPipeline/dashboard.py continues to own conversion,
de-identification, defacing, review, metadata validation, and BIDS logic.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from ImagingPipeline.dashboard import (
    ImagingDashboard as LegacyImagingDashboard,
    ExtendedSelectionController,
    FolderSelector,
    PROJECT_ROOT,
    get_settings_path,
)


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
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        height=38,
        corner_radius=9,
        fg_color=Palette.PRIMARY,
        hover_color=Palette.PRIMARY_HOVER,
        font=("Arial", 12, "bold"),
        **kwargs,
    )


def secondary_button(master, text, command, **kwargs):
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        height=36,
        corner_radius=9,
        fg_color=Palette.SURFACE,
        hover_color=Palette.SURFACE_ALT,
        text_color=Palette.TEXT,
        border_width=1,
        border_color=Palette.BORDER,
        font=("Arial", 11, "bold"),
        **kwargs,
    )



class ImagingDashboard(LegacyImagingDashboard):
    """Modern UI for the existing imaging pipeline."""

    def _show_home(self):
        if self.pipeline_busy:
            messagebox.showwarning(
                "Pipeline busy",
                "Finish or stop the current operation before leaving the processing screen.",
                parent=self,
            )
            return

        self._clear_window()

        page = ctk.CTkFrame(self, fg_color=Palette.BG, corner_radius=0)
        page.pack(fill="both", expand=True)
        page.grid_columnconfigure((0, 1), weight=1, uniform="img")
        page.grid_rowconfigure(2, weight=1)

        nav = ctk.CTkFrame(page, fg_color="transparent")
        nav.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(18, 4))
        if self.on_back is not None:
            secondary_button(nav, "← Back", self._return_to_cocanot, width=88).pack(side="left")

        heading = ctk.CTkFrame(page, fg_color="transparent")
        heading.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=(6, 18))
        title(heading, "Imaging", 28).pack(anchor="w")
        subtitle(
            heading,
            "Prepare DICOM or NIfTI data, remove identifying metadata, deface, visually review, and create BIDS outputs.",
        ).pack(anchor="w", pady=(4, 0))

        process = card(page)
        process.grid(row=2, column=0, sticky="nsew", padx=(20, 9), pady=(0, 20))
        process.grid_columnconfigure(0, weight=1)
        process.grid_rowconfigure(3, weight=1)

        badge = ctk.CTkFrame(process, width=52, height=52, corner_radius=13, fg_color=Palette.SOFT_BLUE)
        badge.grid(row=0, column=0, sticky="w", padx=18, pady=(18, 12))
        badge.grid_propagate(False)
        ctk.CTkLabel(badge, text="MRI", text_color=Palette.PRIMARY, font=("Arial", 15, "bold")).place(
            relx=.5, rely=.5, anchor="center"
        )
        title(process, "Process imaging data", 19).grid(row=1, column=0, sticky="w", padx=18)
        subtitle(
            process,
            "Add source images, prepare NIfTI files, scrub headers, deface, perform side-by-side review, and organize accepted data as BIDS.",
            440,
        ).grid(row=2, column=0, sticky="nw", padx=18, pady=(8, 18))
        primary_button(process, "Open Processing Workspace", self._show_processing).grid(
            row=4, column=0, sticky="ew", padx=18, pady=(0, 18)
        )

        review = card(page)
        review.grid(row=2, column=1, sticky="nsew", padx=(9, 20), pady=(0, 20))
        review.grid_columnconfigure(0, weight=1)
        review.grid_rowconfigure(3, weight=1)

        badge2 = ctk.CTkFrame(review, width=52, height=52, corner_radius=13, fg_color=Palette.SOFT_GREEN)
        badge2.grid(row=0, column=0, sticky="w", padx=18, pady=(18, 12))
        badge2.grid_propagate(False)
        ctk.CTkLabel(badge2, text="PT", text_color=Palette.SUCCESS, font=("Arial", 16, "bold")).place(
            relx=.5, rely=.5, anchor="center"
        )
        title(review, "Review patient data", 19).grid(row=1, column=0, sticky="w", padx=18)
        subtitle(
            review,
            "Review saved imaging records alongside clinical, surgical, and electrophysiology metadata.",
            440,
        ).grid(row=2, column=0, sticky="nw", padx=18, pady=(8, 18))
        secondary_button(review, "Open Patient Review", self._open_patient_explorer).grid(
            row=4, column=0, sticky="ew", padx=18, pady=(0, 18)
        )

    def _build_interface(self):
        outer = ctk.CTkFrame(self, fg_color=Palette.BG, corner_radius=0)
        outer.pack(fill="both", expand=True)

        scroll = ctk.CTkScrollableFrame(
            outer,
            fg_color=Palette.BG,
            corner_radius=0,
            scrollbar_button_color="#CBD5E1",
            scrollbar_button_hover_color="#94A3B8",
        )
        scroll.pack(fill="both", expand=True)
        scroll.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 14))
        header.grid_columnconfigure(0, weight=1)

        title(header, "Imaging Processing", 26).grid(row=0, column=0, sticky="w")
        subtitle(
            header,
            "The five-stage workflow keeps preparation, de-identification, visual review, and metadata confirmation distinct.",
            980,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        secondary_button(header, "← Back", self._leave_processing, width=88).grid(
            row=0, column=1, rowspan=2, sticky="e"
        )

        setup = card(scroll)
        setup.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 12))
        setup.grid_columnconfigure((0, 1), weight=1, uniform="inputs")

        title(setup, "1  Source data", 17).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(16, 4)
        )
        subtitle(
            setup,
            "DICOM and NIfTI can be added independently. The dashboard prepares both into a common NIfTI workflow.",
            900,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 12))

        def input_panel(parent, column, heading_text, add_file_text, add_file_command, add_folder_command, paths):
            box = ctk.CTkFrame(parent, fg_color=Palette.SURFACE_ALT, corner_radius=12)
            box.grid(row=2, column=column, sticky="nsew", padx=(18, 7) if column == 0 else (7, 18), pady=(0, 16))
            box.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                box,
                text=heading_text,
                text_color=Palette.TEXT,
                font=("Arial", 13, "bold"),
            ).grid(row=0, column=0, sticky="w", padx=13, pady=(12, 6))

            host = tk.Frame(box, bg=Palette.SURFACE, highlightbackground=Palette.BORDER, highlightthickness=1)
            host.grid(row=1, column=0, sticky="ew", padx=13)
            host.grid_columnconfigure(0, weight=1)

            listbox = tk.Listbox(
                host,
                height=5,
                selectmode="extended",
                exportselection=False,
                bd=0,
                highlightthickness=0,
                background=Palette.SURFACE,
                foreground=Palette.TEXT,
                selectbackground="#DCEAFF",
                selectforeground=Palette.TEXT,
            )
            listbox.grid(row=0, column=0, sticky="ew")
            selection = ExtendedSelectionController(listbox)

            actions = ctk.CTkFrame(box, fg_color="transparent")
            actions.grid(row=2, column=0, sticky="ew", padx=13, pady=10)

            add_file = secondary_button(actions, add_file_text, add_file_command)
            add_file.pack(side="left")
            add_folder = secondary_button(actions, "Add Folders…", add_folder_command)
            add_folder.pack(side="left", padx=6)

            def remove():
                self._remove_selected_inputs(listbox, paths)

            remove_button = secondary_button(actions, "Remove", remove)
            remove_button.pack(side="left")

            return listbox, selection, add_file, add_folder, remove_button

        (
            self.dicom_input_list,
            self.dicom_input_selection,
            self.add_dicom_files_button,
            self.add_dicom_folders_button,
            self.remove_dicom_button,
        ) = input_panel(
            setup,
            0,
            "DICOM sources",
            "Add DICOM Files…",
            self._add_dicom_files,
            self._add_dicom_folders,
            self.dicom_input_paths,
        )

        (
            self.nifti_input_list,
            self.nifti_input_selection,
            self.add_nifti_files_button,
            self.add_nifti_folders_button,
            self.remove_nifti_button,
        ) = input_panel(
            setup,
            1,
            "NIfTI sources",
            "Add NIfTI Files…",
            self._add_nifti_files,
            self._add_nifti_folders,
            self.nifti_input_paths,
        )

        raw = card(scroll)
        raw.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 12))
        raw.grid_columnconfigure((0, 1), weight=1, uniform="raw")

        title(raw, "2  Verify discovered files", 17).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(16, 4)
        )
        subtitle(
            raw,
            "These views show the raw files discovered from the sources above before any processing begins.",
            900,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 10))

        self.raw_dicom_tree = self._build_raw_file_viewer(
            raw, row=2, column=0, title="Raw DICOM Files"
        )
        self.raw_nifti_tree = self._build_raw_file_viewer(
            raw, row=2, column=1, title="Raw NIfTI Files"
        )

        outputs = card(scroll)
        outputs.grid(row=3, column=0, sticky="ew", padx=6, pady=(0, 12))
        outputs.grid_columnconfigure((0, 1), weight=1, uniform="outputs")

        title(outputs, "3  Output locations", 17).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(16, 10)
        )

        self.derivatives_selector = FolderSelector(
            outputs,
            "Derivatives output folder",
            self.derivatives_dir_var,
            "Select the imaging derivatives output folder",
            PROJECT_ROOT,
        )
        self.derivatives_selector.grid(row=1, column=0, sticky="ew", padx=(18, 9), pady=(0, 14))

        self.bids_selector = FolderSelector(
            outputs,
            "BIDS output folder",
            self.bids_output_dir_var,
            "Select the imaging BIDS output folder",
            PROJECT_ROOT,
        )
        self.bids_selector.grid(row=1, column=1, sticky="ew", padx=(9, 18), pady=(0, 14))

        workflow = card(scroll)
        workflow.grid(row=4, column=0, sticky="ew", padx=6, pady=(0, 12))
        workflow.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="workflow")

        title(workflow, "4  Run the five-stage workflow", 17).grid(
            row=0, column=0, columnspan=5, sticky="w", padx=18, pady=(16, 4)
        )
        subtitle(
            workflow,
            "Review is deliberately required before metadata and BIDS conversion so defacing quality can be checked visually.",
            940,
        ).grid(row=1, column=0, columnspan=5, sticky="w", padx=18, pady=(0, 12))

        self.prepare_button = primary_button(workflow, "1. Prepare NIfTI", self._prepare_nifti)
        self.prepare_button.grid(row=2, column=0, sticky="ew", padx=(18, 4), pady=4)

        self.scrub_button = primary_button(workflow, "2. Scrub Headers", self._run_scrubber)
        self.scrub_button.grid(row=2, column=1, sticky="ew", padx=4, pady=4)

        self.deface_button = primary_button(workflow, "3. Deface", self._run_defacer)
        self.deface_button.grid(row=2, column=2, sticky="ew", padx=4, pady=4)

        self.review_button = primary_button(workflow, "4. Review", self._open_review)
        self.review_button.grid(row=2, column=3, sticky="ew", padx=4, pady=4)

        self.bids_button = primary_button(workflow, "5. Metadata & BIDS", self._open_bids)
        self.bids_button.grid(row=2, column=4, sticky="ew", padx=(4, 18), pady=4)

        actions = ctk.CTkFrame(workflow, fg_color="transparent")
        actions.grid(row=3, column=0, columnspan=5, sticky="ew", padx=18, pady=(9, 16))
        actions.grid_columnconfigure(0, weight=1)

        self.overwrite_checkbox = ctk.CTkCheckBox(
            actions,
            text="Overwrite existing stage outputs or exact BIDS outputs",
            variable=self.overwrite_var,
            text_color=Palette.TEXT,
            fg_color=Palette.PRIMARY,
            hover_color=Palette.PRIMARY_HOVER,
        )
        self.overwrite_checkbox.grid(row=0, column=0, sticky="w")

        self.save_settings_button = secondary_button(
            actions,
            "Save Folder Settings",
            self._save_folder_settings,
        )
        self.save_settings_button.grid(row=0, column=1, padx=(8, 0))

        self.stop_button = ctk.CTkButton(
            actions,
            text="Stop Current Operation",
            command=self._stop_current_operation,
            height=36,
            corner_radius=9,
            fg_color=Palette.DANGER,
            hover_color="#991B1B",
            state="disabled",
        )
        self.stop_button.grid(row=0, column=2, padx=(8, 0))

        log = card(scroll, fg_color=Palette.SURFACE_ALT)
        log.grid(row=5, column=0, sticky="ew", padx=6, pady=(0, 14))
        log.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(log, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            top,
            text="Pipeline log",
            text_color=Palette.TEXT,
            font=("Arial", 14, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            top,
            textvariable=self.status_var,
            text_color=Palette.MUTED,
            font=("Arial", 11),
        ).grid(row=0, column=1, sticky="e")

        self.log_text = tk.Text(
            log,
            wrap="word",
            height=10,
            state="disabled",
            bd=0,
            highlightthickness=0,
            background="#0F172A",
            foreground="#DCE5EF",
            insertbackground="#FFFFFF",
            font=("Courier", 10),
        )
        self.log_text.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))

        self._append_log(f"Dashboard ready. Settings file: {get_settings_path()}")


def main():
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.title("Imaging DeID Dashboard")
    root.geometry("1280x900")
    root.minsize(980, 720)

    app = ImagingDashboard(root)
    app.pack(fill="both", expand=True)
    root.protocol("WM_DELETE_WINDOW", app._close_dashboard)
    root.mainloop()


if __name__ == "__main__":
    main()
