import math
import os
import datetime as dt
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

from lib.db import Event
from lib.sim import Simulation
from lib.ui_tabs import UITabsMixin


class AppUI(UITabsMixin, tk.Frame):
    """Main Tkinter UI for the universe simulation."""
    def __init__(self, master: tk.Tk, sim: Simulation) -> None:
        super().__init__(master)
        self.sim = sim
        self.is_running = True
        self.cycle_interval_ms = 2500
        self.selected_system_id = None
        self.theme = {
            "bg": "#070b14",
            "panel": "#0b1324",
            "panel_alt": "#0f1a33",
            "text": "#d7f3ff",
            "muted": "#6f8aa8",
            "accent": "#1fe4c7",
            "accent_alt": "#f7b32b",
            "danger": "#ff6b6b",
            "grid": "#13233f",
        }
        self.queue = queue.Queue()
        self.log_texts = {}
        self._stars = []
        self._system_positions = {}
        self._civ_systems = {}
        self._comm_links = []
        self._last_event_id = 0
        self._persistent_links = []
        self._alert_text = "Status: Stable"
        self._alert_color = "#1fe4c7"
        self._system_view_data = {}
        self._civ_tab_ids = {}
        self._needs_init_message = True
        self._stop = False
        self._worker_thread = None
        self._layout_set = False
        self._build()
        self._refresh_events()
        self._refresh_universe()
        self._refresh_civ_tabs()
        self._start_worker()
        self._process_queue()
        self.winfo_toplevel().protocol("WM_DELETE_WINDOW", self._quit_app)
        self.after(100, self._set_layout_sashes)

    def _build(self) -> None:
        """Build the full UI layout."""
        self._apply_theme()
        header = tk.Frame(self, bg=self.theme["bg"])
        header.pack(fill="x", padx=12, pady=8)

        title = tk.Label(
            header,
            text="TRANSCENDENCE :: UNIVERSE CONTROL",
            font=("Consolas", 18, "bold"),
            bg=self.theme["bg"],
            fg=self.theme["accent"],
        )
        title.pack(side="left")

        controls = tk.Frame(header, bg=self.theme["bg"])
        controls.pack(side="right")

        self.pause_btn = tk.Button(
            controls,
            text="Pause",
            command=self._toggle_pause,
            bg=self.theme["panel"],
            fg=self.theme["accent"],
            activebackground=self.theme["accent"],
            activeforeground=self.theme["bg"],
            highlightbackground=self.theme["panel"],
        )
        self.pause_btn.pack(side="left", padx=4)

        refresh = tk.Button(
            controls,
            text="Refresh",
            command=self._refresh_events,
            bg=self.theme["panel"],
            fg=self.theme["accent"],
            activebackground=self.theme["accent"],
            activeforeground=self.theme["bg"],
            highlightbackground=self.theme["panel"],
        )
        refresh.pack(side="left", padx=4)
        export_btn = tk.Button(
            controls,
            text="Export",
            command=self._export_snapshot,
            bg=self.theme["panel"],
            fg=self.theme["accent"],
            activebackground=self.theme["accent"],
            activeforeground=self.theme["bg"],
            highlightbackground=self.theme["panel"],
        )
        export_btn.pack(side="left", padx=4)
        quit_btn = tk.Button(
            controls,
            text="Quit",
            command=self._quit_app,
            bg=self.theme["panel"],
            fg=self.theme["danger"],
            activebackground=self.theme["danger"],
            activeforeground=self.theme["bg"],
            highlightbackground=self.theme["panel"],
        )
        quit_btn.pack(side="left", padx=4)

        self.body_pane = tk.PanedWindow(
            self,
            orient="horizontal",
            sashrelief="raised",
            bg=self.theme["bg"],
        )
        self.body_pane.pack(fill="both", expand=True, padx=12, pady=8)

        left = tk.Frame(self.body_pane, bg=self.theme["bg"])
        right = tk.Frame(self.body_pane, bg=self.theme["bg"])

        self.body_pane.add(left, stretch="always")
        self.body_pane.add(right, stretch="always")

        self.left_split = tk.PanedWindow(
            left, orient="vertical", sashrelief="raised", bg=self.theme["bg"]
        )
        self.left_split.pack(fill="both", expand=True)

        panel_frame = tk.Frame(self.left_split, bg=self.theme["panel"])
        map_frame = tk.Frame(self.left_split, bg=self.theme["bg"])
        self.left_split.add(panel_frame, stretch="never")
        self.left_split.add(map_frame, stretch="always")

        self.canvas = tk.Canvas(
            map_frame, background=self.theme["bg"], highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        panel_title = tk.Label(
            panel_frame,
            text="SYSTEM VIEW",
            font=("Consolas", 10, "bold"),
            bg=self.theme["panel"],
            fg=self.theme["accent_alt"],
        )
        panel_title.pack(anchor="w", padx=8, pady=(8, 4))
        hint_frame = tk.Frame(panel_frame, bg=self.theme["panel"], height=72)
        hint_frame.pack(fill="x", padx=8, pady=(0, 6))
        hint_frame.pack_propagate(False)
        self.system_hint = tk.Label(
            hint_frame,
            text="Click a system to inspect.",
            font=("Consolas", 9),
            bg=self.theme["panel"],
            fg=self.theme["muted"],
            justify="left",
            wraplength=220,
        )
        self.system_hint.pack(anchor="w")
        self.system_canvas = tk.Canvas(
            panel_frame,
            bg=self.theme["panel"],
            highlightthickness=0,
            height=200,
        )
        self.system_canvas.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.system_canvas.bind("<Motion>", self._on_system_hover)
        self.system_canvas.bind("<Leave>", self._clear_system_hover)

        self.info_tabs = ttk.Notebook(right)
        self.info_tabs.pack(fill="x", expand=False, pady=(0, 6))

        self.sys_tab = tk.Frame(self.info_tabs, bg=self.theme["panel"])
        self.info_text = tk.Text(
            self.sys_tab,
            wrap="word",
            height=9,
            bg=self.theme["panel"],
            fg=self.theme["text"],
            insertbackground=self.theme["accent"],
        )
        self.info_text.pack(fill="both", expand=True)
        self.info_text.insert(tk.END, "Click a star system to inspect it.")
        self.info_tabs.add(self.sys_tab, text="System")

        self.civ_tab = tk.Frame(self.info_tabs, bg=self.theme["panel_alt"])
        overview = tk.Frame(self.civ_tab, bg=self.theme["panel_alt"])
        overview.pack(fill="both", expand=True)
        self.overview_title = tk.Label(
            overview,
            text="CIVILIZATIONS",
            font=("Consolas", 10, "bold"),
            bg=self.theme["panel_alt"],
            fg=self.theme["accent_alt"],
        )
        self.overview_title.pack(anchor="w", padx=8, pady=(6, 2))
        self.civ_overview = tk.Frame(overview, bg=self.theme["panel_alt"])
        self.civ_overview.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        self.info_tabs.add(self.civ_tab, text="Civs")

        self.stats_tab = tk.Frame(self.info_tabs, bg=self.theme["panel"])
        self.info_tabs.add(self.stats_tab, text="Stats")

        self.world_tab = tk.Frame(self.info_tabs, bg=self.theme["panel"])
        self.info_tabs.add(self.world_tab, text="World")

        self.chaos_tab = tk.Frame(self.info_tabs, bg=self.theme["panel"])
        self.info_tabs.add(self.chaos_tab, text="Rules")

        self.errors_tab = tk.Frame(self.info_tabs, bg=self.theme["panel"])
        self.info_tabs.add(self.errors_tab, text="Errors")


        player_row = tk.Frame(right, bg=self.theme["panel_alt"])
        player_row.pack(fill="x", pady=(0, 6))
        player_row.columnconfigure(0, weight=1)
        player_row.columnconfigure(1, weight=1)

        player_frame = tk.Frame(player_row, bg=self.theme["panel_alt"])
        player_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tk.Label(
            player_frame,
            text="PLAYER DIRECTIVE (next cycle)",
            font=("Consolas", 9, "bold"),
            bg=self.theme["panel_alt"],
            fg=self.theme["accent_alt"],
        ).pack(anchor="w", padx=8, pady=(6, 2))
        self.player_text = tk.Text(
            player_frame,
            height=2,
            wrap="word",
            bg=self.theme["panel"],
            fg=self.theme["text"],
            insertbackground=self.theme["accent"],
        )
        self.player_text.pack(fill="x", padx=8, pady=(0, 4))
        row = tk.Frame(player_frame, bg=self.theme["panel_alt"])
        row.pack(fill="x", padx=8, pady=(0, 6))
        self.player_combo = ttk.Combobox(row, values=[], state="readonly", width=20)
        self.player_combo.pack(side="left")
        tk.Button(
            row,
            text="Queue",
            command=self._queue_player_directive,
            bg=self.theme["panel"],
            fg=self.theme["accent"],
            activebackground=self.theme["accent"],
            activeforeground=self.theme["bg"],
            highlightbackground=self.theme["panel"],
        ).pack(side="left", padx=6)

        command_frame = tk.Frame(player_row, bg=self.theme["panel_alt"])
        command_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        tk.Label(
            command_frame,
            text="PLAYER COMMAND",
            font=("Consolas", 9, "bold"),
            bg=self.theme["panel_alt"],
            fg=self.theme["accent_alt"],
        ).pack(anchor="w", padx=8, pady=(6, 2))
        cmd_row = tk.Frame(command_frame, bg=self.theme["panel_alt"])
        cmd_row.pack(fill="x", padx=8, pady=(0, 6))
        self.command_type = ttk.Combobox(
            cmd_row,
            values=["END_UNIVERSE", "KILL_CIV", "FORCE_EVENT", "SET_GLOBAL_MARK"],
            state="readonly",
            width=18,
        )
        self.command_type.pack(side="left")
        self.command_type.set("END_UNIVERSE")
        self.command_target = ttk.Combobox(cmd_row, values=[], state="readonly", width=18)
        self.command_target.pack(side="left", padx=6)
        self.command_arg = tk.Entry(
            cmd_row,
            bg=self.theme["panel"],
            fg=self.theme["text"],
            insertbackground=self.theme["accent"],
            width=24,
        )
        self.command_arg.pack(side="left", padx=6)
        tk.Button(
            cmd_row,
            text="Queue",
            command=self._queue_player_command,
            bg=self.theme["panel"],
            fg=self.theme["accent"],
            activebackground=self.theme["accent"],
            activeforeground=self.theme["bg"],
            highlightbackground=self.theme["panel"],
        ).pack(side="left")

        self.civ_tabs = ttk.Notebook(right)
        self.civ_tabs.pack(fill="both", expand=True, pady=(6, 0))

        events_pane = tk.PanedWindow(
            right, orient="horizontal", sashrelief="raised", bg=self.theme["bg"]
        )
        events_pane.pack(fill="both", expand=True, pady=(8, 0))

        events_left = tk.Frame(events_pane, bg=self.theme["bg"])
        events_right = tk.Frame(events_pane, bg=self.theme["bg"])
        events_pane.add(events_left, stretch="always")
        events_pane.add(events_right, stretch="always")

        self.event_list = tk.Listbox(
            events_left,
            height=10,
            bg=self.theme["panel"],
            fg=self.theme["text"],
            selectbackground=self.theme["accent"],
            selectforeground=self.theme["bg"],
        )
        self.event_list.pack(fill="both", expand=True)
        self.event_list.bind("<<ListboxSelect>>", self._on_select)

        self.event_detail = tk.Text(
            events_right,
            wrap="word",
            height=10,
            bg=self.theme["panel"],
            fg=self.theme["text"],
            insertbackground=self.theme["accent"],
        )
        self.event_detail.pack(fill="both", expand=True)

        footer = tk.Frame(self, bg=self.theme["bg"])
        footer.pack(fill="x", padx=12, pady=(0, 12))

        self.status_var = tk.StringVar(value="Ready")
        status = tk.Label(
            footer,
            textvariable=self.status_var,
            bg=self.theme["bg"],
            fg=self.theme["muted"],
            font=("Consolas", 10),
        )
        status.pack(side="left")

    def _toggle_pause(self) -> None:
        self.is_running = not self.is_running
        self.pause_btn.configure(text="Pause" if self.is_running else "Resume")
        state = "running" if self.is_running else "paused"
        self.status_var.set(f"Simulation {state}")

    def _refresh_events(self) -> None:
        """Reload event list from DB and refresh the map."""
        self.event_list.delete(0, tk.END)
        self.events = self.sim.db.list_events(limit=500)
        for event in self.events:
            label = f"#{event.id} | C{event.cycle} | {event.title}"
            self.event_list.insert(tk.END, label)
        self.event_detail.delete("1.0", tk.END)
        self._refresh_universe()
        latest = self.sim.db.get_latest_cycle_id()
        civ_count = len(self.sim.db.list_civilizations())
        ruleset = getattr(self.sim, "ruleset_name", "harsh_realism")
        self.status_var.set(
            f"Cycle {latest} | Events {len(self.events)} | Civs {civ_count} | Ruleset {ruleset}"
        )
        if latest == 0 and self._needs_init_message:
            self.info_text.delete("1.0", tk.END)
            self.info_text.insert(
                tk.END,
                "Initialization in progress...\n"
                "Wait for cycle 1 to populate full system data.",
            )
        if latest >= 1:
            self._needs_init_message = False
        self._comm_links = self._build_comm_links(self.events)
        self._persistent_links = self._build_persistent_links(self.events)
        self._set_alert_state(self.events)
        if self.events:
            newest = self.events[0].id
            if newest > self._last_event_id:
                self._pulse_from_events(self.events, newest - self._last_event_id)
                self._last_event_id = newest

    def _on_select(self, _event: tk.Event) -> None:
        selection = self.event_list.curselection()
        if not selection:
            return
        index = selection[0]
        event = self.events[index]
        self._show_event(event)

    def _show_event(self, event: Event) -> None:
        self.event_detail.delete("1.0", tk.END)
        lines = [
            f"ID: {event.id}",
            f"Cycle: {event.cycle}",
            f"Kind: {event.kind}",
            f"Title: {event.title}",
            f"Time: {event.created_at}",
            "",
            event.detail,
            "",
            f"Metadata: {event.metadata}",
        ]
        self.event_detail.insert(tk.END, "\n".join(lines))

    def _start_worker(self) -> None:
        self._worker_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._worker_thread.start()

    def _run_loop(self) -> None:
        while not self._stop:
            if self.is_running:
                if self.sim.is_ended():
                    self.is_running = False
                    self.status_var.set("Universe ended: No signals detected.")
                    time.sleep(0.2)
                    continue
                self.sim.run_cycle_stream(self._enqueue_stream)
                self.queue.put({"type": "cycle_complete"})
                time.sleep(self.cycle_interval_ms / 1000.0)
            else:
                time.sleep(0.2)

    def _enqueue_stream(self, payload) -> None:
        self.queue.put(payload)

    def _process_queue(self) -> None:
        handled = False
        while True:
            try:
                payload = self.queue.get_nowait()
            except queue.Empty:
                break
            handled = True
            if payload.get("type") == "cycle_complete":
                self._refresh_events()
                self._refresh_civ_tabs()
                continue
            self._handle_log_stream(payload)
        if handled:
            self.event_list.see(0)
        self.after(100, self._process_queue)

    def _refresh_universe(self) -> None:
        self.canvas.delete("all")
        self._draw_starfield()
        systems = self.sim.db.list_systems()
        civs = self.sim.db.list_civilizations()
        civ_planets = {civ.home_planet_id: civ for civ in civs}
        self._civ_systems = {}
        system_colors = {}
        for system in systems:
            planets = self.sim.db.list_planets_by_system(system.id)
            color = None
            for planet in planets:
                civ = civ_planets.get(planet.id)
                if civ:
                    color = "#444444" if getattr(civ, "extinct", 0) else civ.color
                    self._civ_systems[civ.id] = system.id
                    break
            system_colors[system.id] = color

        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        self._system_items = {}
        self._system_positions = {}
        self._draw_persistent_links(systems)
        self._draw_comm_links(systems)
        for system in systems:
            x = int(system.x * (width - 40)) + 20
            y = int(system.y * (height - 40)) + 20
            self._system_positions[system.id] = (x, y)
            fill = "#d7f3ff"
            outline = system_colors.get(system.id) or self.theme["grid"]
            glow = system_colors.get(system.id) or self.theme["accent"]
            self.canvas.create_oval(
                x - 16,
                y - 16,
                x + 16,
                y + 16,
                outline="",
                fill=glow,
                stipple="gray25",
            )
            item = self.canvas.create_oval(
                x - 8, y - 8, x + 8, y + 8, fill=fill, outline=outline, width=2
            )
            self.canvas.create_text(
                x,
                y + 16,
                text=system.name,
                fill=self.theme["muted"],
                font=("Consolas", 9),
            )
            self._system_items[item] = system.id
        self._draw_hud()

    def _handle_log_stream(self, payload) -> None:
        """Route streaming chunks to the correct text widget."""
        scope = payload.get("scope")
        civ_id = payload.get("civ_id")
        if scope == "master":
            key = "master"
        elif scope == "chaos":
            text = getattr(self, "chaos_text", None)
            if not text:
                return
            self._handle_log_stream_to_widget(text, payload, scope, civ_id)
            return
        else:
            if not civ_id:
                return
            key = int(civ_id)
        text = self.log_texts.get(key)
        if not text:
            self._refresh_civ_tabs()
            text = self.log_texts.get(key)
        if not text:
            return
        self._handle_log_stream_to_widget(text, payload, scope, civ_id)

    def _handle_log_stream_to_widget(
        self, text: tk.Text, payload, scope: str, civ_id: str
    ) -> None:
        if payload.get("type") == "status":
            self.status_var.set(payload.get("message", ""))
            return
        event_type = payload.get("type")
        cycle = payload.get("cycle", "?")
        role = payload.get("role", "assistant")
        if event_type == "log_start":
            text.insert(tk.END, f"[C{cycle}] {role}:\n", "header")
            text.see(tk.END)
            self._focus_llm_tab(scope, civ_id)
        elif event_type == "log_chunk":
            tag = role if role in ("prompt", "god", "analysis") else "assistant"
            text.insert(tk.END, payload.get("chunk", ""), tag)
            text.see(tk.END)
            self._focus_llm_tab(scope, civ_id)
        elif event_type == "log_end":
            text.insert(tk.END, "\n\n", "assistant")
            text.see(tk.END)
            if scope == "civ" and civ_id:
                self._pulse_civ(int(civ_id))

    def _on_canvas_resize(self, _event: tk.Event) -> None:
        self._seed_starfield()
        self._refresh_universe()
        self._set_layout_sashes()

    def _on_canvas_click(self, event: tk.Event) -> None:
        items = self.canvas.find_closest(event.x, event.y)
        if not items:
            return
        item = items[0]
        system_id = self._system_items.get(item)
        if not system_id:
            return
        self.selected_system_id = system_id
        self._show_system_info(system_id)

    def _build_comm_links(self, events):
        systems = self.sim.db.list_systems()
        if len(systems) < 2:
            return []
        links = []
        kinds = {"contact", "conflict", "alliance", "trade", "war"}
        for event in events[:12]:
            if event.kind not in kinds:
                continue
            a = event.id % len(systems)
            b = (event.id * 7 + 3) % len(systems)
            if a == b:
                b = (b + 1) % len(systems)
            links.append((systems[a].id, systems[b].id, event.kind))
        return links

    def _build_persistent_links(self, events):
        systems = self.sim.db.list_systems()
        if len(systems) < 2:
            return []
        links = {}
        kinds = {"alliance", "trade", "conflict", "war"}
        for event in events:
            if event.kind not in kinds:
                continue
            a = event.id % len(systems)
            b = (event.id * 7 + 3) % len(systems)
            if a == b:
                b = (b + 1) % len(systems)
            key = tuple(sorted((systems[a].id, systems[b].id)))
            if key not in links:
                links[key] = event.kind
        return [(key[0], key[1], kind) for key, kind in links.items()]

    def _set_alert_state(self, events) -> None:
        alert = "Status: Stable"
        color = self.theme["accent"]
        for event in events[:6]:
            if event.kind in ("war", "conflict"):
                alert = f"Alert: {event.kind.upper()}"
                color = self.theme["danger"]
                break
            if event.kind == "anomaly":
                alert = "Alert: ANOMALY DETECTED"
                color = self.theme["accent_alt"]
                break
            if event.kind == "breakthrough":
                alert = "Signal: BREAKTHROUGH"
                color = "#7bdff2"
                break
        self._alert_text = alert
        self._alert_color = color

    def _draw_comm_links(self, systems) -> None:
        if not self._comm_links:
            return
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        positions = {}
        for system in systems:
            x = int(system.x * (width - 40)) + 20
            y = int(system.y * (height - 40)) + 20
            positions[system.id] = (x, y)
        color_map = {
            "contact": self.theme["accent"],
            "alliance": self.theme["accent_alt"],
            "trade": "#7bdff2",
            "conflict": self.theme["danger"],
            "war": self.theme["danger"],
        }
        for a, b, kind in self._comm_links:
            if a not in positions or b not in positions:
                continue
            ax, ay = positions[a]
            bx, by = positions[b]
            color = color_map.get(kind, self.theme["muted"])
            self.canvas.create_line(
                ax,
                ay,
                bx,
                by,
                fill=color,
                width=2,
                dash=(4, 3),
            )

    def _draw_persistent_links(self, systems) -> None:
        if not self._persistent_links:
            return
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        positions = {}
        for system in systems:
            x = int(system.x * (width - 40)) + 20
            y = int(system.y * (height - 40)) + 20
            positions[system.id] = (x, y)
        color_map = {
            "alliance": self.theme["accent_alt"],
            "trade": "#7bdff2",
            "conflict": self.theme["danger"],
            "war": self.theme["danger"],
        }
        for a, b, kind in self._persistent_links:
            if a not in positions or b not in positions:
                continue
            ax, ay = positions[a]
            bx, by = positions[b]
            color = color_map.get(kind, self.theme["muted"])
            self.canvas.create_line(
                ax,
                ay,
                bx,
                by,
                fill=color,
                width=3,
                smooth=True,
            )

    def _draw_starfield(self) -> None:
        if not self._stars:
            self._seed_starfield()
        for star in self._stars:
            x, y, r, color = star
            self.canvas.create_oval(x - r, y - r, x + r, y + r, fill=color, outline="")

    def _seed_starfield(self) -> None:
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        self._stars = []
        for i in range(120):
            x = (i * 97) % width
            y = (i * 53) % height
            r = 1 if i % 3 else 2
            color = self.theme["grid"] if i % 5 else self.theme["muted"]
            self._stars.append((x, y, r, color))

    def _draw_hud(self) -> None:
        latest = self.sim.db.get_latest_cycle_id()
        self.canvas.create_text(
            12,
            12,
            anchor="nw",
            text=f"CYCLE {latest}",
            fill=self.theme["accent_alt"],
            font=("Consolas", 12, "bold"),
        )
        self.canvas.create_text(
            12,
            34,
            anchor="nw",
            text=self._alert_text,
            fill=self._alert_color,
            font=("Consolas", 10, "bold"),
        )

    def _apply_theme(self) -> None:
        self.configure(bg=self.theme["bg"])
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "TNotebook",
            background=self.theme["bg"],
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background=self.theme["panel_alt"],
            foreground=self.theme["text"],
            padding=(10, 4),
            font=("Consolas", 9, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.theme["accent"])],
            foreground=[("selected", self.theme["bg"])],
        )

    def _set_layout_sashes(self) -> None:
        try:
            width = max(self.body_pane.winfo_width(), 1)
            height_left = max(self.left_split.winfo_height(), 1)
            if self._layout_set:
                return
            if width < 600 or height_left < 400:
                return
            left_width = int(width * 0.2)
            self.body_pane.sash_place(0, left_width, 0)
            top_height = int(height_left * 0.4)
            self.left_split.sash_place(0, 0, top_height)
            self._layout_set = True
        except Exception:
            return

    def _show_system_info(self, system_id: int) -> None:
        system = next(
            (s for s in self.sim.db.list_systems() if s.id == system_id), None
        )
        if not system:
            return
        planets = self.sim.db.list_planets_by_system(system_id)
        civs = {civ.home_planet_id: civ for civ in self.sim.db.list_civilizations()}
        lines = [
            f"System: {system.name}",
            f"Position: ({system.x:.2f}, {system.y:.2f})",
            "",
            "Planets:",
        ]
        for planet in planets:
            civ = civs.get(planet.id)
            civ_label = ""
            if civ:
                civ_label = f" | Civ: {civ.name} ({civ.level}, {civ.status})"
            lines.append(
                f"- {planet.name} | {planet.kind} | orbit {planet.orbit_au:.2f} AU | "
                f"size {planet.size:.2f} | habitability {planet.habitability:.2f} | "
                f"richness {planet.richness:.2f} | science {planet.science:.2f}"
                f"{civ_label}"
            )
        self.info_text.delete("1.0", tk.END)
        self.info_text.insert(tk.END, "\n".join(lines))

        self._render_system_view(system)

    def _export_snapshot(self) -> None:
        db_path = getattr(self.sim.db, "path", "sim.db")
        base_dir = os.path.dirname(db_path) or "."
        game_name = os.path.splitext(os.path.basename(db_path))[0]
        cycle = self.sim.db.get_latest_cycle_id()
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{game_name}_cycle{cycle}.txt"
        path = os.path.join(base_dir, filename)
        content = self.sim.db.export_snapshot()
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def _quit_app(self) -> None:
        self.is_running = False
        self._stop = True
        self.status_var.set("Shutting down…")
        self._show_shutdown_overlay()
        self._wait_for_worker()

    def _wait_for_worker(self) -> None:
        thread = self._worker_thread
        if thread and thread.is_alive():
            self.after(100, self._wait_for_worker)
            return
        try:
            self._export_snapshot()
            self.sim.db.set_setting(
                "last_cycle", str(self.sim.db.get_latest_cycle_id())
            )
            self.sim.db.close()
        except Exception:
            pass
        self._hide_shutdown_overlay()
        self.winfo_toplevel().destroy()

    def _show_shutdown_overlay(self) -> None:
        if hasattr(self, "_shutdown_overlay") and self._shutdown_overlay.winfo_exists():
            return
        overlay = tk.Toplevel(self)
        overlay.title("Saving...")
        overlay.geometry("500x100")
        overlay.resizable(False, False)
        overlay.transient(self.winfo_toplevel())
        overlay.grab_set()
        label = tk.Label(
            overlay,
            text=(
                "Saving in progress...\n"
                "Please wait end of cycle!\n"
                "(may take time if a LLM response is running)."
            ),
            font=("Consolas", 10),
        )
        label.pack(expand=True, padx=20, pady=20)
        self._shutdown_overlay = overlay

    def _hide_shutdown_overlay(self) -> None:
        overlay = getattr(self, "_shutdown_overlay", None)
        if overlay and overlay.winfo_exists():
            overlay.destroy()

    def _render_system_view(self, system) -> None:
        data = self._system_view_data
        canvas = self.system_canvas
        if not canvas:
            return
        if data.get("after_id"):
            self.after_cancel(data["after_id"])
        canvas.update_idletasks()
        planets = self.sim.db.list_planets_by_system(system.id)
        civs = {civ.home_planet_id: civ for civ in self.sim.db.list_civilizations()}
        max_orbit = max((p.orbit_au for p in planets), default=1.0)
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        center = (width // 2, height // 2)
        orbit_scale = min(width, height) * 0.42
        bodies = []
        for planet in planets:
            radius = (planet.orbit_au / max_orbit) * orbit_scale + 20
            color = civs.get(planet.id).color if planet.id in civs else self.theme["muted"]
            bodies.append(
                {
                    "planet": planet,
                    "radius": radius,
                    "angle": (planet.id * 53) % 360,
                    "speed": max(0.4, 2.2 - planet.orbit_au) / 90.0,
                    "color": color,
                }
            )
        data.update(
            {
                "system": system,
                "center": center,
                "bodies": bodies,
                "canvas": canvas,
                "positions": {},
            }
        )
        self._animate_system_view()

    def _animate_system_view(self) -> None:
        data = self._system_view_data
        canvas = data.get("canvas")
        system = data.get("system")
        if not canvas or not system:
            return
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        cx, cy = width // 2, height // 2
        data["center"] = (cx, cy)
        canvas.create_text(
            12,
            12,
            anchor="nw",
            text=f"SYSTEM {system.name}",
            fill=self.theme["accent"],
            font=("Consolas", 12, "bold"),
        )
        canvas.create_oval(cx - 10, cy - 10, cx + 10, cy + 10, fill=self.theme["accent"], outline="")
        for body in data["bodies"]:
            radius = body["radius"]
            canvas.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                outline=self.theme["grid"],
            )
            body["angle"] = (body["angle"] + body["speed"]) % 360
            angle = body["angle"]
            rad = math.radians(angle)
            x = cx + radius * math.cos(rad)
            y = cy + radius * math.sin(rad)
            r = max(3, int(body["planet"].size * 2))
            canvas.create_oval(
                x - r,
                y - r,
                x + r,
                y + r,
                fill=body["color"],
                outline="",
            )
            data["positions"][body["planet"].id] = (x, y, r, body["planet"])
        data["after_id"] = self.after(50, self._animate_system_view)

    def _on_system_hover(self, event: tk.Event) -> None:
        data = self._system_view_data
        positions = data.get("positions", {})
        if not positions:
            return
        closest = None
        for item in positions.values():
            x, y, r, planet = item
            if (event.x - x) ** 2 + (event.y - y) ** 2 <= (r + 4) ** 2:
                closest = planet
                break
        if not closest:
            self.system_hint.configure(text="Hover a planet for details.")
            return
        self.system_hint.configure(
            text=(
                f"{closest.name} | {closest.kind}\n"
                f"Orbit {closest.orbit_au:.2f} AU | Size {closest.size:.2f}\n"
                f"Habitability {closest.habitability:.2f}\n"
                f"Richness {closest.richness:.2f} | Science {closest.science:.2f}"
            )
        )

    def _clear_system_hover(self, _event: tk.Event) -> None:
        self.system_hint.configure(text="Click a system to inspect.")

    def _focus_llm_tab(self, scope: str, civ_id: str) -> None:
        if scope == "master":
            tab = self._civ_tab_ids.get("master")
        elif scope == "chaos":
            return
        else:
            if not civ_id:
                return
            tab = self._civ_tab_ids.get(int(civ_id))
        if not tab:
            return
        self.civ_tabs.select(tab)

    def _on_model_selected(self, _event: tk.Event) -> None:
        # Backward-compatible no-op if an old widget still binds this callback.
        return

    def _pulse_civ(self, civ_id: int) -> None:
        system_id = self._civ_systems.get(civ_id)
        if not system_id:
            return
        pos = self._system_positions.get(system_id)
        if not pos:
            return
        self._pulse_at(pos[0], pos[1], self.theme["accent_alt"])

    def _pulse_from_events(self, events, count: int) -> None:
        systems = list(self._system_positions.keys())
        if not systems:
            return
        for event in events[:count]:
            system_id = systems[event.id % len(systems)]
            pos = self._system_positions.get(system_id)
            if pos:
                color = (
                    self.theme["danger"]
                    if event.kind in ("conflict", "war")
                    else self.theme["accent"]
                )
                self._pulse_at(pos[0], pos[1], color)

    def _pulse_at(self, x: int, y: int, color: str) -> None:
        ring = self.canvas.create_oval(
            x - 8, y - 8, x + 8, y + 8, outline=color, width=2
        )
        self._animate_pulse(ring, x, y, 10, color)

    def _animate_pulse(self, ring, x: int, y: int, step: int, color: str) -> None:
        if step > 22:
            self.canvas.delete(ring)
            return
        self.canvas.coords(ring, x - step, y - step, x + step, y + step)
        self.canvas.itemconfig(ring, outline=color)
        self.after(40, lambda: self._animate_pulse(ring, x, y, step + 2, color))
