"""PyWebView API mixin for local-only surgical follow-up tracking.

Add SurgicalFollowupApiMixin to the Python class that is exposed as
window.pywebview.api.
"""

from __future__ import annotations

from .surgical_followup import SurgicalFollowupStore


class SurgicalFollowupApiMixin:
    def _get_surgical_followup_store(self):
        store = getattr(
            self,
            "_surgical_followup_store",
            None,
        )

        if store is None:
            store = SurgicalFollowupStore()
            self._surgical_followup_store = store

        return store

    def metadata_save_real_surgery_date(
        self,
        site_id,
        patient_id,
        surgery_id,
        real_surgery_date,
    ):
        date_text = str(
            real_surgery_date or ""
        ).strip()

        return (
            self._get_surgical_followup_store()
            .save_real_surgery_date(
                site_id,
                patient_id,
                surgery_id,
                date_text,
            )
        )

    def metadata_get_real_surgery_date(
        self,
        site_id,
        patient_id,
        surgery_id,
    ):
        return (
            self._get_surgical_followup_store()
            .get_real_surgery_date(
                site_id,
                patient_id,
                surgery_id,
            )
        )

    def metadata_get_needs_attention(
        self,
        site_id,
    ):
        return (
            self._get_surgical_followup_store()
            .needs_attention(
                site_id,
            )
        )
