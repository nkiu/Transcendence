import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from db import Database
from llm import LLMClient
from sim import Simulation
from ui import AppUI


def select_db_path() -> tuple[str, bool, str]:
    os.makedirs("data", exist_ok=True)
    chooser = tk.Tk()
    chooser.withdraw()

    selected = {"path": "", "ollama_on": True, "model": ""}
    llm = LLMClient(mode="ollama")

    def pick_new() -> None:
        name = simpledialog.askstring(
            "New Game", "Game name (letters/numbers):", parent=chooser
        )
        if not name:
            return
        filename = f"{name.strip().replace(' ', '_')}.db"
        selected["path"] = os.path.join("data", filename)
        dialog.destroy()

    def pick_load() -> None:
        path = filedialog.askopenfilename(
            title="Load Game",
            initialdir="data",
            filetypes=[("SQLite DB", "*.db")],
        )
        if path:
            selected["path"] = path
            dialog.destroy()

    def cancel() -> None:
        dialog.destroy()

    def refresh_models() -> None:
        ok = llm.healthcheck()
        if ok:
            status_var.set("OLLAMA: ONLINE")
            status_label.configure(fg="#1a8b5a")
            models = llm.list_models()
            if models:
                model_combo.configure(values=models, state="readonly")
                model_combo.set(models[0])
                selected["model"] = models[0]
            else:
                model_combo.configure(values=[], state="normal")
                model_combo.set("")
        else:
            status_var.set("OLLAMA: OFFLINE")
            status_label.configure(fg="#b34747")
            model_combo.configure(values=[], state="normal")
            model_combo.set("")

    def on_model_change(_event: tk.Event) -> None:
        value = model_combo.get().strip()
        if value:
            selected["model"] = value

    def toggle_ollama() -> None:
        selected["ollama_on"] = bool(ollama_var.get())

    dialog = tk.Toplevel(chooser)
    dialog.title("Select Game")
    dialog.geometry("420x320")
    dialog.resizable(False, False)

    label = tk.Label(
        dialog,
        text="Create a new game or load an existing one.",
        font=("Helvetica", 11),
    )
    label.pack(pady=14)

    btns = tk.Frame(dialog)
    btns.pack(pady=8)

    tk.Button(btns, text="New Game", width=12, command=pick_new).pack(
        side="left", padx=6
    )
    tk.Button(btns, text="Load Game", width=12, command=pick_load).pack(
        side="left", padx=6
    )

    llm_frame = tk.Frame(dialog)
    llm_frame.pack(fill="x", padx=12, pady=(12, 0))

    status_var = tk.StringVar(value="OLLAMA: checking...")
    status_label = tk.Label(llm_frame, textvariable=status_var, font=("Helvetica", 10))
    status_label.pack(anchor="w")

    ollama_var = tk.BooleanVar(value=True)
    ollama_toggle = tk.Checkbutton(
        llm_frame, text="Enable Ollama", variable=ollama_var, command=toggle_ollama
    )
    ollama_toggle.pack(anchor="w", pady=(6, 4))

    model_row = tk.Frame(llm_frame)
    model_row.pack(fill="x", pady=(2, 4))
    tk.Label(model_row, text="Model:").pack(side="left")
    model_combo = ttk.Combobox(model_row, values=[], width=28)
    model_combo.pack(side="left", padx=6)
    model_combo.bind("<<ComboboxSelected>>", on_model_change)

    tk.Button(llm_frame, text="Refresh Models", command=refresh_models).pack(
        anchor="w", pady=(4, 6)
    )

    tk.Button(dialog, text="Cancel", width=12, command=cancel).pack(pady=8)

    refresh_models()

    chooser.wait_window(dialog)
    chooser.destroy()

    if not selected["path"]:
        messagebox.showinfo("No game selected", "Exiting application.")
    return selected["path"], selected["ollama_on"], selected["model"]


def main() -> None:
    db_path, ollama_on, model = select_db_path()
    if not db_path:
        return
    os.environ["OLLAMA_ON"] = "1" if ollama_on else "0"
    if model:
        os.environ["OLLAMA_MODEL"] = model
    db = Database(db_path)
    sim = Simulation(db)

    root = tk.Tk()
    root.title("Transcendence - Universe Sim")
    root.geometry("1000x650")

    app = AppUI(root, sim)
    app.pack(fill="both", expand=True)

    root.mainloop()


if __name__ == "__main__":
    main()
