import datetime as dt
import glob
import importlib.util
import logging
import os
import queue
import re
import sqlite3
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from lib.db import Database
from lib.llm import LLMClient
from lib.sim import Simulation
from lib.ui import AppUI
from prompts.prompts_design import (
    DEFAULT_CIV_GEN_PROMPT,
    DEFAULT_CIV_THOUGHT_PROMPT,
    DEFAULT_EVENTS_PROMPT,
    DEFAULT_MASTER_PROMPT,
)
from rulesets import list_available_rulesets

DEFAULT_MASTER_SEED = ""
DEFAULT_CIV_SEED = ""
DEFAULT_CHAOS_SEED = ""
SAVED_PROMPTS_LABEL = "Saved (DB)"


def _load_prompt_sets() -> dict:
    files = sorted(set(glob.glob(os.path.join("prompts", "*.py"))))
    prompt_sets = {}

    def extract_templates(module) -> dict:
        keys = [
            ("EVENTS_PROMPT", "DEFAULT_EVENTS_PROMPT", "FLAVOR_PROMPT"),
            ("CIV_GEN_PROMPT", "DEFAULT_CIV_GEN_PROMPT", "CIV_SEED_PROMPT"),
            ("CIV_THOUGHT_PROMPT", "DEFAULT_CIV_THOUGHT_PROMPT", "CIV_NARRATOR_PROMPT"),
            ("MASTER_PROMPT", "DEFAULT_MASTER_PROMPT", "MASTER_OBSERVER_PROMPT"),
        ]
        templates = {}
        for primary, fallback, alt in keys:
            exact = getattr(module, primary, None)
            if exact is None:
                exact = getattr(module, alt, None)
            if exact is None:
                exact = getattr(module, fallback, None)
            if isinstance(exact, str):
                templates[primary] = exact
                continue
            candidates = [
                name
                for name in dir(module)
                if name.startswith(primary) and isinstance(getattr(module, name), str)
            ]
            if candidates:
                templates[primary] = getattr(module, sorted(candidates)[0])
        if len(templates) != 4:
            return {}
        return templates

    for path in files:
        module_name = os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(module_name, path)
        if not spec or not spec.loader:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            logging.debug("Failed to load prompt module %s: %s", path, e)
            continue
        templates = extract_templates(module)
        if not templates:
            continue
        match = re.search(r"v(\d+)", module_name)
        if module_name == "prompts_design":
            label = "v1"
        else:
            label = f"v{match.group(1)}" if match else "default"
        prompt_sets[label] = {
            "events": templates["EVENTS_PROMPT"],
            "civ_gen": templates["CIV_GEN_PROMPT"],
            "civ_thought": templates["CIV_THOUGHT_PROMPT"],
            "master": templates["MASTER_PROMPT"],
        }
    if not prompt_sets:
        prompt_sets["default"] = {
            "events": DEFAULT_EVENTS_PROMPT,
            "civ_gen": DEFAULT_CIV_GEN_PROMPT,
            "civ_thought": DEFAULT_CIV_THOUGHT_PROMPT,
            "master": DEFAULT_MASTER_PROMPT,
        }
    return prompt_sets


