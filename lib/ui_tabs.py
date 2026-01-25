import json
import tkinter as tk
from tkinter import ttk


class UITabsMixin:
    """Tabs and text panels (master, civs, stats, world, chaos, directives)."""

    def _format_percent(self, value) -> str:
        try:
            return f"{int(round(float(value) * 100))}%"
        except (TypeError, ValueError):
            return "—"

    def _format_stage_progress(self, stage: str, progress_value) -> str:
        if not stage:
            return "Stage: — | Progress: —"
        if progress_value is None:
            return f"Stage: {stage} | Progress: —"
        return f"Stage: {stage} | Progress: {self._format_percent(progress_value)}"

    def _get_civ_progress(self, civ_id: int):
        raw = self.sim.db.get_setting(f"civ_progress_{civ_id}")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _get_civ_token(self, civ_id: int, key: str) -> str:
        raw = self.sim.db.get_setting(f"{key}_{civ_id}")
        return raw.strip() if raw else ""

    def _refresh_civ_tabs(self) -> None:
        """Rebuild civilization log tabs (master + civs)."""
        for tab in self.civ_tabs.tabs():
            self.civ_tabs.forget(tab)
        self.log_texts = {}
        self._civ_tab_ids = {}
        civs = self.sim.db.list_civilizations()

        master_frame = tk.Frame(self.civ_tabs)
        master_text = tk.Text(master_frame, wrap="word")
        self._setup_text_widget(master_text)
        master_text.pack(fill="both", expand=True)
        master_logs = self.sim.db.list_ai_logs("master", None, limit=120)
        self._insert_logs(master_text, list(reversed(master_logs)))
        self.civ_tabs.add(master_frame, text="Master AI")
        self.log_texts["master"] = master_text
        self._civ_tab_ids["master"] = master_frame

        for civ in civs:
            frame = tk.Frame(self.civ_tabs, bg=self.theme["panel"])
            header = tk.Frame(frame, bg=self.theme["panel"])
            header.pack(fill="x", padx=8, pady=(6, 2))

            title = tk.Label(
                header,
                text=f"{civ.name} :: {civ.tech_stage}",
                font=("Consolas", 10, "bold"),
                bg=self.theme["panel"],
                fg=self.theme["accent_alt"],
            )
            title.pack(side="left")

            intent_frame = tk.Frame(frame, bg=self.theme["panel"])
            intent_frame.pack(fill="x", padx=8, pady=(0, 4))
            llm_off = getattr(self.sim.llm, "mode", "") == "stub"
            agenda = self._get_civ_token(civ.id, "civ_agenda") or "—"
            stance = self._get_civ_token(civ.id, "civ_stance") or "—"
            if llm_off:
                agenda = "SURVIVE"
                stance = "PRAGMATIC"
                intent_text = f"Intent: {agenda} / {stance} (LLM off)"
            else:
                intent_text = f"Intent: {agenda} / {stance}"
            intent_label = tk.Label(
                intent_frame,
                text=intent_text,
                font=("Consolas", 9),
                bg=self.theme["panel"],
                fg=self.theme["text"],
            )
            intent_label.pack(side="left")

            intent_hint = tk.Label(
                intent_frame,
                text="LLM-declared posture; biases event weights only.",
                font=("Consolas", 8),
                bg=self.theme["panel"],
                fg=self.theme["muted"],
                wraplength=260,
                justify="right",
            )
            intent_hint.pack(side="right")

            stats_frame = tk.Frame(frame, bg=self.theme["panel"])
            stats_frame.pack(fill="x", padx=8, pady=(0, 6))
            stats_frame.columnconfigure(0, weight=1)
            stats_frame.columnconfigure(1, weight=0)
            stats_frame.columnconfigure(2, weight=1)
            stats_frame.columnconfigure(3, weight=0)

            core_label = tk.Label(
                stats_frame,
                text="Core Stats",
                font=("Consolas", 9, "bold"),
                bg=self.theme["panel"],
                fg=self.theme["accent"],
            )
            core_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))

            stage_progress = self._format_stage_progress(
                getattr(civ, "tech_stage", ""), self._get_civ_progress(civ.id)
            )
            stage_label = tk.Label(
                stats_frame,
                text=stage_progress,
                font=("Consolas", 9),
                bg=self.theme["panel"],
                fg=self.theme["text"],
            )
            stage_label.grid(row=0, column=2, columnspan=2, sticky="e", pady=(0, 2))

            core_stats = [
                ("Cohesion", getattr(civ, "cohesion", None)),
                ("Inequality", getattr(civ, "inequality", None)),
                ("Eco", getattr(civ, "eco_pressure", None)),
                ("Innovation", getattr(civ, "innovation", None)),
                ("Stability", getattr(civ, "stability", None)),
                ("Food", getattr(civ, "food_security", None)),
                ("Health", getattr(civ, "health", None)),
            ]
            row = 1
            for idx, (label_text, value) in enumerate(core_stats):
                col = idx % 2
                if col == 0 and idx:
                    row += 1
                col_base = 0 if col == 0 else 2
                label = tk.Label(
                    stats_frame,
                    text=f"{label_text}:",
                    font=("Consolas", 8),
                    bg=self.theme["panel"],
                    fg=self.theme["muted"],
                )
                label.grid(row=row, column=col_base, sticky="w")
                value_label = tk.Label(
                    stats_frame,
                    text=self._format_percent(value),
                    font=("Consolas", 8),
                    bg=self.theme["panel"],
                    fg=self.theme["text"],
                )
                value_label.grid(row=row, column=col_base + 1, sticky="e", padx=(0, 8))

            dynamics_label = tk.Label(
                stats_frame,
                text="Internal Dynamics",
                font=("Consolas", 9, "bold"),
                bg=self.theme["panel"],
                fg=self.theme["accent"],
            )
            dynamics_label.grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(6, 2))
            dynamics_hint = tk.Label(
                stats_frame,
                text="elite_power=capture capacity; legitimacy=public acceptance; extraction_rate=rent seeking",
                font=("Consolas", 8),
                bg=self.theme["panel"],
                fg=self.theme["muted"],
                wraplength=320,
                justify="right",
            )
            dynamics_hint.grid(row=row + 1, column=2, columnspan=2, sticky="e", pady=(6, 2))

            dynamics = [
                ("Elite Power", getattr(civ, "elite_power", None)),
                ("Legitimacy", getattr(civ, "legitimacy", None)),
                ("Extraction", getattr(civ, "extraction_rate", None)),
            ]
            dynamics_row = row + 2
            for idx, (label_text, value) in enumerate(dynamics):
                col = idx % 2
                if col == 0 and idx:
                    dynamics_row += 1
                col_base = 0 if col == 0 else 2
                label = tk.Label(
                    stats_frame,
                    text=f"{label_text}:",
                    font=("Consolas", 8),
                    bg=self.theme["panel"],
                    fg=self.theme["muted"],
                )
                label.grid(row=dynamics_row, column=col_base, sticky="w")
                value_label = tk.Label(
                    stats_frame,
                    text=self._format_percent(value),
                    font=("Consolas", 8),
                    bg=self.theme["panel"],
                    fg=self.theme["text"],
                )
                value_label.grid(row=dynamics_row, column=col_base + 1, sticky="e", padx=(0, 8))

            text = tk.Text(frame, wrap="word")
            self._setup_text_widget(text)
            text.pack(fill="both", expand=True)
            logs = self.sim.db.list_ai_logs("civ", civ.id, limit=120)
            self._insert_logs(text, list(reversed(logs)))
            if getattr(civ, "extinct", 0) and not logs:
                text.insert(tk.END, "Dead civilization. Nothing remains.\n", "assistant")
            label = f"{civ.name} [DEAD]" if getattr(civ, "extinct", 0) else civ.name
            self.civ_tabs.add(frame, text=label)
            self.log_texts[civ.id] = text
            self._civ_tab_ids[civ.id] = frame

        self._refresh_civ_overview(civs)
        if hasattr(self, "info_tabs"):
            self._refresh_info_tabs(civs)
        self._refresh_player_targets(civs)

    def _setup_text_widget(self, text: tk.Text) -> None:
        text.configure(
            bg=self.theme["panel"],
            fg=self.theme["text"],
            insertbackground=self.theme["accent"],
        )
        text.tag_configure("header", foreground=self.theme["accent"])
        text.tag_configure("assistant", foreground=self.theme["text"])
        text.tag_configure("prompt", foreground=self.theme["muted"])
        text.tag_configure("god", foreground=self.theme["accent_alt"])
        text.tag_configure("analysis", foreground=self.theme["accent"])

    def _insert_logs(self, text: tk.Text, logs) -> None:
        for log in logs:
            header = f"[C{log.cycle}] {log.role}:\n"
            text.insert(tk.END, header, "header")
            tag = log.role if log.role in ("prompt", "god", "analysis") else "assistant"
            text.insert(tk.END, f"{log.message}\n\n", tag)

    def _render_stats_tab(self, parent: tk.Frame, civs) -> None:
        """Render per-civilization stat bars."""
        for child in parent.winfo_children():
            child.destroy()
        parent.configure(bg=self.theme["panel"])
        canvas = tk.Canvas(parent, bg=self.theme["panel"], highlightthickness=0)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        inner = tk.Frame(canvas, bg=self.theme["panel"])
        canvas.create_window((0, 0), window=inner, anchor="nw")

        header = tk.Label(
            inner,
            text="CIVILIZATION STATS",
            font=("Consolas", 10, "bold"),
            bg=self.theme["panel"],
            fg=self.theme["accent_alt"],
        )
        header.grid(row=0, column=0, columnspan=7, sticky="w", padx=10, pady=(8, 6))

        def bar(parent_widget, value: float) -> ttk.Progressbar:
            p = ttk.Progressbar(parent_widget, length=120, maximum=100)
            p["value"] = int(value * 100)
            return p

        row = 1
        for civ in civs:
            title = tk.Label(
                inner,
                text=f"{civ.name} :: {civ.tech_stage}",
                font=("Consolas", 9, "bold"),
                bg=self.theme["panel"],
                fg=self.theme["text"],
            )
            title.grid(row=row, column=0, columnspan=6, sticky="w", padx=10, pady=(6, 2))
            row += 1

            labels = [
                ("Cohesion", civ.cohesion),
                ("Inequality", civ.inequality),
                ("Eco", civ.eco_pressure),
                ("Innovation", civ.innovation),
                ("Stability", civ.stability),
                ("Food", getattr(civ, "food_security", 0.0)),
                ("Health", getattr(civ, "health", 0.0)),
            ]
            for idx, (name, value) in enumerate(labels):
                lbl = tk.Label(
                    inner,
                    text=name,
                    font=("Consolas", 8),
                    bg=self.theme["panel"],
                    fg=self.theme["muted"],
                )
                lbl.grid(row=row, column=idx, padx=6, pady=(0, 6))
                prog = bar(inner, value)
                prog.grid(row=row + 1, column=idx, padx=6, pady=(0, 10))
            row += 2

        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _render_world_tab(self, parent: tk.Frame) -> None:
        """Render long-term world marks, delayed effects, and settings."""
        for child in parent.winfo_children():
            child.destroy()
        parent.configure(bg=self.theme["panel"])
        text = tk.Text(parent, wrap="word")
        self._setup_text_widget(text)
        text.pack(fill="both", expand=True)

        settings = []
        seed = self.sim.db.get_setting("seed")
        if seed:
            settings.append(f"seed = {seed}")
        marks = self.sim.db.list_world_marks(limit=120)
        effects = self.sim.db.list_due_effects(999999)

        lines = []
        lines.append("== RUN SETTINGS ==")
        lines.extend(settings or ["(none)"])
        lines.append("")

        lines.append("== WORLD MARKS ==")
        if marks:
            for mark in reversed(marks):
                civ = f"CIV{mark.civ_id}" if mark.civ_id else "global"
                lines.append(f"[C{mark.cycle}] {civ} :: {mark.label}")
                lines.append(f"  impact: {mark.impact}")
        else:
            lines.append("(none)")
        lines.append("")

        lines.append("== DELAYED EFFECTS QUEUE ==")
        if effects:
            for effect in effects:
                civ = f"CIV{effect.civ_id}" if effect.civ_id else "global"
                lines.append(f"[due C{effect.cycle_due}] {civ} :: {effect.kind}")
                lines.append(f"  delta: {effect.payload}")
        else:
            lines.append("(none)")

        text.insert(tk.END, "\n".join(lines))

    def _render_chaos_tab(self, parent: tk.Frame) -> None:
        for child in parent.winfo_children():
            child.destroy()
        parent.configure(bg=self.theme["panel"])
        text = tk.Text(parent, wrap="word")
        self._setup_text_widget(text)
        text.pack(fill="both", expand=True)

        seed = self.sim.db.get_setting("seed") or "unknown"
        ended = self.sim.db.get_setting("universe_ended") == "1"
        reason = self.sim.db.get_setting("universe_end_reason") or ""
        cooldowns = self.sim.db.get_setting("event_cooldowns") or "{}"
        try:
            cooldowns_data = json.loads(cooldowns)
            cooldown_count = len(cooldowns_data) if isinstance(cooldowns_data, dict) else 0
        except json.JSONDecodeError:
            cooldown_count = 0

        lines = []
        lines.append("== RULES ENGINE ==")
        lines.append(f"seed = {seed}")
        lines.append(f"universe_ended = {ended}")
        if reason:
            lines.append(f"end_reason = {reason}")
        lines.append(f"cooldowns_tracked = {cooldown_count}")
        lines.append("")

        lines.append("== GLOBAL MARKS ==")
        marks = self.sim.db.list_marks(None)
        lines.extend(marks or ["(none)"])
        lines.append("")

        lines.append("== PENDING EFFECTS ==")
        pending = self.sim.db.list_all_delayed_effects()
        if pending:
            for effect in pending[:20]:
                target = f"CIV{effect.civ_id}" if effect.civ_id else "global"
                lines.append(f"[due C{effect.cycle_due}] {target} :: {effect.kind}")
                lines.append(f"  payload: {effect.payload}")
        else:
            lines.append("(none)")
        lines.append("")

        lines.append("== RECENT RULES EVENTS ==")
        events = self.sim.db.list_events(limit=20)
        if events:
            for event in reversed(events):
                meta = event.metadata if isinstance(event.metadata, dict) else {}
                event_id = meta.get("event_id", event.kind)
                severity = meta.get("severity", "?")
                target = meta.get("target", "-")
                lines.append(f"[C{event.cycle}] {event_id} :: sev={severity} :: {target}")
        else:
            lines.append("(none)")
        lines.append("")
        lines.append("== CIV MARKS ==")
        civs = self.sim.db.list_civilizations()
        for civ in civs:
            marks = self.sim.db.list_marks(civ.id)
            lines.append(f"{civ.name}: " + (", ".join(marks) if marks else "(none)"))

        text.insert(tk.END, "\n".join(lines))
        self.chaos_text = text

    def _render_errors_tab(self, parent: tk.Frame) -> None:
        for child in parent.winfo_children():
            child.destroy()
        parent.configure(bg=self.theme["panel"])
        text = tk.Text(parent, wrap="word")
        self._setup_text_widget(text)
        text.pack(fill="both", expand=True)
        logs = self.sim.db.list_ai_logs("error", None, limit=200)
        self._insert_logs(text, list(reversed(logs)))

    def _refresh_info_tabs(self, civs) -> None:
        if not hasattr(self, "stats_tab"):
            return
        self._render_stats_tab(self.stats_tab, civs)
        self._render_world_tab(self.world_tab)
        self._render_chaos_tab(self.chaos_tab)
        if hasattr(self, "errors_tab"):
            self._render_errors_tab(self.errors_tab)

    def _draw_sparkline(self, canvas: tk.Canvas, civ_id: int, latest_cycle: int) -> None:
        logs = self.sim.db.list_ai_logs("civ", civ_id, limit=60)
        counts = {}
        for log in logs:
            counts[log.cycle] = counts.get(log.cycle, 0) + 1
        points = []
        span = 10
        start = max(latest_cycle - span + 1, 1)
        for i in range(start, latest_cycle + 1):
            points.append(counts.get(i, 0))
        if not points:
            return
        max_val = max(points) or 1
        w = int(canvas["width"])
        h = int(canvas["height"])
        step = w / max(len(points), 1)
        for idx, val in enumerate(points):
            x = int(idx * step)
            y = h - int((val / max_val) * (h - 2)) - 1
            canvas.create_line(x, h, x, y, fill=self.theme["accent"], width=2)

    def _refresh_civ_overview(self, civs) -> None:
        for child in self.civ_overview.winfo_children():
            child.destroy()
        latest = self.sim.db.get_latest_cycle_id()
        header = tk.Frame(self.civ_overview, bg=self.theme["panel_alt"])
        header.pack(fill="x", pady=(0, 4))
        tk.Label(
            header,
            text="CIV",
            bg=self.theme["panel_alt"],
            fg=self.theme["muted"],
            font=("Consolas", 8, "bold"),
            width=18,
            anchor="w",
        ).pack(side="left", padx=(6, 0))
        tk.Label(
            header,
            text="Stage/Progress",
            bg=self.theme["panel_alt"],
            fg=self.theme["muted"],
            font=("Consolas", 8, "bold"),
            width=18,
            anchor="w",
        ).pack(side="left")
        tk.Label(
            header,
            text="Intent",
            bg=self.theme["panel_alt"],
            fg=self.theme["muted"],
            font=("Consolas", 8, "bold"),
            width=16,
            anchor="w",
        ).pack(side="left")
        tk.Label(
            header,
            text="Dynamics",
            bg=self.theme["panel_alt"],
            fg=self.theme["muted"],
            font=("Consolas", 8, "bold"),
            width=18,
            anchor="w",
        ).pack(side="left")
        for civ in civs:
            row = tk.Frame(self.civ_overview, bg=self.theme["panel_alt"])
            row.pack(fill="x", pady=2)
            dot = tk.Canvas(
                row,
                width=12,
                height=12,
                bg=self.theme["panel_alt"],
                highlightthickness=0,
            )
            dot.pack(side="left")
            fill = "#444444" if getattr(civ, "extinct", 0) else civ.color
            dot.create_oval(2, 2, 10, 10, fill=fill, outline="")
            status = "EXTINCT" if getattr(civ, "extinct", 0) else civ.status
            name = tk.Label(
                row,
                text=f"{civ.name} :: {status}",
                bg=self.theme["panel_alt"],
                fg=self.theme["text"],
                font=("Consolas", 9),
                width=18,
                anchor="w",
            )
            name.pack(side="left", padx=(6, 0))
            progress = self._get_civ_progress(civ.id)
            stage = getattr(civ, "tech_stage", "") or "—"
            stage_text = self._format_stage_progress(stage, progress)
            tk.Label(
                row,
                text=stage_text.replace("Stage: ", "").replace("Progress: ", ""),
                bg=self.theme["panel_alt"],
                fg=self.theme["text"],
                font=("Consolas", 9),
                width=18,
                anchor="w",
            ).pack(side="left")
            agenda = self._get_civ_token(civ.id, "civ_agenda") or "—"
            stance = self._get_civ_token(civ.id, "civ_stance") or "—"
            tk.Label(
                row,
                text=f"{agenda}/{stance}",
                bg=self.theme["panel_alt"],
                fg=self.theme["text"],
                font=("Consolas", 9),
                width=16,
                anchor="w",
            ).pack(side="left")
            elite = self._format_percent(getattr(civ, "elite_power", None))
            legit = self._format_percent(getattr(civ, "legitimacy", None))
            extract = self._format_percent(getattr(civ, "extraction_rate", None))
            tk.Label(
                row,
                text=f"E{elite} L{legit} X{extract}",
                bg=self.theme["panel_alt"],
                fg=self.theme["text"],
                font=("Consolas", 9),
                width=18,
                anchor="w",
            ).pack(side="left")
            spark = tk.Canvas(
                row,
                width=70,
                height=12,
                bg=self.theme["panel_alt"],
                highlightthickness=0,
            )
            spark.pack(side="right", padx=6)
            self._draw_sparkline(spark, civ.id, latest)

    def _refresh_player_targets(self, civs) -> None:
        options = ["All civilizations"] + [civ.name for civ in civs]
        if hasattr(self, "player_combo"):
            self.player_combo.configure(values=options)
            if not self.player_combo.get():
                self.player_combo.set(options[0])
        if hasattr(self, "command_target"):
            command_options = ["global"] + [civ.name for civ in civs]
            self.command_target.configure(values=command_options)
            if not self.command_target.get():
                self.command_target.set(command_options[0])

    def _queue_player_directive(self) -> None:
        if not hasattr(self, "player_text"):
            return
        text = self.player_text.get("1.0", tk.END).strip()
        if not text:
            return
        target = self.player_combo.get().strip()
        if target == "All civilizations":
            target_key = "all"
        else:
            target_key = target
        self.sim.db.set_setting("player_directive_text", text)
        self.sim.db.set_setting("player_directive_target", target_key)
        self.player_text.delete("1.0", tk.END)

    def _queue_player_command(self) -> None:
        if not hasattr(self, "command_type"):
            return
        command_type = self.command_type.get().strip()
        arg = self.command_arg.get().strip() if hasattr(self, "command_arg") else ""
        target = self.command_target.get().strip() if hasattr(self, "command_target") else ""
        if not command_type:
            return
        payload = {"type": command_type}
        if command_type == "END_UNIVERSE":
            payload["reason"] = arg or "Player command"
        elif command_type == "KILL_CIV":
            if not target or target == "global":
                return
            payload["civ_id"] = self._civ_id_for_name(target)
        elif command_type == "FORCE_EVENT":
            payload["event_id"] = arg
            if target and target != "global":
                payload["target"] = self._civ_id_for_name(target)
            else:
                payload["target"] = "global"
        elif command_type == "SET_GLOBAL_MARK":
            payload["mark"] = arg
        if "civ_id" in payload and payload["civ_id"] is None:
            return
        if payload.get("target") is None:
            return
        self.sim.db.set_setting("player_command_json", json.dumps(payload))
        if hasattr(self, "command_arg"):
            self.command_arg.delete(0, tk.END)

    def _civ_id_for_name(self, name: str):
        for civ in self.sim.db.list_civilizations():
            if civ.name == name:
                return civ.id
        return None
