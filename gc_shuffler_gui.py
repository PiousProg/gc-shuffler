#!/usr/bin/env python3
"""GC Shuffler GUI: a Tkinter front-end for gc_shuffler.

Pick your Dolphin executable and games folder, set the interval and session
length, then press Start. The window shows the current game, a countdown, how
many times each game has come up, and a log. Settings are remembered between
runs in ``gc_shuffler_gui.json`` next to this script.

Requires gc_shuffler.py in the same folder (it provides the Dolphin helpers).
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, Optional

import gc_shuffler as core  # Also enforces the Windows-only check.

# When packaged with PyInstaller, __file__ points to a temporary folder that is
# deleted on exit, so store the settings next to the .exe instead.
_BASE_DIR = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
             else os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(_BASE_DIR, "gc_shuffler_gui.json")

DEFAULTS = {
    "dolphin": "",
    "games_dir": "",
    "interval": "60",
    "hours": "3",
    "boot_wait": "12",
    "state_delay": "2",
    "load_hotkey": "f1",
    "save_hotkey": "shift+f1",
    "allow_repeat": False,
}


class Session(threading.Thread):
    """Runs the shuffle loop in the background and reports through a queue."""

    def __init__(self, cfg: Dict, games: list, events: "queue.Queue"):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.games = games
        self.events = events
        self.stop_event = threading.Event()
        self.process: Optional[subprocess.Popen] = None
        self.dolphin_gone = False

    def stop(self) -> None:
        self.stop_event.set()

    # -- helpers ----------------------------------------------------------- #
    def _log(self, text: str) -> None:
        self.events.put(("log", text))

    def _wait(self, seconds: float, phase: str, game: str, rnd: int, session_end: float) -> bool:
        """Sleep in small steps. Return False if stopped or Dolphin vanished."""
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_event.is_set():
                return False
            if self.process is not None and self.process.poll() is not None:
                self.dolphin_gone = True
                return False
            self.events.put(("status", {
                "phase": phase,
                "game": game,
                "round": rnd,
                "phase_left": max(0.0, end - time.time()),
                "phase_total": seconds,
                "session_left": max(0.0, session_end - time.time()),
            }))
            time.sleep(0.2)
        return True

    # -- main loop --------------------------------------------------------- #
    def run(self) -> None:
        try:
            self._loop()
        except Exception as exc:  # Report anything unexpected to the UI.
            self._log(f"ERROR: {exc}")
            core.close_dolphin(self.process)
        finally:
            self.events.put(("done", None))

    def _loop(self) -> None:
        c = self.cfg
        load_keys = core.parse_hotkey(c["load_hotkey"])
        save_keys = core.parse_hotkey(c["save_hotkey"])
        session_end = time.time() + c["hours"] * 3600
        previous = None
        rnd = 0

        while not self.stop_event.is_set() and time.time() < session_end:
            rnd += 1
            game = core.pick_next_game(self.games, previous, c["allow_repeat"])
            name = os.path.splitext(os.path.basename(game))[0]
            self._log(f"[Round {rnd}] {name}")
            self.events.put(("played", game))
            self.dolphin_gone = False
            ready = False  # True once the saved state has been loaded.

            self.process = core.launch_dolphin(c["dolphin"], game)
            if self._wait(c["boot_wait"], "Booting", name, rnd, session_end):
                core.send_hotkey(load_keys)  # No-op if no state exists yet.
                ready = True
                if self._wait(c["state_delay"], "Loading state", name, rnd, session_end):
                    play = max(0.0, min(c["interval"], session_end - time.time()))
                    self._wait(play, "Playing", name, rnd, session_end)

            # Only save if the old state was loaded first; otherwise a quick
            # stop would overwrite real progress with a fresh boot.
            if ready and not self.dolphin_gone:
                core.send_hotkey(save_keys)
                time.sleep(c["state_delay"])
            elif self.dolphin_gone:
                self._log("  Dolphin was closed manually, skipping save.")

            core.close_dolphin(self.process)
            self.process = None
            previous = game
            time.sleep(1)  # Let Dolphin release its files.

        self._log("Session stopped." if self.stop_event.is_set() else "Session finished.")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("GC Shuffler")
        self.minsize(640, 620)
        self.events: "queue.Queue" = queue.Queue()
        self.session: Optional[Session] = None
        self.plays: Dict[str, int] = {}
        self.games: list = []

        cfg = dict(DEFAULTS)
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                cfg.update(json.load(fh))
        except (OSError, ValueError):
            pass
        if not cfg["dolphin"]:
            cfg["dolphin"] = next((p for p in core.DOLPHIN_CANDIDATES if os.path.isfile(p)), "")

        self.vars = {
            key: (tk.BooleanVar(value=val) if isinstance(val, bool) else tk.StringVar(value=val))
            for key, val in cfg.items()
        }
        self._build_ui()
        self._scan_games()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_events)

    # -- UI construction --------------------------------------------------- #
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)

        # Settings
        box = ttk.LabelFrame(root, text="Settings")
        box.pack(fill="x", **pad)
        box.columnconfigure(1, weight=1)
        self.setting_widgets = []

        def path_row(row, label, key, browse):
            ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", **pad)
            entry = ttk.Entry(box, textvariable=self.vars[key])
            entry.grid(row=row, column=1, sticky="ew", **pad)
            button = ttk.Button(box, text="Browse...", command=browse)
            button.grid(row=row, column=2, **pad)
            self.setting_widgets += [entry, button]

        path_row(0, "Dolphin.exe", "dolphin", self._browse_dolphin)
        path_row(1, "Games folder", "games_dir", self._browse_games)

        grid = ttk.Frame(box)
        grid.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)
        fields = [
            ("Seconds per game", "interval"), ("Session (hours)", "hours"),
            ("Boot wait (s)", "boot_wait"), ("State delay (s)", "state_delay"),
            ("Load hotkey", "load_hotkey"), ("Save hotkey", "save_hotkey"),
        ]
        for i, (label, key) in enumerate(fields):
            r, col = divmod(i, 3)
            ttk.Label(grid, text=label).grid(row=r, column=col * 2, sticky="w", padx=(0, 4), pady=3)
            entry = ttk.Entry(grid, textvariable=self.vars[key], width=10)
            entry.grid(row=r, column=col * 2 + 1, sticky="w", padx=(0, 16), pady=3)
            self.setting_widgets.append(entry)
        check = ttk.Checkbutton(box, text="Allow the same game twice in a row",
                                variable=self.vars["allow_repeat"])
        check.grid(row=3, column=0, columnspan=3, sticky="w", **pad)
        self.setting_widgets.append(check)

        # Controls
        controls = ttk.Frame(root)
        controls.pack(fill="x", **pad)
        self.start_btn = ttk.Button(controls, text="Start", command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(controls, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=8)

        # Status
        status = ttk.LabelFrame(root, text="Status")
        status.pack(fill="x", **pad)
        self.game_label = ttk.Label(status, text="Idle", font=("Segoe UI", 14, "bold"))
        self.game_label.pack(anchor="w", padx=8, pady=(6, 0))
        self.phase_label = ttk.Label(status, text="")
        self.phase_label.pack(anchor="w", padx=8)
        self.bar = ttk.Progressbar(status, maximum=1.0)
        self.bar.pack(fill="x", padx=8, pady=4)
        self.session_label = ttk.Label(status, text="")
        self.session_label.pack(anchor="w", padx=8, pady=(0, 6))

        # Games
        games_box = ttk.LabelFrame(root, text="Games")
        games_box.pack(fill="both", expand=True, **pad)
        self.tree = ttk.Treeview(games_box, columns=("plays",), height=6)
        self.tree.heading("#0", text="Game")
        self.tree.heading("plays", text="Times played")
        self.tree.column("plays", width=100, anchor="center", stretch=False)
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)

        # Log
        log_box = ttk.LabelFrame(root, text="Log")
        log_box.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(log_box, height=7, state="disabled", wrap="word")
        scroll = ttk.Scrollbar(log_box, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

    # -- Browse / scan ----------------------------------------------------- #
    def _browse_dolphin(self) -> None:
        path = filedialog.askopenfilename(title="Select Dolphin.exe",
                                          filetypes=[("Dolphin", "Dolphin.exe"), ("Executables", "*.exe")])
        if path:
            self.vars["dolphin"].set(os.path.normpath(path))

    def _browse_games(self) -> None:
        path = filedialog.askdirectory(title="Select your games folder")
        if path:
            self.vars["games_dir"].set(os.path.normpath(path))
            self._scan_games()

    def _scan_games(self) -> None:
        folder = self.vars["games_dir"].get()
        self.games = []
        self.tree.delete(*self.tree.get_children())
        if not os.path.isdir(folder):
            return
        self.games = [
            os.path.join(folder, n) for n in sorted(os.listdir(folder))
            if os.path.splitext(n)[1].lower() in core.GAME_EXTENSIONS
        ]
        self.plays = {g: 0 for g in self.games}
        for g in self.games:
            self.tree.insert("", "end", iid=g, text=os.path.splitext(os.path.basename(g))[0], values=(0,))

    # -- Start / stop ------------------------------------------------------ #
    def _read_config(self) -> Optional[Dict]:
        v = {k: var.get() for k, var in self.vars.items()}
        try:
            cfg = {
                "dolphin": v["dolphin"], "games_dir": v["games_dir"],
                "interval": float(v["interval"]), "hours": float(v["hours"]),
                "boot_wait": float(v["boot_wait"]), "state_delay": float(v["state_delay"]),
                "load_hotkey": v["load_hotkey"], "save_hotkey": v["save_hotkey"],
                "allow_repeat": bool(v["allow_repeat"]),
            }
        except ValueError:
            messagebox.showerror("Invalid settings", "Interval, hours and delays must be numbers.")
            return None
        if min(cfg["interval"], cfg["hours"]) <= 0 or min(cfg["boot_wait"], cfg["state_delay"]) < 0:
            messagebox.showerror("Invalid settings", "Interval and hours must be greater than 0.")
            return None
        if not core.parse_hotkey(cfg["load_hotkey"]) or not core.parse_hotkey(cfg["save_hotkey"]):
            messagebox.showerror("Invalid settings", "Hotkeys cannot be empty.")
            return None
        return cfg

    def _save_config(self) -> None:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump({k: var.get() for k, var in self.vars.items()}, fh, indent=2)
        except OSError:
            pass

    def _start(self) -> None:
        cfg = self._read_config()
        if cfg is None:
            return
        if not os.path.isfile(cfg["dolphin"]):
            messagebox.showerror("Dolphin not found", "Select a valid Dolphin.exe.")
            return
        self._scan_games()
        if len(self.games) < 2:
            messagebox.showerror("Not enough games",
                                 "The games folder needs at least 2 game files "
                                 "(.iso, .gcm, .rvz, .gcz, .wbfs, .ciso).")
            return
        self._save_config()
        self._set_running(True)
        self._append_log(f"Starting with {len(self.games)} games.")
        self.session = Session(cfg, self.games, self.events)
        self.session.start()

    def _stop(self) -> None:
        if self.session:
            self.stop_btn.configure(state="disabled")
            self._append_log("Stopping...")
            self.session.stop()

    def _set_running(self, running: bool) -> None:
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
        for widget in self.setting_widgets:
            widget.configure(state="disabled" if running else "normal")

    # -- Events from the worker thread ------------------------------------- #
    def _poll_events(self) -> None:
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self._append_log(data)
                elif kind == "status":
                    self._update_status(data)
                elif kind == "played":
                    self.plays[data] = self.plays.get(data, 0) + 1
                    if self.tree.exists(data):
                        self.tree.set(data, "plays", self.plays[data])
                elif kind == "done":
                    self._set_running(False)
                    self.game_label.configure(text="Idle")
                    self.phase_label.configure(text="")
                    self.session_label.configure(text="")
                    self.bar.configure(value=0)
                    self.session = None
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _update_status(self, s: Dict) -> None:
        self.game_label.configure(text=s["game"])
        self.phase_label.configure(
            text=f"Round {s['round']}  -  {s['phase']}  ({s['phase_left']:.0f}s left)")
        total = s["phase_total"] or 1
        self.bar.configure(value=1 - s["phase_left"] / total)
        h, rem = divmod(int(s["session_left"]), 3600)
        m, sec = divmod(rem, 60)
        self.session_label.configure(text=f"Session time left: {h:d}:{m:02d}:{sec:02d}")

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # -- Shutdown ---------------------------------------------------------- #
    def _on_close(self) -> None:
        if self.session and self.session.is_alive():
            if not messagebox.askyesno("Quit", "A session is running. Save the current game and quit?"):
                return
            self.session.stop()
            self._wait_for_session()
        else:
            self._save_config()
            self.destroy()

    def _wait_for_session(self) -> None:
        if self.session and self.session.is_alive():
            self.after(200, self._wait_for_session)
        else:
            self._save_config()
            self.destroy()


if __name__ == "__main__":
    App().mainloop()
