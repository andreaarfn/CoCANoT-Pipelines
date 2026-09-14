"""Reusable record table for the Metadata Dashboard."""

from __future__ import annotations

from tkinter import ttk


class RecordTable(ttk.LabelFrame):
    """Small table used to display one metadata record type."""

    def __init__(
        self,
        parent,
        title,
        on_open=None,
        add_text=None,
        on_add=None,
        secondary_add_text=None,
        on_secondary_add=None,
        open_text="Review / Edit Selected",
        on_delete=None,
        delete_text="Delete Selected",
    ):
        super().__init__(
            parent,
            text=title,
            padding=8,
        )
        self.on_open = on_open
        self.on_add = on_add
        self.on_secondary_add = on_secondary_add
        self.on_delete = on_delete
        self.records = {}

        self.columnconfigure(
            0,
            weight=1,
        )

        self.tree = ttk.Treeview(
            self,
            columns=(
                "record_id",
                "summary",
                "updated",
            ),
            show="headings",
            selectmode="browse",
            height=4,
        )
        self.tree.heading(
            "record_id",
            text="Record",
        )
        self.tree.heading(
            "summary",
            text="Summary",
        )
        self.tree.heading(
            "updated",
            text="Updated",
        )
        self.tree.column(
            "record_id",
            width=150,
            anchor="w",
        )
        self.tree.column(
            "summary",
            width=430,
            anchor="w",
        )
        self.tree.column(
            "updated",
            width=180,
            anchor="w",
        )
        self.tree.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        self.tree.bind(
            "<Double-1>",
            self._open_selected,
        )

        scroll = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.tree.yview,
        )
        scroll.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        self.tree.configure(
            yscrollcommand=scroll.set,
        )

        actions = ttk.Frame(
            self
        )
        actions.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(6, 0),
        )

        if (
            add_text
            and on_add is not None
        ):
            ttk.Button(
                actions,
                text=add_text,
                command=on_add,
            ).pack(
                side="left",
            )

        if (
            secondary_add_text
            and on_secondary_add is not None
        ):
            ttk.Button(
                actions,
                text=secondary_add_text,
                command=on_secondary_add,
            ).pack(
                side="left",
                padx=(6, 0),
            )

        if on_open is not None:
            ttk.Button(
                actions,
                text=open_text,
                command=self._open_selected,
            ).pack(
                side="right",
            )

        if on_delete is not None:
            ttk.Button(
                actions,
                text=delete_text,
                command=self._delete_selected,
            ).pack(
                side="right",
                padx=(0, 6),
            )

    def set_records(
        self,
        records,
        summary_builder,
    ):
        self.records = {}

        for item_id in self.tree.get_children():
            self.tree.delete(
                item_id
            )

        for index, record in enumerate(
            records,
            start=1,
        ):
            item_id = f"record-{index}"
            self.records[
                item_id
            ] = record

            updated = str(
                record.get(
                    "updated_at"
                )
                or ""
            )
            if "T" in updated:
                updated = updated.split(
                    "T",
                    1,
                )[0]

            self.tree.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    record.get(
                        "record_id",
                        "",
                    ),
                    summary_builder(
                        record
                    ),
                    updated,
                ),
            )

    def selected_record(self):
        selected = self.tree.selection()

        if not selected:
            return None

        return self.records.get(
            selected[0]
        )

    def _open_selected(
        self,
        _event=None,
    ):
        if self.on_open is None:
            return

        record = self.selected_record()

        if record is None:
            return

        self.on_open(
            record
        )


    def _delete_selected(
        self,
    ):
        if self.on_delete is None:
            return

        record = self.selected_record()

        if record is None:
            return

        self.on_delete(
            record
        )
