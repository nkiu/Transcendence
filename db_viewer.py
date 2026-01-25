#!/usr/bin/env python3
import json
import sqlite3
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class DBViewer(tk.Tk):
    def __init__(self, db_path: Optional[str] = None) -> None:
        super().__init__()
        self.title("Transcendence DB Viewer")
        self.geometry("1100x700")
        self.conn: Optional[sqlite3.Connection] = None
        self.db_path = ""
        self.mapping: Dict[str, str] = {}
        self.table_columns: Dict[str, List[str]] = {}
        self.civ_cache: Dict[int, Dict[str, object]] = {}
        self.cycles_cache: List[int] = []
        self.cycle_name_cache: Dict[int, str] = {}
        self.mission_cycle_cache: Dict[str, set] = {}

        self._build_ui()
        if db_path:
            self._open_db(db_path)

    def _build_ui(self) -> None:
        top = tk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        tk.Button(top, text="Open DB", command=self._open_dialog).pack(side="left")
        self.db_label = tk.Label(top, text="No database loaded")
        self.db_label.pack(side="left", padx=8)

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=6)

        top = tk.Frame(body)
        top.pack(fill="x")

        bottom = tk.PanedWindow(body, orient="horizontal")
        bottom.pack(fill="both", expand=True, pady=(6, 0))

        left = tk.Frame(bottom)
        bottom.add(left, stretch="never")

        right = tk.Frame(bottom)
        bottom.add(right, stretch="always")

        tk.Label(left, text="Civilization").pack(anchor="w")
        self.civ_combo = ttk.Combobox(left, state="readonly", width=28)
        self.civ_combo.pack(fill="x", pady=(0, 6))
        self.civ_combo.bind("<<ComboboxSelected>>", self._on_civ_selected)

        tk.Label(left, text="Cycles").pack(anchor="w")
        self.cycle_list = tk.Listbox(left, height=25)
        self.cycle_list.pack(fill="both", expand=True)
        self.cycle_list.bind("<<ListboxSelect>>", self._on_cycle_selected)

        stats_frame = tk.LabelFrame(top, text="Stats")
        stats_frame.pack(fill="x", expand=False)
        self.stats_grid = stats_frame

        self.stats_labels: Dict[str, tk.Label] = {}
        self._init_stats_grid()

        right_tabs = ttk.Notebook(right)
        right_tabs.pack(fill="both", expand=True)

        self.narrative_tab = tk.Frame(right_tabs)
        self.events_tab = tk.Frame(right_tabs)
        self.raw_tab = tk.Frame(right_tabs)
        right_tabs.add(self.narrative_tab, text="Narrative")
        right_tabs.add(self.events_tab, text="Events")
        right_tabs.add(self.raw_tab, text="Raw")

        self.narrative_text = tk.Text(self.narrative_tab, wrap="word")
        self.narrative_text.pack(fill="both", expand=True)

        self.events_tree = ttk.Treeview(
            self.events_tab,
            columns=("kind", "title", "detail"),
            show="headings",
            height=12,
        )
        self.events_tree.heading("kind", text="Kind")
        self.events_tree.heading("title", text="Title")
        self.events_tree.heading("detail", text="Detail")
        self.events_tree.column("kind", width=90)
        self.events_tree.column("title", width=200)
        self.events_tree.column("detail", width=300)
        self.events_tree.pack(fill="both", expand=True)

        self.raw_text = tk.Text(self.raw_tab, wrap="word")
        self.raw_text.pack(fill="both", expand=True)

        plot_row = tk.Frame(self)
        plot_row.pack(fill="x", padx=8, pady=(0, 6))
        tk.Button(plot_row, text="Show plots", command=self._show_plots).pack(
            side="left"
        )

        self.status_var = tk.StringVar(value="Ready")
        status = tk.Label(self, textvariable=self.status_var, anchor="w")
        status.pack(fill="x", padx=8, pady=(0, 6))

    def _init_stats_grid(self) -> None:
        fields = [
            "stage",
            "progress",
            "cohesion",
            "inequality",
            "eco_pressure",
            "innovation",
            "stability",
            "food_security",
            "health",
            "elite_power",
            "legitimacy",
            "extraction_rate",
            "agenda",
            "stance",
            "news",
            "known_systems",
            "contacts",
            "missions",
        ]
        for idx, field in enumerate(fields):
            row = idx // 2
            col = (idx % 2) * 2
            tk.Label(self.stats_grid, text=field).grid(row=row, column=col, sticky="w")
            lbl = tk.Label(self.stats_grid, text="—")
            lbl.grid(row=row, column=col + 1, sticky="w", padx=(6, 12))
            self.stats_labels[field] = lbl

    def _open_dialog(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Transcendence DB",
            filetypes=[("SQLite DB", "*.db"), ("All files", "*.*")],
        )
        if path:
            self._open_db(path)

    def _open_db(self, path: str) -> None:
        try:
            if self.conn:
                self.conn.close()
            self.conn = sqlite3.connect(path)
            self.conn.row_factory = sqlite3.Row
            self.db_path = path
            self.db_label.configure(text=path)
            self.mission_cycle_cache.clear()
            self._introspect_schema()
            self._populate_civs()
            self._populate_cycles()
            self.status_var.set(f"Loaded {path}")
        except Exception as exc:
            messagebox.showerror("DB Error", str(exc))
            self.status_var.set("Failed to load DB")

    def _introspect_schema(self) -> None:
        if not self.conn:
            return
        cur = self.conn.cursor()
        tables = [
            row[0]
            for row in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        self.table_columns = {}
        for table in tables:
            cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
            self.table_columns[table] = cols

        mapping = {}
        mapping["civilizations"] = self._find_table(
            ["civilizations"], ["id", "name", "tech_stage"]
        )
        mapping["events"] = self._find_table(["events"], ["cycle", "title"])
        mapping["ai_logs"] = self._find_table(["ai_logs"], ["scope", "cycle"])
        mapping["cycle_records"] = self._find_table(
            ["cycle_records"], ["cycle", "record_json"]
        )
        mapping["cycles"] = self._find_table(["cycles"], ["id", "summary"])
        self.mapping = mapping

        if not mapping.get("civilizations"):
            messagebox.showwarning(
                "Schema Warning",
                "Civilizations table not detected. Viewer may be limited.",
            )
        if not mapping.get("events"):
            messagebox.showwarning(
                "Schema Warning",
                "Events table not detected. Events view may be empty.",
            )
        if not mapping.get("cycle_records"):
            self.status_var.set("cycle_records not found; timeline limited")

    def _find_table(self, names: List[str], required_cols: List[str]) -> Optional[str]:
        for name in names:
            if name in self.table_columns:
                if all(col in self.table_columns[name] for col in required_cols):
                    return name
        for table, cols in self.table_columns.items():
            if all(col in cols for col in required_cols):
                return table
        return None

    def _populate_civs(self) -> None:
        self.civ_cache.clear()
        table = self.mapping.get("civilizations")
        if not table or not self.conn:
            return
        cur = self.conn.cursor()
        civs = cur.execute(
            f"SELECT id, name FROM {table} ORDER BY id"
        ).fetchall()
        entries = []
        for row in civs:
            self.civ_cache[int(row[0])] = {"id": int(row[0]), "name": row[1]}
            entries.append(f"{row[0]}: {row[1]}")
        entries.insert(0, "MASTER")
        self.civ_combo.configure(values=entries)
        if entries:
            self.civ_combo.set(entries[0])

    def _populate_cycles(self) -> None:
        self.cycle_list.delete(0, tk.END)
        self.cycles_cache = []
        if not self.conn:
            return
        civ_id = self._selected_civ_id()
        mission_cycles = self._mission_cycles_for(civ_id)
        self.cycle_name_cache = self._load_cycle_names()
        table = self.mapping.get("cycle_records") or self.mapping.get("cycles")
        if not table:
            return
        cur = self.conn.cursor()
        rows = cur.execute(f"SELECT cycle FROM {table} ORDER BY cycle").fetchall()
        if not rows and table == self.mapping.get("cycles"):
            rows = cur.execute(f"SELECT id FROM {table} ORDER BY id").fetchall()
        for row in rows:
            cycle = int(row[0])
            self.cycles_cache.append(cycle)
            name = self.cycle_name_cache.get(cycle, "")
            label = f"Cycle {cycle}"
            if name:
                label = f"{label} — {name}"
            if cycle in mission_cycles:
                label = f"(M) {label}"
            self.cycle_list.insert(tk.END, label)

    def _on_civ_selected(self, _event=None) -> None:
        self._populate_cycles()
        self._refresh_for_selection()

    def _on_cycle_selected(self, _event=None) -> None:
        self._refresh_for_selection()

    def _selected_civ_id(self) -> Optional[object]:
        raw = self.civ_combo.get()
        if not raw:
            return None
        if raw.strip().upper() == "MASTER":
            return "MASTER"
        try:
            return int(raw.split(":", 1)[0])
        except ValueError:
            return None

    def _selected_cycle(self) -> Optional[int]:
        selection = self.cycle_list.curselection()
        if not selection:
            return None
        idx = selection[0]
        try:
            return self.cycles_cache[idx]
        except IndexError:
            return None

    def _refresh_for_selection(self) -> None:
        civ_id = self._selected_civ_id()
        cycle = self._selected_cycle()
        if civ_id is None or cycle is None:
            return
        self._load_stats(civ_id, cycle)
        self._load_events(civ_id, cycle)
        self._load_narrative(civ_id, cycle)

    def _load_stats(self, civ_id: object, cycle: int) -> None:
        if civ_id == "MASTER":
            self._clear_stats()
            return
        record = self._get_cycle_record(cycle)
        if not record:
            self._clear_stats()
            return
        civ_entry = None
        for civ in record.get("civilizations", []):
            if str(civ.get("civ_id")) == str(civ_id):
                civ_entry = civ
                break
        if not civ_entry:
            self._clear_stats()
            return
        stats = civ_entry.get("stats", {})
        self._set_stat("stage", civ_entry.get("stage", "—"))
        progress = civ_entry.get("progress")
        self._set_stat("progress", progress if progress is not None else "—")
        for key in (
            "cohesion",
            "inequality",
            "eco_pressure",
            "innovation",
            "stability",
            "food_security",
            "health",
            "elite_power",
            "legitimacy",
            "extraction_rate",
        ):
            self._set_stat(key, stats.get(key, "—"))
        narrative = civ_entry.get("narrative", {})
        self._set_stat("agenda", narrative.get("agenda", "—"))
        self._set_stat("stance", narrative.get("stance", "—"))
        self._set_stat("news", narrative.get("news", "—"))
        self._set_stat("known_systems", len(civ_entry.get("known_systems", [])))
        self._set_stat("contacts", len(civ_entry.get("known_contacts", [])))
        self._set_stat("missions", len(civ_entry.get("missions", [])))

        self.raw_text.delete("1.0", tk.END)
        self.raw_text.insert(tk.END, json.dumps(civ_entry, indent=2))

    def _load_events(self, civ_id: object, cycle: int) -> None:
        for item in self.events_tree.get_children():
            self.events_tree.delete(item)
        table = self.mapping.get("events")
        if not table or not self.conn:
            return
        cur = self.conn.cursor()
        rows = cur.execute(
            f"SELECT kind, title, detail, metadata_json FROM {table} WHERE cycle = ?",
            (cycle,),
        ).fetchall()
        for row in rows:
            meta = {}
            try:
                meta = json.loads(row[3])
            except json.JSONDecodeError:
                meta = {}
            if civ_id != "MASTER":
                target = str(meta.get("target", ""))
                if target and target != str(civ_id):
                    continue
            self.events_tree.insert("", "end", values=(row[0], row[1], row[2]))

    def _load_narrative(self, civ_id: object, cycle: int) -> None:
        self.narrative_text.delete("1.0", tk.END)
        record = self._get_cycle_record(cycle)
        if civ_id == "MASTER":
            if record:
                master = record.get("master", {})
                text = (
                    f"TITLE: {master.get('title', '')}\n"
                    f"SUMMARY:\n{master.get('log_text', '')}\n\n"
                    f"WORLD:\n{master.get('analysis_text', '')}\n\n"
                    f"NOTES:\n{master.get('god_text', '')}\n"
                )
                self.narrative_text.insert(tk.END, text)
                return
            table = self.mapping.get("ai_logs")
            if not table or not self.conn:
                self.narrative_text.insert(tk.END, "No narrative stored")
                return
            cur = self.conn.cursor()
            rows = cur.execute(
                f"SELECT role, message FROM {table} WHERE scope='master' AND cycle=?",
                (cycle,),
            ).fetchall()
            if not rows:
                self.narrative_text.insert(tk.END, "No narrative stored")
                return
            parts = {row[0]: row[1] for row in rows}
            title = self.cycle_name_cache.get(cycle, f"Cycle {cycle}")
            text = (
                f"TITLE: {title}\nSUMMARY:\n{parts.get('assistant', '')}\n\n"
                f"WORLD:\n{parts.get('analysis', '')}\n\n"
                f"NOTES:\n{parts.get('god', '')}\n"
            )
            self.narrative_text.insert(tk.END, text)
            return
        if record:
            for civ in record.get("civilizations", []):
                if str(civ.get("civ_id")) == str(civ_id):
                    narrative = civ.get("narrative", {})
                    log = narrative.get("log_text", "")
                    god = narrative.get("god_text", "")
                    news = narrative.get("news", "")
                    agenda = narrative.get("agenda", "")
                    stance = narrative.get("stance", "")
                    text = (
                        f"LOG:\n{log}\n\nGOD:\n{god}\n\n"
                        f"NEWS: {news}\nAGENDA: {agenda}\nSTANCE: {stance}\n"
                    )
                    self.narrative_text.insert(tk.END, text)
                    return
        table = self.mapping.get("ai_logs")
        if not table or not self.conn:
            self.narrative_text.insert(tk.END, "No narrative stored")
            return
        cur = self.conn.cursor()
        rows = cur.execute(
            f"SELECT role, message FROM {table} WHERE scope='civ' AND civ_id=? AND cycle=?",
            (civ_id, cycle),
        ).fetchall()
        if not rows:
            self.narrative_text.insert(tk.END, "No narrative stored")
            return
        parts = {row[0]: row[1] for row in rows}
        text = (
            f"LOG:\n{parts.get('assistant', '')}\n\nGOD:\n{parts.get('god', '')}\n\n"
            f"NEWS: {parts.get('news', '')}\nAGENDA: {parts.get('agenda', '')}\n"
            f"STANCE: {parts.get('stance', '')}\n"
        )
        self.narrative_text.insert(tk.END, text)

    def _get_cycle_record(self, cycle: int) -> Optional[Dict[str, object]]:
        table = self.mapping.get("cycle_records")
        if not table or not self.conn:
            return None
        cur = self.conn.cursor()
        row = cur.execute(
            f"SELECT record_json FROM {table} WHERE cycle=?",
            (cycle,),
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    def _set_stat(self, key: str, value) -> None:
        label = self.stats_labels.get(key)
        if not label:
            return
        if isinstance(value, float):
            label.configure(text=f"{value:.2f}")
        else:
            label.configure(text=str(value))

    def _clear_stats(self) -> None:
        for lbl in self.stats_labels.values():
            lbl.configure(text="—")
        self.raw_text.delete("1.0", tk.END)

    def _load_cycle_names(self) -> Dict[int, str]:
        names: Dict[int, str] = {}
        if not self.conn:
            return names
        table = self.mapping.get("cycles")
        if table:
            cur = self.conn.cursor()
            rows = cur.execute(f"SELECT id, summary FROM {table}").fetchall()
            for row in rows:
                if row[1]:
                    names[int(row[0])] = str(row[1])
        if not names and self.mapping.get("cycle_records"):
            cur = self.conn.cursor()
            rows = cur.execute(
                f"SELECT cycle, record_json FROM {self.mapping['cycle_records']}"
            ).fetchall()
            for cycle, record_json in rows:
                try:
                    record = json.loads(record_json)
                except json.JSONDecodeError:
                    continue
                title = record.get("master", {}).get("title")
                if title:
                    names[int(cycle)] = str(title)
        return names

    def _mission_cycles_for(self, civ_id: Optional[object]) -> set:
        if civ_id is None or not self.conn:
            return set()
        key = str(civ_id)
        if key in self.mission_cycle_cache:
            return self.mission_cycle_cache[key]
        cycles = set()
        table = self.mapping.get("events")
        if not table:
            self.mission_cycle_cache[key] = cycles
            return cycles
        cur = self.conn.cursor()
        rows = cur.execute(
            f"SELECT cycle, title, metadata_json FROM {table} "
            "WHERE title LIKE '%MISSION%' "
            "OR metadata_json LIKE '%MISSION%' "
            "OR metadata_json LIKE '%INTERSTELLAR%'"
        ).fetchall()
        for cycle, title, meta_raw in rows:
            event_id = ""
            target = ""
            try:
                meta = json.loads(meta_raw)
                event_id = str(meta.get("event_id", ""))
                target = str(meta.get("target", ""))
            except json.JSONDecodeError:
                event_id = ""
            if "MISSION_" not in event_id and "INTERSTELLAR" not in event_id:
                if title and "MISSION" not in str(title).upper():
                    continue
            if civ_id != "MASTER":
                if target and target != str(civ_id):
                    continue
            cycles.add(int(cycle))
        self.mission_cycle_cache[key] = cycles
        return cycles

    def _show_plots(self) -> None:
        civ_id = self._selected_civ_id()
        if civ_id is None:
            messagebox.showinfo("Plots", "Select a civilization first.")
            return
        table = self.mapping.get("cycle_records")
        if not table or not self.conn:
            messagebox.showinfo("Plots", "No cycle records available.")
            return
        cur = self.conn.cursor()
        rows = cur.execute(
            f"SELECT cycle, record_json FROM {table} ORDER BY cycle"
        ).fetchall()
        series = {
            "stability": [],
            "legitimacy": [],
            "cohesion": [],
            "inequality": [],
            "innovation": [],
            "food_security": [],
            "health": [],
        }
        cycles = []
        markers = {"stage": [], "crisis": [], "contact": []}
        last_stage = None
        for cycle, record_json in rows:
            try:
                record = json.loads(record_json)
            except json.JSONDecodeError:
                continue
            civ_entry = None
            for civ in record.get("civilizations", []):
                if str(civ.get("civ_id")) == str(civ_id):
                    civ_entry = civ
                    break
            if not civ_entry:
                continue
            stats = civ_entry.get("stats", {})
            cycles.append(int(cycle))
            for key in series:
                series[key].append(stats.get(key, 0.0))
            stage = civ_entry.get("stage")
            if stage != last_stage and stage:
                markers["stage"].append(int(cycle))
                last_stage = stage
            crisis = civ_entry.get("crisis", {}).get("legitimacy")
            if crisis:
                markers["crisis"].append(int(cycle))
            events = civ_entry.get("applied_events", [])
            if any("CONTACT" in e.get("event_id", "") for e in events):
                markers["contact"].append(int(cycle))

        if not cycles:
            messagebox.showinfo("Plots", "No data to plot.")
            return

        win = tk.Toplevel(self)
        win.title("Civilization Plots")
        fig = Figure(figsize=(8, 4), dpi=100)
        ax = fig.add_subplot(111)
        for key, values in series.items():
            ax.plot(cycles, values, label=key)
        for marker in markers["stage"]:
            ax.axvline(marker, color="gray", linestyle=":", linewidth=1)
        for marker in markers["crisis"]:
            ax.axvline(marker, color="red", linestyle="--", linewidth=1)
        for marker in markers["contact"]:
            ax.axvline(marker, color="blue", linestyle="-.", linewidth=1)
        ax.set_xlabel("Cycle")
        ax.set_ylabel("Value")
        ax.legend(loc="upper right")
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python db_viewer.py path/to/sim.db")
        app = DBViewer()
    else:
        app = DBViewer(sys.argv[1])
    app.mainloop()


if __name__ == "__main__":
    main()
