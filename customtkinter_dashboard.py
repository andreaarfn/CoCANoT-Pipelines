#!/usr/bin/env python3
"""Modern CustomTkinter shell for the unified CoCANoT application.

This file intentionally keeps the existing Imaging, Electrophysiology, and
Metadata dashboard implementations intact.  It replaces the top-level
application/navigation shell with a modern CustomTkinter interface and applies
a coordinated ttk theme so legacy ttk widgets blend into the new shell.

Install CustomTkinter if needed:
    pip install customtkinter
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

try:
    import customtkinter as ctk
except ImportError as exc:
    raise SystemExit(
        "CustomTkinter is required for customtkinter_dashboard.py.\n"
        "Install it in the active environment with:\n\n"
        "    pip install customtkinter"
    ) from exc

from app.home import CoCANoTHome
from app.site_access import SiteAccessView
from MetadataPipeline.storage import LocalMetadataStore


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


class Palette:
    APP_BG = "#F4F7FB"
    SIDEBAR = "#10243E"
    SIDEBAR_HOVER = "#1C3655"
    SIDEBAR_ACTIVE = "#244B75"
    SIDEBAR_MUTED = "#A7B7CA"

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

    INPUT = "#F8FAFC"
    TABLE_HEADER = "#EAF0F7"
    TABLE_SELECTED = "#DCEAFF"


class Typography:
    BRAND = ("Arial", 22, "bold")
    PAGE_TITLE = ("Arial", 24, "bold")
    SECTION = ("Arial", 16, "bold")
    BODY = ("Arial", 13)
    SMALL = ("Arial", 11)
    NAV = ("Arial", 13, "bold")


# ---------------------------------------------------------------------------
# Small reusable CTk components
# ---------------------------------------------------------------------------

class NavButton(ctk.CTkButton):
    """Sidebar button with consistent active/inactive styling."""

    def __init__(
        self,
        master,
        *,
        text: str,
        command: Callable[[], None],
        icon_text: str = "•",
    ) -> None:
        self._label = text
        self._icon_text = icon_text

        super().__init__(
            master,
            text=f"{icon_text}   {text}",
            command=command,
            anchor="w",
            height=42,
            corner_radius=9,
            border_width=0,
            fg_color="transparent",
            hover_color=Palette.SIDEBAR_HOVER,
            text_color="#FFFFFF",
            font=Typography.NAV,
        )

    def set_active(self, active: bool) -> None:
        self.configure(
            fg_color=Palette.SIDEBAR_ACTIVE if active else "transparent"
        )


class HeaderAction(ctk.CTkButton):
    def __init__(
        self,
        master,
        *,
        text: str,
        command: Callable[[], None],
        primary: bool = False,
    ) -> None:
        super().__init__(
            master,
            text=text,
            command=command,
            height=34,
            corner_radius=8,
            border_width=0 if primary else 1,
            border_color=Palette.BORDER,
            fg_color=Palette.PRIMARY if primary else Palette.SURFACE,
            hover_color=Palette.PRIMARY_HOVER if primary else Palette.SURFACE_ALT,
            text_color="#FFFFFF" if primary else Palette.TEXT,
            font=("Arial", 12, "bold"),
        )


class HomeCard(ctk.CTkFrame):
    """Large clickable home card."""

    def __init__(
        self,
        master,
        *,
        icon: str,
        title: str,
        description: str,
        button_text: str,
        command: Callable[[], None],
    ) -> None:
        super().__init__(
            master,
            fg_color=Palette.SURFACE,
            corner_radius=14,
            border_width=1,
            border_color=Palette.BORDER,
        )

        self.grid_columnconfigure(0, weight=1)

        icon_box = ctk.CTkFrame(
            self,
            width=48,
            height=48,
            corner_radius=12,
            fg_color="#EAF1FF",
        )
        icon_box.grid(row=0, column=0, sticky="w", padx=18, pady=(18, 10))
        icon_box.grid_propagate(False)

        ctk.CTkLabel(
            icon_box,
            text=icon,
            text_color=Palette.PRIMARY,
            font=("Arial", 20, "bold"),
        ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            self,
            text=title,
            text_color=Palette.TEXT,
            font=Typography.SECTION,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=18)

        ctk.CTkLabel(
            self,
            text=description,
            text_color=Palette.MUTED,
            font=Typography.BODY,
            justify="left",
            anchor="nw",
            wraplength=290,
        ).grid(row=2, column=0, sticky="nsew", padx=18, pady=(7, 14))

        self.grid_rowconfigure(2, weight=1)

        ctk.CTkButton(
            self,
            text=button_text,
            command=command,
            height=36,
            corner_radius=8,
            fg_color=Palette.PRIMARY,
            hover_color=Palette.PRIMARY_HOVER,
            font=("Arial", 12, "bold"),
        ).grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 18))


class ModernHome(ctk.CTkFrame):
    """CustomTkinter replacement for the unified landing page."""

    def __init__(
        self,
        master,
        *,
        site_id: str,
        on_imaging: Callable[[], None],
        on_ephys: Callable[[], None],
        on_metadata: Callable[[], None],
        on_review_patients: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")

        self.grid_columnconfigure((0, 1), weight=1, uniform="cards")
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self,
            text="Welcome to CoCANoT",
            text_color=Palette.TEXT,
            font=("Arial", 30, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(2, 4))

        ctk.CTkLabel(
            self,
            text=(
                f"Site {site_id}  •  Select a workspace to de-identify, review, "
                "validate, or manage study data."
            ),
            text_color=Palette.MUTED,
            font=Typography.BODY,
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 18))

        cards = (
            (
                "IMG",
                "Imaging",
                "Prepare, scrub, deface, visually review, and convert imaging data.",
                "Open Imaging",
                on_imaging,
            ),
            (
                "EEG",
                "Electrophysiology",
                "Scrub EDF metadata, review recordings, and create validated BIDS outputs.",
                "Open Electrophysiology",
                on_ephys,
            ),
            (
                "META",
                "Metadata Management",
                "Manage dictionary-driven clinical, surgical, imaging, and electrophysiology metadata.",
                "Open Metadata",
                on_metadata,
            ),
            (
                "PT",
                "Patient Data Review",
                "Review all locally stored records for a patient from one consolidated workspace.",
                "Review Patients",
                on_review_patients,
            ),
        )

        for index, (icon, title, description, action, command) in enumerate(cards):
            row = 2 + index // 2
            column = index % 2
            card = HomeCard(
                self,
                icon=icon,
                title=title,
                description=description,
                button_text=action,
                command=command,
            )
            card.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=(4 if column == 0 else 9, 9 if column == 0 else 4),
                pady=9,
            )
            self.grid_rowconfigure(row, weight=1)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class CoCANoTCustomApp(ctk.CTk):
    """Modern shell around the existing CoCANoT dashboards."""

    def __init__(self) -> None:
        super().__init__()

        self.title("CoCANoT")
        self.geometry("1460x940")
        self.minsize(1100, 760)
        self.configure(fg_color=Palette.APP_BG)

        self.active_site_id = ""
        self.current_page: Optional[tk.Widget] = None
        self.history: list[tk.Widget] = []
        self.current_route = ""

        self._configure_legacy_ttk_styles()
        self._build_shell()
        self.show_site_access()

    # ------------------------------------------------------------------
    # Global ttk styling
    # ------------------------------------------------------------------

    def _configure_legacy_ttk_styles(self) -> None:
        """Make existing ttk-based dashboards harmonize with the CTk shell."""

        style = ttk.Style(self)

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            ".",
            background=Palette.SURFACE,
            foreground=Palette.TEXT,
            font=("Arial", 11),
        )
        style.configure(
            "TFrame",
            background=Palette.SURFACE,
        )
        style.configure(
            "TLabel",
            background=Palette.SURFACE,
            foreground=Palette.TEXT,
            font=("Arial", 11),
        )
        style.configure(
            "TLabelframe",
            background=Palette.SURFACE,
            bordercolor=Palette.BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label",
            background=Palette.SURFACE,
            foreground=Palette.TEXT,
            font=("Arial", 11, "bold"),
        )
        style.configure(
            "TButton",
            padding=(12, 7),
            background=Palette.SURFACE_ALT,
            foreground=Palette.TEXT,
            borderwidth=1,
            relief="flat",
            font=("Arial", 10, "bold"),
        )
        style.map(
            "TButton",
            background=[
                ("active", "#E8EEF5"),
                ("pressed", "#DDE6F0"),
                ("disabled", "#F1F4F7"),
            ],
            foreground=[("disabled", "#9AA8B6")],
        )
        style.configure(
            "TEntry",
            fieldbackground=Palette.INPUT,
            foreground=Palette.TEXT,
            bordercolor=Palette.BORDER,
            lightcolor=Palette.BORDER,
            darkcolor=Palette.BORDER,
            padding=6,
        )
        style.configure(
            "TCombobox",
            fieldbackground=Palette.INPUT,
            foreground=Palette.TEXT,
            padding=5,
        )
        style.configure(
            "Treeview",
            background=Palette.SURFACE,
            fieldbackground=Palette.SURFACE,
            foreground=Palette.TEXT,
            rowheight=30,
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", Palette.TABLE_SELECTED)],
            foreground=[("selected", Palette.TEXT)],
        )
        style.configure(
            "Treeview.Heading",
            background=Palette.TABLE_HEADER,
            foreground=Palette.TEXT,
            font=("Arial", 10, "bold"),
            padding=(8, 8),
            relief="flat",
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#DEE8F3")],
        )
        style.configure(
            "Vertical.TScrollbar",
            background="#CBD5E1",
            troughcolor=Palette.SURFACE_ALT,
            borderwidth=0,
            arrowsize=12,
        )
        style.configure(
            "Horizontal.TScrollbar",
            background="#CBD5E1",
            troughcolor=Palette.SURFACE_ALT,
            borderwidth=0,
            arrowsize=12,
        )
        style.configure(
            "TCheckbutton",
            background=Palette.SURFACE,
            foreground=Palette.TEXT,
        )
        style.configure(
            "TRadiobutton",
            background=Palette.SURFACE,
            foreground=Palette.TEXT,
        )

        # Native Tk widgets used by the older dashboards inherit these.
        self.option_add("*Listbox.background", Palette.SURFACE)
        self.option_add("*Listbox.foreground", Palette.TEXT)
        self.option_add("*Listbox.selectBackground", Palette.TABLE_SELECTED)
        self.option_add("*Listbox.selectForeground", Palette.TEXT)
        self.option_add("*Listbox.highlightThickness", 1)
        self.option_add("*Listbox.highlightBackground", Palette.BORDER)
        self.option_add("*Text.background", Palette.SURFACE_ALT)
        self.option_add("*Text.foreground", Palette.TEXT)
        self.option_add("*Text.insertBackground", Palette.TEXT)
        self.option_add("*Canvas.background", Palette.SURFACE)

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------

    def _build_shell(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(
            self,
            width=240,
            corner_radius=0,
            fg_color=Palette.SIDEBAR,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(8, weight=1)

        brand = ctk.CTkFrame(
            self.sidebar,
            fg_color="transparent",
        )
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 20))
        brand.grid_columnconfigure(1, weight=1)

        logo = ctk.CTkFrame(
            brand,
            width=38,
            height=38,
            corner_radius=10,
            fg_color=Palette.PRIMARY,
        )
        logo.grid(row=0, column=0, rowspan=2, sticky="w")
        logo.grid_propagate(False)

        ctk.CTkLabel(
            logo,
            text="C",
            text_color="#FFFFFF",
            font=("Arial", 19, "bold"),
        ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            brand,
            text="CoCANoT",
            text_color="#FFFFFF",
            font=Typography.BRAND,
            anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(10, 0))

        ctk.CTkLabel(
            brand,
            text="De-ID & Validation",
            text_color=Palette.SIDEBAR_MUTED,
            font=("Arial", 10),
            anchor="w",
        ).grid(row=1, column=1, sticky="w", padx=(10, 0))

        self.nav_buttons: dict[str, NavButton] = {}

        nav_specs = (
            ("home", "Home", "⌂", self._show_home),
            ("imaging", "Imaging", "I", self._show_imaging),
            ("ephys", "Electrophysiology", "E", self._show_ephys),
            ("metadata", "Metadata", "M", self._show_metadata),
            ("patients", "Patient Review", "P", self._show_patient_review),
        )

        for row, (route, label, icon, command) in enumerate(nav_specs, start=1):
            button = NavButton(
                self.sidebar,
                text=label,
                icon_text=icon,
                command=command,
            )
            button.grid(row=row, column=0, sticky="ew", padx=12, pady=3)
            self.nav_buttons[route] = button

        self.site_card = ctk.CTkFrame(
            self.sidebar,
            fg_color="#162F4D",
            corner_radius=12,
        )
        self.site_card.grid(
            row=9,
            column=0,
            sticky="sew",
            padx=12,
            pady=(12, 8),
        )
        self.site_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.site_card,
            text="ACTIVE SITE",
            text_color=Palette.SIDEBAR_MUTED,
            font=("Arial", 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=13, pady=(12, 2))

        self.site_label = ctk.CTkLabel(
            self.site_card,
            text="Not signed in",
            text_color="#FFFFFF",
            font=("Arial", 14, "bold"),
            anchor="w",
        )
        self.site_label.grid(row=1, column=0, sticky="ew", padx=13, pady=(0, 12))

        self.sign_out_button = ctk.CTkButton(
            self.sidebar,
            text="Sign Out",
            command=self.show_site_access,
            height=36,
            corner_radius=8,
            fg_color="transparent",
            hover_color=Palette.SIDEBAR_HOVER,
            border_width=1,
            border_color="#35516F",
            text_color="#FFFFFF",
            font=("Arial", 11, "bold"),
        )
        self.sign_out_button.grid(
            row=10,
            column=0,
            sticky="ew",
            padx=12,
            pady=(0, 16),
        )

        self.main = ctk.CTkFrame(
            self,
            fg_color=Palette.APP_BG,
            corner_radius=0,
        )
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)

        self.topbar = ctk.CTkFrame(
            self.main,
            height=72,
            corner_radius=0,
            fg_color=Palette.SURFACE,
            border_width=0,
        )
        self.topbar.grid(row=0, column=0, sticky="ew")
        self.topbar.grid_propagate(False)
        self.topbar.grid_columnconfigure(0, weight=1)

        title_area = ctk.CTkFrame(self.topbar, fg_color="transparent")
        title_area.grid(row=0, column=0, sticky="w", padx=24, pady=12)

        self.page_title = ctk.CTkLabel(
            title_area,
            text="CoCANoT",
            text_color=Palette.TEXT,
            font=Typography.PAGE_TITLE,
            anchor="w",
        )
        self.page_title.pack(anchor="w")

        self.page_subtitle = ctk.CTkLabel(
            title_area,
            text="Clinical research data de-identification and validation",
            text_color=Palette.MUTED,
            font=Typography.SMALL,
            anchor="w",
        )
        self.page_subtitle.pack(anchor="w", pady=(1, 0))

        actions = ctk.CTkFrame(self.topbar, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e", padx=24, pady=12)

        self.back_button = HeaderAction(
            actions,
            text="← Back",
            command=self.go_back,
        )
        self.back_button.pack(side="left", padx=(0, 8))

        self.home_button = HeaderAction(
            actions,
            text="Home",
            command=self._show_home,
        )
        self.home_button.pack(side="left")

        self.content_shell = ctk.CTkFrame(
            self.main,
            fg_color=Palette.APP_BG,
            corner_radius=0,
        )
        self.content_shell.grid(row=1, column=0, sticky="nsew")
        self.content_shell.grid_columnconfigure(0, weight=1)
        self.content_shell.grid_rowconfigure(0, weight=1)

        self.content = ctk.CTkFrame(
            self.content_shell,
            fg_color=Palette.SURFACE,
            corner_radius=16,
            border_width=1,
            border_color=Palette.BORDER,
        )
        self.content.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=18,
            pady=18,
        )
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _set_route(
        self,
        route: str,
        title: str,
        subtitle: str,
    ) -> None:
        self.current_route = route
        self.page_title.configure(text=title)
        self.page_subtitle.configure(text=subtitle)

        for name, button in self.nav_buttons.items():
            button.set_active(name == route)

        has_site = bool(self.active_site_id)
        self.sidebar.grid() if has_site else self.sidebar.grid_remove()

        self.site_label.configure(
            text=self.active_site_id if self.active_site_id else "Not signed in"
        )

        self.back_button.configure(
            state="normal" if self.history else "disabled"
        )

    def _destroy_navigation(self) -> None:
        if self.current_page is not None:
            try:
                self.current_page.destroy()
            except tk.TclError:
                pass
            self.current_page = None

        for page in self.history:
            try:
                if page.winfo_exists():
                    page.destroy()
            except tk.TclError:
                pass

        self.history = []
        self.back_button.configure(state="disabled")

    def _mount(self, page: tk.Widget) -> None:
        self.current_page = page

        # grid works for Tk, ttk, and CTk widgets.
        try:
            page.grid(row=0, column=0, sticky="nsew")
        except tk.TclError:
            page.pack(fill="both", expand=True)

    def _navigate(
        self,
        factory: Callable[[], tk.Widget],
        *,
        remember: bool = True,
    ) -> None:
        previous = self.current_page

        if previous is not None:
            try:
                previous.grid_remove()
            except tk.TclError:
                try:
                    previous.pack_forget()
                except tk.TclError:
                    pass

            if remember:
                self.history.append(previous)
            else:
                previous.destroy()

        try:
            page = factory()
        except Exception:
            if previous is not None:
                try:
                    if previous.winfo_exists():
                        if remember and self.history and self.history[-1] is previous:
                            self.history.pop()
                        self._mount(previous)
                except tk.TclError:
                    pass

            raise

        self._mount(page)
        self.back_button.configure(
            state="normal" if self.history else "disabled"
        )

    # ------------------------------------------------------------------
    # Site access
    # ------------------------------------------------------------------

    def show_site_access(self) -> None:
        self._destroy_navigation()
        self.active_site_id = ""
        self.site_label.configure(text="Not signed in")

        # Hide navigation chrome during site access.
        self.sidebar.grid_remove()
        self.page_title.configure(text="Site Access")
        self.page_subtitle.configure(
            text="Select or authenticate the CoCANoT site for this installation"
        )
        self.back_button.configure(state="disabled")
        self.home_button.configure(state="disabled")

        holder = ctk.CTkFrame(
            self.content,
            fg_color="transparent",
        )
        holder.grid(row=0, column=0, sticky="nsew")
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)

        card = ctk.CTkFrame(
            holder,
            width=560,
            height=520,
            fg_color=Palette.SURFACE,
            corner_radius=18,
            border_width=1,
            border_color=Palette.BORDER,
        )
        card.place(relx=0.5, rely=0.5, anchor="center")
        card.grid_propagate(False)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(2, weight=1)

        badge = ctk.CTkFrame(
            card,
            width=54,
            height=54,
            corner_radius=14,
            fg_color="#EAF1FF",
        )
        badge.grid(row=0, column=0, pady=(30, 10))
        badge.grid_propagate(False)

        ctk.CTkLabel(
            badge,
            text="C",
            text_color=Palette.PRIMARY,
            font=("Arial", 25, "bold"),
        ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            card,
            text="CoCANoT Site Access",
            text_color=Palette.TEXT,
            font=("Arial", 24, "bold"),
        ).grid(row=1, column=0, pady=(0, 10))

        legacy_host = tk.Frame(card, bg=Palette.SURFACE, bd=0, highlightthickness=0)
        legacy_host.grid(row=2, column=0, sticky="nsew", padx=28, pady=(4, 28))

        self.current_page = holder

        # Keep your existing access/authentication behavior.
        legacy_view = SiteAccessView(
            legacy_host,
            on_success=self._site_authenticated,
        )
        legacy_view.pack(fill="both", expand=True)

    def _site_authenticated(self, site_id) -> None:
        site_id = str(site_id or "").strip().upper()

        if not site_id:
            messagebox.showerror(
                "Site required",
                "A valid Site ID is required.",
                parent=self,
            )
            return

        LocalMetadataStore().set_site_id(site_id)
        self.active_site_id = site_id
        self.site_label.configure(text=site_id)

        if self.current_page is not None:
            self.current_page.destroy()
            self.current_page = None

        self.sidebar.grid()
        self.home_button.configure(state="normal")
        self._show_home(remember=False)

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def _show_home(self, remember: bool = True) -> None:
        if not self.active_site_id:
            return

        self._set_route(
            "home",
            "Home",
            "Choose a CoCANoT workspace",
        )
        self._navigate(self._make_home, remember=remember)

    def _show_imaging(self) -> None:
        if not self.active_site_id:
            return

        self._set_route(
            "imaging",
            "Imaging",
            "De-identification, visual review, metadata, and BIDS conversion",
        )
        self._navigate(self._make_imaging)

    def _show_ephys(self) -> None:
        if not self.active_site_id:
            return

        self._set_route(
            "ephys",
            "Electrophysiology",
            "EDF de-identification, review, metadata, and BIDS conversion",
        )
        self._navigate(self._make_ephys)

    def _show_metadata(self) -> None:
        if not self.active_site_id:
            return

        self._set_route(
            "metadata",
            "Metadata Management",
            "Dictionary-driven metadata entry, validation, and review",
        )
        self._navigate(self._make_metadata)

    def _show_patient_review(self) -> None:
        if not self.active_site_id:
            return

        self._set_route(
            "patients",
            "Patient Data Review",
            "Review a patient's clinical, surgical, imaging, and electrophysiology records",
        )
        self._navigate(self._make_patient_review)

    def _show_imaging_processing(self) -> None:
        self._set_route(
            "imaging",
            "Imaging Processing",
            "Prepare, de-identify, review, and convert imaging data",
        )
        self._navigate(self._make_imaging_processing)

    def _show_ephys_processing(self) -> None:
        self._set_route(
            "ephys",
            "Electrophysiology Processing",
            "Scrub, review, validate, and convert electrophysiology data",
        )
        self._navigate(self._make_ephys_processing)

    def go_back(self) -> None:
        if not self.history:
            return

        if self.current_page is not None:
            try:
                self.current_page.destroy()
            except tk.TclError:
                pass

        self.current_page = self.history.pop()
        self._mount(self.current_page)

        self.back_button.configure(
            state="normal" if self.history else "disabled"
        )

    # ------------------------------------------------------------------
    # Page factories
    # ------------------------------------------------------------------

    def _make_home(self) -> tk.Widget:
        return ModernHome(
            self.content,
            site_id=self.active_site_id,
            on_imaging=self._show_imaging,
            on_ephys=self._show_ephys,
            on_metadata=self._show_metadata,
            on_review_patients=self._show_patient_review,
        )

    def _make_imaging(self) -> tk.Widget:
        from ImagingPipeline.customtkinter_dashboard import ImagingDashboard

        return ImagingDashboard(
            self.content,
            site_id=self.active_site_id,
            on_back=self.go_back,
            on_review_patients=self._show_patient_review,
        )

    def _make_ephys(self) -> tk.Widget:
        from ElectrophysiologyPipeline.customtkinter_dashboard import PipelineDashboard

        return PipelineDashboard(
            self.content,
            site_id=self.active_site_id,
            on_back=self.go_back,
            on_review_patients=self._show_patient_review,
        )

    def _make_imaging_processing(self) -> tk.Widget:
        from ImagingPipeline.customtkinter_dashboard import ImagingDashboard

        return ImagingDashboard(
            self.content,
            site_id=self.active_site_id,
            on_back=self.go_back,
            on_review_patients=self._show_patient_review,
            initial_view="processing",
            processing_return=self.go_back,
        )

    def _make_ephys_processing(self) -> tk.Widget:
        from ElectrophysiologyPipeline.customtkinter_dashboard import PipelineDashboard

        return PipelineDashboard(
            self.content,
            site_id=self.active_site_id,
            on_back=self.go_back,
            on_review_patients=self._show_patient_review,
            initial_view="processing",
            processing_return=self.go_back,
        )

    def _make_metadata(self) -> tk.Widget:
        from MetadataPipeline.customtkinter_dashboard import MetadataDashboard

        return MetadataDashboard(
            self.content,
            site_id=self.active_site_id,
            on_back=self.go_back,
            initial_view="home",
            on_open_imaging=self._show_imaging_processing,
            on_open_electrophysiology=self._show_ephys_processing,
        )

    def _make_patient_review(self) -> tk.Widget:
        from MetadataPipeline.customtkinter_dashboard import MetadataDashboard

        return MetadataDashboard(
            self.content,
            site_id=self.active_site_id,
            on_back=self.go_back,
            initial_view="patient_explorer",
            on_open_imaging=self._show_imaging_processing,
            on_open_electrophysiology=self._show_ephys_processing,
        )


def main() -> None:
    app = CoCANoTCustomApp()
    app.mainloop()


if __name__ == "__main__":
    main()