def select_db_path() -> tuple[str, bool, str, str, str, str, str, dict, str]:
    os.makedirs("data", exist_ok=True)
    chooser = tk.Tk()
    chooser.withdraw()

    prompt_sets = _load_prompt_sets()
    selected = {
        "path": "",
        "ollama_on": True,
        "model": "",
        "backend": "ollama",
        "ruleset": "harsh_realism",
        "prompt_master": DEFAULT_MASTER_SEED,
        "prompt_civ": DEFAULT_CIV_SEED,
        "prompt_chaos": DEFAULT_CHAOS_SEED,
        "templates": {
            "events": DEFAULT_EVENTS_PROMPT,
            "civ_gen": DEFAULT_CIV_GEN_PROMPT,
            "civ_thought": DEFAULT_CIV_THOUGHT_PROMPT,
            "master": DEFAULT_MASTER_PROMPT,
        },
    }
    llm = LLMClient(mode="ollama")

    def pick_new() -> None:
        name = simpledialog.askstring(
            "New Game", "Game name (letters/numbers):", parent=chooser
        )
        if not name:
            return
        filename = f"{name.strip().replace(' ', '_')}.db"
        selected["path"] = os.path.join("data", filename)
        path_var.set(selected["path"])
        prompt_set_combo.set(default_prompt_set)
        prompt_set_label.configure(text=default_prompt_set)
        _apply_prompt_set(default_prompt_set)
        ruleset_combo.set("harsh_realism")
        selected["ruleset"] = "harsh_realism"
        db_preview_text.configure(state="normal")
        db_preview_text.delete("1.0", tk.END)
        db_preview_text.insert(
            tk.END, "New game selected. Database preview will appear after save."
        )
        db_preview_text.configure(state="disabled")

    def pick_load() -> None:
        path = filedialog.askopenfilename(
            title="Load Game",
            initialdir="data",
            filetypes=[("SQLite DB", "*.db")],
        )
        if path:
            selected["path"] = path
            path_var.set(path)
            _load_prompts_from_db(path)
            _render_db_preview(path)
            screen_tabs.select(db_tab)

    def cancel() -> None:
        selected["path"] = ""
        dialog.destroy()

    def refresh_models_with(client: LLMClient) -> None:
        ok = client.healthcheck()
        backend_label = "LLAMA.CPP" if client.backend_type == "llamacpp" else "OLLAMA"
        if ok:
            status_var.set(f"{backend_label}: ONLINE")
            status_label.configure(fg="#1a8b5a")
            models = client.list_models()
            if models:
                model_combo.configure(values=models, state="readonly")
                model_combo.set(models[0])
                selected["model"] = models[0]
            else:
                model_combo.configure(values=[], state="normal")
                model_combo.set("")
        else:
            status_var.set(f"{backend_label}: OFFLINE")
            status_label.configure(fg="#b34747")
            model_combo.configure(values=[], state="normal")
            model_combo.set("")

    def refresh_models() -> None:
        backend = selected.get("backend", "ollama")
        client = LLMClient(mode="ollama", backend=backend)
        refresh_models_with(client)

    def on_model_change(_event: tk.Event) -> None:
        value = model_combo.get().strip()
        if value:
            selected["model"] = value

    def toggle_ollama() -> None:
        selected["ollama_on"] = bool(ollama_var.get())

    def toggle_no_llm() -> None:
        no_llm = bool(no_llm_var.get())
        if no_llm:
            ollama_var.set(False)
            selected["ollama_on"] = False
            ollama_toggle.configure(state="disabled")
            llamacpp_toggle.configure(state="disabled")
            model_combo.configure(state="disabled")
        else:
            ollama_toggle.configure(state="normal")
            llamacpp_toggle.configure(state="normal")
            model_combo.configure(state="normal")
            selected["ollama_on"] = bool(ollama_var.get())

    def toggle_llamacpp() -> None:
        use_llamacpp = bool(llamacpp_var.get())
        if use_llamacpp:
            selected["backend"] = "llamacpp"
            ollama_var.set(True)
            selected["ollama_on"] = True
            ollama_toggle.configure(state="disabled")
            llm = LLMClient(mode="ollama", backend="llamacpp")
            refresh_models_with(llm)
        else:
            selected["backend"] = "ollama"
            ollama_toggle.configure(state="normal")
            llm = LLMClient(mode="ollama", backend="ollama")
            refresh_models_with(llm)

    def _load_prompts_from_db(path: str) -> None:
        try:
            db = Database(path)
            events_prompt.delete("1.0", tk.END)
            civ_gen_prompt.delete("1.0", tk.END)
            civ_thought_prompt.delete("1.0", tk.END)
            master_prompt.delete("1.0", tk.END)
            ruleset_name = db.get_setting("ruleset_name") or "harsh_realism"
            ruleset_combo.set(ruleset_name)
            selected["ruleset"] = ruleset_name
            events_prompt.insert(
                tk.END,
                db.get_setting("prompt_events") or DEFAULT_EVENTS_PROMPT,
            )
            civ_gen_prompt.insert(
                tk.END,
                db.get_setting("prompt_civ_gen") or DEFAULT_CIV_GEN_PROMPT,
            )
            civ_thought_prompt.insert(
                tk.END,
                db.get_setting("prompt_civ_thought") or DEFAULT_CIV_THOUGHT_PROMPT,
            )
            master_prompt.insert(
                tk.END,
                db.get_setting("prompt_master_template") or DEFAULT_MASTER_PROMPT,
            )
            db.close()
            prompt_set_combo.set(SAVED_PROMPTS_LABEL)
        except Exception as e:
            logging.debug("Failed to load prompts from DB: %s", e)

    def start_game() -> None:
        if not selected["path"]:
            messagebox.showinfo("Select game", "Pick or create a game first.")
            return
        ruleset_name = ruleset_combo.get().strip() or "harsh_realism"
        selected["ruleset"] = ruleset_name
        selected["prompt_master"] = DEFAULT_MASTER_SEED
        selected["prompt_civ"] = DEFAULT_CIV_SEED
        selected["prompt_chaos"] = DEFAULT_CHAOS_SEED
        selected["templates"] = {
            "events": events_prompt.get("1.0", tk.END).strip()
            or DEFAULT_EVENTS_PROMPT,
            "civ_gen": civ_gen_prompt.get("1.0", tk.END).strip()
            or DEFAULT_CIV_GEN_PROMPT,
            "civ_thought": civ_thought_prompt.get("1.0", tk.END).strip()
            or DEFAULT_CIV_THOUGHT_PROMPT,
            "master": master_prompt.get("1.0", tk.END).strip()
            or DEFAULT_MASTER_PROMPT,
        }
        dialog.destroy()

    dialog = tk.Toplevel(chooser)
    dialog.title("Select Game")
    dialog.geometry("640x620")
    dialog.resizable(False, False)

    header = tk.Label(
        dialog,
        text="Create or load a game, then review prompts.",
        font=("Helvetica", 11),
    )
    header.pack(pady=10)

    screen_tabs = ttk.Notebook(dialog)
    screen_tabs.pack(fill="both", expand=True, padx=12, pady=6)

    game_tab = tk.Frame(screen_tabs)
    prompt_tab = tk.Frame(screen_tabs)
    db_tab = tk.Frame(screen_tabs)
    about_tab = tk.Frame(screen_tabs)
    screen_tabs.add(game_tab, text="Game")
    screen_tabs.add(prompt_tab, text="Prompts")
    screen_tabs.add(db_tab, text="Database")
    screen_tabs.add(about_tab, text="About")

    btns = tk.Frame(game_tab)
    btns.pack(pady=6)

    tk.Button(btns, text="New Game", width=12, command=pick_new).pack(
        side="left", padx=6
    )
    tk.Button(btns, text="Load Game", width=12, command=pick_load).pack(
        side="left", padx=6
    )

    path_var = tk.StringVar(value="")
    path_label = tk.Label(game_tab, textvariable=path_var, font=("Helvetica", 9))
    path_label.pack(pady=(4, 0))

    llm_frame = tk.Frame(game_tab)
    llm_frame.pack(fill="x", padx=12, pady=(12, 0))

    status_var = tk.StringVar(value="OLLAMA: checking...")
    status_label = tk.Label(llm_frame, textvariable=status_var, font=("Helvetica", 10))
    status_label.pack(anchor="w")

    ollama_var = tk.BooleanVar(value=True)
    ollama_toggle = tk.Checkbutton(
        llm_frame, text="Enable Ollama", variable=ollama_var, command=toggle_ollama
    )
    ollama_toggle.pack(anchor="w", pady=(6, 4))
    no_llm_var = tk.BooleanVar(value=False)
    no_llm_toggle = tk.Checkbutton(
        llm_frame, text="No LLM (deterministic)", variable=no_llm_var, command=toggle_no_llm
    )
    no_llm_toggle.pack(anchor="w", pady=(0, 2))
    llamacpp_var = tk.BooleanVar(value=False)
    llamacpp_toggle = tk.Checkbutton(
        llm_frame, text="Use llama.cpp backend", variable=llamacpp_var, command=toggle_llamacpp
    )
    llamacpp_toggle.pack(anchor="w", pady=(0, 6))

    model_row = tk.Frame(llm_frame)
    model_row.pack(fill="x", pady=(2, 4))
    tk.Label(model_row, text="Model:").pack(side="left")
    model_combo = ttk.Combobox(model_row, values=[], width=28)
    model_combo.pack(side="left", padx=6)
    model_combo.bind("<<ComboboxSelected>>", on_model_change)

    prompt_row = tk.Frame(llm_frame)
    prompt_row.pack(fill="x", pady=(2, 4))
    tk.Label(prompt_row, text="Prompt set:").pack(side="left")
    prompt_set_keys = sorted(prompt_sets.keys())
    prompt_set_combo = ttk.Combobox(
        prompt_row,
        values=[SAVED_PROMPTS_LABEL] + prompt_set_keys,
        state="readonly",
        width=20,
    )
    prompt_set_combo.pack(side="left", padx=6)
    def _pick_latest_prompt_set(keys):
        versions = []
        for key in keys:
            match = re.match(r"v(\d+)$", key)
            if match:
                versions.append((int(match.group(1)), key))
        if versions:
            return sorted(versions)[-1][1]
        return keys[0] if keys else "default"

    default_prompt_set = _pick_latest_prompt_set(prompt_set_keys)
    prompt_set_combo.set(default_prompt_set)

    ruleset_row = tk.Frame(llm_frame)
    ruleset_row.pack(fill="x", pady=(2, 4))
    tk.Label(ruleset_row, text="Ruleset:").pack(side="left")
    ruleset_values = [name for name, _desc in list_available_rulesets()]
    ruleset_combo = ttk.Combobox(
        ruleset_row, values=ruleset_values, state="readonly", width=24
    )
    ruleset_combo.pack(side="left", padx=6)
    ruleset_combo.set("harsh_realism")

    about_text = tk.Text(about_tab, wrap="word", height=18)
    about_text.pack(fill="both", expand=True, padx=12, pady=12)
    about_content = (
        "TRANSCENDENCE\n"
        "v7_llama.cpp\n\n"
        "Created by Denis Prim - January 2026\n\n"
        "TRANSCENDENCE is an experimental simulation exploring how civilizations emerge, "
        "struggle, progress, and collapse under DND-like rule systems.\n\n"
        "Local OLLAMA-powered LLMs are used not as decision-makers,"
        "but as witnesses - narrating what civilizations believe they are living,"
        "while the rules decide what actually happens.\n\n"
        "This project is a personal experiment.\nNot really a game, and not really a simulation.\n\n"
        "Coded by hand, with curiosity, "
        "and the support of OpenAI CODEX.\n\n"
        "http://denis.prim.swiss\n"
    )
    about_text.insert("1.0", about_content)
    about_text.configure(state="disabled")

    tk.Button(llm_frame, text="Refresh Models", command=refresh_models).pack(
        anchor="w", pady=(4, 6)
    )

    prompt_header = tk.Label(
        prompt_tab,
        text="Prompt set: ",
        font=("Helvetica", 10),
    )
    prompt_header.pack(anchor="w", padx=6, pady=(6, 2))
    prompt_set_label = tk.Label(
        prompt_tab,
        text=prompt_set_combo.get(),
        font=("Helvetica", 10, "bold"),
    )
    prompt_set_label.pack(anchor="w", padx=6, pady=(0, 4))

    template_tabs = ttk.Notebook(prompt_tab)
    template_tabs.pack(fill="both", expand=True, padx=6, pady=6)

    def _make_template_tab(title: str) -> tk.Text:
        frame = tk.Frame(template_tabs)
        text = tk.Text(frame, height=8, width=60)
        text.pack(fill="both", expand=True)
        template_tabs.add(frame, text=title)
        return text

    events_prompt = _make_template_tab("Events")
    civ_gen_prompt = _make_template_tab("Civ Gen")
    civ_thought_prompt = _make_template_tab("Civ Thought")
    master_prompt = _make_template_tab("Master")

    def _apply_prompt_set(label: str) -> None:
        if label == SAVED_PROMPTS_LABEL:
            return
        templates = prompt_sets.get(label)
        if not templates:
            return
        for widget, key in (
            (events_prompt, "events"),
            (civ_gen_prompt, "civ_gen"),
            (civ_thought_prompt, "civ_thought"),
            (master_prompt, "master"),
        ):
            widget.delete("1.0", tk.END)
            widget.insert(tk.END, templates[key])

    def on_prompt_set_change(_event: tk.Event) -> None:
        label = prompt_set_combo.get().strip()
        prompt_set_label.configure(text=label)
        _apply_prompt_set(label)

    prompt_set_combo.bind("<<ComboboxSelected>>", on_prompt_set_change)
    prompt_set_label.configure(text=default_prompt_set)
    _apply_prompt_set(default_prompt_set)

    db_header = tk.Label(
        db_tab,
        text="Database preview (read-only).",
        font=("Helvetica", 10),
    )
    db_header.pack(anchor="w", padx=6, pady=(6, 2))
    db_preview_frame = tk.Frame(db_tab)
    db_preview_frame.pack(fill="both", expand=True, padx=6, pady=6)
    db_preview_scroll = ttk.Scrollbar(db_preview_frame, orient="vertical")
    db_preview_text = tk.Text(
        db_preview_frame, height=10, width=60, yscrollcommand=db_preview_scroll.set
    )
    db_preview_scroll.configure(command=db_preview_text.yview)
    db_preview_text.pack(side="left", fill="both", expand=True)
    db_preview_scroll.pack(side="right", fill="y")
    db_preview_text.insert(
        tk.END, "Load a game to preview the database contents."
    )

    def _render_db_preview(path: str) -> None:
        db_preview_text.configure(state="normal")
        db_preview_text.delete("1.0", tk.END)
        if not path or not os.path.exists(path):
            db_preview_text.insert(tk.END, "Database not found.")
            db_preview_text.configure(state="disabled")
            return
        try:
            stat = os.stat(path)
            lines = []
            lines.append(f"Path: {path}")
            lines.append(f"Size: {stat.st_size} bytes")
            modified = dt.datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" ", timespec="seconds")
            lines.append(f"Modified: {modified}")
            lines.append("")
            with sqlite3.connect(path) as conn:
                cur = conn.cursor()
                counts = {}
                for table in (
                    "cycles",
                    "events",
                    "civilizations",
                    "systems",
                    "planets",
                    "ai_logs",
                    "world_marks",
                    "delayed_effects",
                    "chaos_profiles",
                ):
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {table}")
                        counts[table] = cur.fetchone()[0]
                    except sqlite3.Error:
                        counts[table] = "?"
                cur.execute("SELECT MAX(id) FROM cycles")
                latest_cycle = cur.fetchone()[0]
                lines.append("== COUNTS ==")
                for key, value in counts.items():
                    lines.append(f"{key}: {value}")
                lines.append("")
                lines.append(f"Latest cycle: {latest_cycle or 0}")
                cur.execute(
                    "SELECT id, summary FROM cycles ORDER BY id DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    lines.append(f"Last cycle summary: {row[1] or ''}")
                lines.append("")
                cur.execute(
                    "SELECT name, color, tech_stage, level "
                    "FROM civilizations ORDER BY id LIMIT 8"
                )
                civs = cur.fetchall()
                lines.append("== CIVILIZATIONS (sample) ==")
                if civs:
                    for name, color, tech_stage, level in civs:
                        lines.append(
                            f"- {name} [{color}] :: {tech_stage} :: {level}"
                        )
                else:
                    lines.append("(none)")
                lines.append("")
                cur.execute(
                    "SELECT cycle, title FROM events ORDER BY id DESC LIMIT 5"
                )
                events = cur.fetchall()
                lines.append("== RECENT EVENTS ==")
                if events:
                    for cycle, title in events:
                        lines.append(f"[C{cycle}] {title}")
                else:
                    lines.append("(none)")
            db_preview_text.insert(tk.END, "\n".join(lines))
        except Exception as exc:
            db_preview_text.insert(tk.END, f"Preview failed: {exc}")
        db_preview_text.configure(state="disabled")

    action_row = tk.Frame(dialog)
    action_row.pack(pady=6)
    tk.Button(action_row, text="Start", width=12, command=start_game).pack(
        side="left", padx=6
    )
    tk.Button(action_row, text="Cancel", width=12, command=cancel).pack(
        side="left", padx=6
    )

    refresh_models()

    chooser.wait_window(dialog)
    chooser.destroy()

    if not selected["path"]:
        messagebox.showinfo("No game selected", "Exiting application.")
    return (
        selected["path"],
        selected["ollama_on"],
        selected["model"],
        selected["ruleset"],
        selected["prompt_master"],
        selected["prompt_civ"],
        selected["prompt_chaos"],
        selected["templates"],
        selected["backend"],
    )


def main() -> None:
    (
        db_path,
        ollama_on,
        model,
        ruleset_name,
        prompt_master,
        prompt_civ,
        prompt_chaos,
        templates,
        backend,
    ) = select_db_path()
    if not db_path:
        return
    root = tk.Tk()
    root.title("Transcendence - Universe Sim - V7_llama.cpp")
    root.geometry("1000x650")
    loading = tk.Frame(root)
    loading.pack(fill="both", expand=True)
    tk.Label(
        loading,
        text="Initializing universe...\nThis may take a moment.",
        font=("Consolas", 12),
    ).pack(expand=True)
    progress = ttk.Progressbar(loading, mode="indeterminate", length=240)
    progress.pack(pady=10)
    progress.start(10)

    init_queue: queue.Queue = queue.Queue()

    def init_worker() -> None:
        try:
            os.environ["OLLAMA_ON"] = "1" if ollama_on else "0"
            os.environ["LLM_BACKEND"] = backend
            if model:
                os.environ["OLLAMA_MODEL"] = model
            db = Database(db_path)
            db.set_setting("llm_model", model if ollama_on else "")
            db.set_setting("llm_backend", backend)
            db.set_setting("prompt_master", prompt_master)
            db.set_setting("prompt_civ", prompt_civ)
            db.set_setting("prompt_chaos", prompt_chaos)
            db.set_setting("ruleset_name", ruleset_name or "harsh_realism")
            db.set_setting("llm_enabled", "1" if ollama_on else "0")
            db.set_setting("prompt_events", templates["events"])
            db.set_setting("prompt_civ_gen", templates["civ_gen"])
            db.set_setting("prompt_civ_thought", templates["civ_thought"])
            db.set_setting("prompt_master_template", templates["master"])
            sim = Simulation(db)
            init_queue.put(("ok", sim))
        except Exception as exc:
            init_queue.put(("err", exc))

    def check_init() -> None:
        try:
            status, payload = init_queue.get_nowait()
        except queue.Empty:
            root.after(100, check_init)
            return
        progress.stop()
        loading.destroy()
        if status == "err":
            tk.Label(root, text=f"Init failed: {payload}").pack(pady=20)
            return
        app = AppUI(root, payload)
        app.pack(fill="both", expand=True)

    threading.Thread(target=init_worker, daemon=True).start()
    root.after(100, check_init)
    root.mainloop()


if __name__ == "__main__":
    main()
