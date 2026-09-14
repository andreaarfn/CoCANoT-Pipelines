#!/usr/bin/env python3
"""Unified CoCANoT application with browser-style navigation."""

from __future__ import annotations

import tkinter as tk

from app.home import CoCANoTHome
from app.site_access import SiteAccessView
from MetadataPipeline.storage import LocalMetadataStore


class CoCANoTApp(tk.Tk):
    """Own the single CoCANoT application window and navigation history."""

    def __init__(self):
        super().__init__()

        self.title("CoCANoT")
        self.geometry("1320x920")
        self.minsize(980, 720)

        self.active_site_id = ""
        self.current_page = None
        self.history = []

        self.container = tk.Frame(self)
        self.container.pack(fill="both", expand=True)

        self.show_site_access()

    def _destroy_navigation(self):
        if self.current_page is not None:
            self.current_page.destroy()
            self.current_page = None

        for page in self.history:
            if page.winfo_exists():
                page.destroy()

        self.history = []

    def show_site_access(self):
        self._destroy_navigation()
        self.active_site_id = ""

        self.current_page = SiteAccessView(
            self.container,
            on_success=self._site_authenticated,
        )
        self.current_page.pack(fill="both", expand=True)

    def _site_authenticated(self, site_id):
        site_id = str(site_id or "").strip().upper()

        LocalMetadataStore().set_site_id(site_id)
        self.active_site_id = site_id

        if self.current_page is not None:
            self.current_page.destroy()
            self.current_page = None

        self._show_home(remember=False)

    def _show_home(self, remember=True):
        self._navigate(self._make_home, remember=remember)

    def _show_imaging(self):
        self._navigate(self._make_imaging)

    def _show_ephys(self):
        self._navigate(self._make_ephys)

    def _show_metadata(self):
        self._navigate(self._make_metadata)

    def _show_patient_review(self):
        self._navigate(self._make_patient_review)

    def _navigate(self, factory, remember=True):
        previous = self.current_page

        if previous is not None:
            previous.pack_forget()

            if remember:
                self.history.append(previous)
            else:
                previous.destroy()

        try:
            page = factory()
        except Exception:
            if previous is not None and previous.winfo_exists():
                if remember and self.history and self.history[-1] is previous:
                    self.history.pop()

                previous.pack(fill="both", expand=True)
                self.current_page = previous

            raise

        self.current_page = page
        page.pack(fill="both", expand=True)

    def go_back(self):
        if not self.history:
            return

        if self.current_page is not None:
            self.current_page.destroy()

        self.current_page = self.history.pop()
        self.current_page.pack(fill="both", expand=True)

    def _make_home(self):
        return CoCANoTHome(
            self.container,
            site_id=self.active_site_id,
            on_imaging=self._show_imaging,
            on_ephys=self._show_ephys,
            on_metadata=self._show_metadata,
            on_review_patients=self._show_patient_review,
            on_sign_out=self.show_site_access,
        )

    def _make_imaging(self):
        from ImagingPipeline.dashboard import ImagingDashboard

        return ImagingDashboard(
            self.container,
            site_id=self.active_site_id,
            on_back=self.go_back,
            on_review_patients=self._show_patient_review,
        )

    def _make_ephys(self):
        from ElectrophysiologyPipeline.dashboard import PipelineDashboard

        return PipelineDashboard(
            self.container,
            site_id=self.active_site_id,
            on_back=self.go_back,
            on_review_patients=self._show_patient_review,
        )

    def _make_metadata(self):
        from MetadataPipeline.dashboard import MetadataDashboard

        return MetadataDashboard(
            self.container,
            site_id=self.active_site_id,
            on_back=self.go_back,
            initial_view="home",
        )

    def _make_patient_review(self):
        from MetadataPipeline.dashboard import MetadataDashboard

        return MetadataDashboard(
            self.container,
            site_id=self.active_site_id,
            on_back=self.go_back,
            initial_view="patient_explorer",
        )


def main():
    app = CoCANoTApp()
    app.mainloop()


if __name__ == "__main__":
    main()
