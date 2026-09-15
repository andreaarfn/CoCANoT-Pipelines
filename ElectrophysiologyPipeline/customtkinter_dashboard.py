#!/usr/bin/env python3
"""CustomTkinter presentation layer for the CoCANoT Electrophysiology pipeline.

Save this file as:
    ElectrophysiologyPipeline/customtkinter_dashboard.py

All processing, validation, EDF review, BIDS conversion, and persistence remain
implemented by ElectrophysiologyPipeline/dashboard.py.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from ElectrophysiologyPipeline.dashboard import (
    PipelineDashboard as LegacyPipelineDashboard,
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



class PipelineDashboard(LegacyPipelineDashboard):
    """Modern UI for the existing electrophysiology pipeline."""

    def show_home(self):
        if self.is_pipeline_running():
            messagebox.showwarning(
                "Pipeline busy",
                "Finish or stop the current operation before leaving the processing screen.",
                parent=self,
            )
            return

        self.clear_window()

        page = ctk.CTkFrame(self, fg_color=Palette.BG, corner_radius=0)
        page.pack(fill="both", expand=True)
        page.grid_columnconfigure((0, 1), weight=1, uniform="ephys")
        page.grid_rowconfigure(2, weight=1)

        nav = ctk.CTkFrame(page, fg_color="transparent")
        nav.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(18, 4))
        if self.on_back is not None:
            secondary_button(nav, "← Back", self.return_to_cocanot, width=88).pack(side="left")

        heading = ctk.CTkFrame(page, fg_color="transparent")
        heading.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=(6, 18))
        title(heading, "Electrophysiology", 28).pack(anchor="w")
        subtitle(
            heading,
            "De-identify EDF recordings, review scrubbed metadata, and produce validated BIDS datasets.",
        ).pack(anchor="w", pady=(4, 0))

        process = card(page)
        process.grid(row=2, column=0, sticky="nsew", padx=(20, 9), pady=(0, 20))
        process.grid_columnconfigure(0, weight=1)
        process.grid_rowconfigure(3, weight=1)

        badge = ctk.CTkFrame(process, width=52, height=52, corner_radius=13, fg_color=Palette.SOFT_BLUE)
        badge.grid(row=0, column=0, sticky="w", padx=18, pady=(18, 12))
        badge.grid_propagate(False)
        ctk.CTkLabel(badge, text="EEG", text_color=Palette.PRIMARY, font=("Arial", 15, "bold")).place(
            relx=.5, rely=.5, anchor="center"
        )
        title(process, "Process recordings", 19).grid(row=1, column=0, sticky="w", padx=18)
        subtitle(
            process,
            "Add EDF sources, choose recordings, scrub identifying headers, review the result, and convert accepted files to BIDS.",
            440,
        ).grid(row=2, column=0, sticky="nw", padx=18, pady=(8, 18))
        primary_button(process, "Open Processing Workspace", self.show_processing).grid(
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
            "Open the consolidated patient workspace to review saved electrophysiology records alongside other CoCANoT metadata.",
            440,
        ).grid(row=2, column=0, sticky="nw", padx=18, pady=(8, 18))
        secondary_button(review, "Open Patient Review", self.open_patient_explorer).grid(
            row=4, column=0, sticky="ew", padx=18, pady=(0, 18)
        )

    def build_interface(self):
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

        title(header, "Electrophysiology Processing", 26).grid(row=0, column=0, sticky="w")
        subtitle(
            header,
            "Work from top to bottom. Source selection and output settings are saved separately from pipeline execution.",
            980,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        secondary_button(header, "← Back", self.leave_processing, width=88).grid(
            row=0, column=1, rowspan=2, sticky="e"
        )

        setup = card(scroll)
        setup.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 12))
        setup.grid_columnconfigure(0, weight=3)
        setup.grid_columnconfigure(1, weight=2)

        left = ctk.CTkFrame(setup, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(18, 9), pady=18)
        left.grid_columnconfigure(0, weight=1)

        title(left, "1  Add raw EDF sources", 17).grid(row=0, column=0, sticky="w")
        subtitle(
            left,
            "Add individual EDF files or whole folders. Double-click rows below to include or exclude recordings.",
            620,
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        list_host = tk.Frame(left, bg=Palette.SURFACE, highlightbackground=Palette.BORDER, highlightthickness=1)
        list_host.grid(row=2, column=0, sticky="ew")
        list_host.grid_columnconfigure(0, weight=1)

        self.folder_list = tk.Listbox(
            list_host,
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
        self.folder_list.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        self.folder_selection = ExtendedSelectionController(self.folder_list)

        source_actions = ctk.CTkFrame(left, fg_color="transparent")
        source_actions.grid(row=3, column=0, sticky="ew", pady=(9, 0))

        self.add_file_button = secondary_button(source_actions, "Add EDF Files…", self.add_input_files)
        self.add_file_button.pack(side="left")
        self.add_folder_button = secondary_button(source_actions, "Add Folders…", self.add_input_folder)
        self.add_folder_button.pack(side="left", padx=7)
        self.remove_folder_button = secondary_button(source_actions, "Remove", self.remove_input_folders)
        self.remove_folder_button.pack(side="left")

        right = ctk.CTkFrame(setup, fg_color=Palette.SURFACE_ALT, corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew", padx=(9, 18), pady=18)
        right.grid_columnconfigure(0, weight=1)

        title(right, "Output folders", 17).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 6))
        subtitle(
            right,
            "Choose where intermediate derivatives and final BIDS data should be written.",
            400,
        ).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))

        self.derivatives_selector = FolderSelector(
            right,
            "Derivatives output folder",
            self.derivatives_dir_var,
            "Select the derivatives output folder",
            PROJECT_ROOT,
        )
        self.derivatives_selector.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 9))

        self.bids_selector = FolderSelector(
            right,
            "BIDS output folder",
            self.bids_output_dir_var,
            "Select the BIDS output folder",
            PROJECT_ROOT,
        )
        self.bids_selector.grid(row=3, column=0, sticky="ew", padx=14)

        self.save_settings_button = secondary_button(
            right,
            "Save Folder Settings",
            lambda: self.save_folder_settings(),
        )
        self.save_settings_button.grid(row=4, column=0, sticky="ew", padx=14, pady=14)

        recordings = card(scroll)
        recordings.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 12))
        recordings.grid_columnconfigure(0, weight=1)

        title(recordings, "2  Choose recordings", 17).grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 4)
        )
        subtitle(
            recordings,
            "The table is populated from the sources above. Inclusion controls affect every downstream step.",
            900,
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 10))

        table_host = tk.Frame(recordings, bg=Palette.SURFACE)
        table_host.grid(row=2, column=0, sticky="ew", padx=18)
        table_host.grid_columnconfigure(0, weight=1)

        self.raw_tree = ttk.Treeview(
            table_host,
            columns=("include", "file", "source"),
            show="headings",
            selectmode="extended",
            height=11,
        )
        for column, heading, width in (
            ("include", "Include", 90),
            ("file", "File Name", 650),
            ("source", "Source", 380),
        ):
            self.raw_tree.heading(column, text=heading)
            self.raw_tree.column(column, width=width, anchor="w")
        self.raw_tree.grid(row=0, column=0, sticky="ew")
        self.raw_tree.bind("<Double-1>", self.toggle_raw_inclusion_at_pointer)

        y = ttk.Scrollbar(table_host, orient="vertical", command=self.raw_tree.yview)
        y.grid(row=0, column=1, sticky="ns")
        x = ttk.Scrollbar(table_host, orient="horizontal", command=self.raw_tree.xview)
        x.grid(row=1, column=0, sticky="ew")
        self.raw_tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.raw_tree_selection = ExtendedSelectionController(self.raw_tree)

        row_actions = ctk.CTkFrame(recordings, fg_color="transparent")
        row_actions.grid(row=3, column=0, sticky="ew", padx=18, pady=(9, 16))
        secondary_button(row_actions, "Include Selected", lambda: self.set_raw_selected(True)).pack(side="left")
        secondary_button(row_actions, "Exclude Selected", lambda: self.set_raw_selected(False)).pack(side="left", padx=7)
        secondary_button(row_actions, "Include All", lambda: self.set_raw_all(True)).pack(side="left", padx=(12, 7))
        secondary_button(row_actions, "Exclude All", lambda: self.set_raw_all(False)).pack(side="left")

        workflow = card(scroll)
        workflow.grid(row=3, column=0, sticky="ew", padx=6, pady=(0, 12))
        workflow.grid_columnconfigure((0, 1, 2), weight=1, uniform="steps")

        title(workflow, "3  Run the pipeline", 17).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(16, 4)
        )
        subtitle(
            workflow,
            "Each stage is intentionally separate so you can inspect the de-identification result before conversion.",
            940,
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 12))

        self.scrub_button = primary_button(workflow, "1. Scrub Included EDFs", self.run_scrubber)
        self.scrub_button.grid(row=2, column=0, sticky="ew", padx=(18, 6), pady=4)

        self.compare_button = primary_button(workflow, "2. Review Scrubbed EDFs", self.launch_comparison)
        self.compare_button.grid(row=2, column=1, sticky="ew", padx=6, pady=4)

        self.bids_button = primary_button(workflow, "3. Metadata & BIDS", self.open_bids_metadata_review)
        self.bids_button.grid(row=2, column=2, sticky="ew", padx=(6, 18), pady=4)

        self.stop_button = ctk.CTkButton(
            workflow,
            text="Stop Current Operation",
            command=self.stop_current_operation,
            height=36,
            corner_radius=9,
            fg_color=Palette.DANGER,
            hover_color="#991B1B",
            state="disabled",
        )
        self.stop_button.grid(row=3, column=0, columnspan=3, sticky="ew", padx=18, pady=(8, 6))

        self.overwrite_checkbox = ctk.CTkCheckBox(
            workflow,
            text="Overwrite existing staged, scrubbed, or exact BIDS outputs",
            variable=self.overwrite_var,
            text_color=Palette.TEXT,
            fg_color=Palette.PRIMARY,
            hover_color=Palette.PRIMARY_HOVER,
        )
        self.overwrite_checkbox.grid(row=4, column=0, columnspan=3, sticky="w", padx=18, pady=(4, 16))

        log = card(scroll, fg_color=Palette.SURFACE_ALT)
        log.grid(row=4, column=0, sticky="ew", padx=6, pady=(0, 14))
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

        if self.log_history:
            self.log_text.configure(state="normal")
            self.log_text.insert("1.0", "\n".join(self.log_history) + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        else:
            self.append_log(f"Dashboard ready. Settings file: {get_settings_path()}")


def main():
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.title("Electrophysiology DeID Dashboard")
    root.geometry("1280x900")
    root.minsize(980, 700)

    app = PipelineDashboard(root)
    app.pack(fill="both", expand=True)
    root.protocol("WM_DELETE_WINDOW", app.close_dashboard)
    root.mainloop()


if __name__ == "__main__":
    main()
