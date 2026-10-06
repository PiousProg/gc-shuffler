#!/usr/bin/env python3
"""GC Shuffler: randomly switch between GameCube games in Dolphin.

Every N seconds the current game is saved, Dolphin is closed, and a different
random game is launched. When you land on a game you've already played, your
progress is restored exactly where you left it (similar to BizHawk Shuffler,
but for Dolphin).

How it works
------------
Dolphin stores save states in files named after the game ID, so "slot 1" of
game A never collides with "slot 1" of game B. This script relies on that:

    1. Launch Dolphin on a random game (``--exec`` command-line flag).
    2. Wait for the game to boot.
    3. Press the "Load State Slot 1" hotkey. This restores your progress if a
       state exists, and silently does nothing the first time.
    4. Let you play for the configured interval.
    5. Press the "Save State Slot 1" hotkey.
    6. Close Dolphin and pick the next game.

Requirements: Windows, Python 3.8+, and the packages in requirements.txt.
See README.md for the one-time Dolphin setup.
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import time
from typing import List, Optional

if sys.platform != "win32":
    sys.exit("GC Shuffler currently supports Windows only.")

try:
    import psutil
    import pyautogui
    import pygetwindow as gw
except ImportError as exc:  # pragma: no cover
    sys.exit(f"Missing dependency ({exc.name}). Run: pip install -r requirements.txt")

# Disk image formats Dolphin can boot directly.
GAME_EXTENSIONS = {".iso", ".gcm", ".rvz", ".gcz", ".wbfs", ".ciso"}

# Usual install locations, checked when --dolphin is not given.
DOLPHIN_CANDIDATES = [
    os.path.expandvars(r"%ProgramFiles%\Dolphin-x64\Dolphin.exe"),
    os.path.expandvars(r"%ProgramFiles%\Dolphin\Dolphin.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Dolphin\Dolphin.exe"),
]

# Pause between simulated key presses and the actions around them.
FOCUS_DELAY = 0.3


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def find_dolphin(explicit: Optional[str]) -> str:
    """Return the path to Dolphin.exe or exit with a helpful message."""
    candidates = [explicit] if explicit else DOLPHIN_CANDIDATES
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    sys.exit("Dolphin.exe not found. Pass its location with --dolphin PATH.")


def find_games(games_dir: str) -> List[str]:
    """Return every bootable game file in ``games_dir`` (non-recursive)."""
    if not os.path.isdir(games_dir):
        sys.exit(f"Games folder not found: {games_dir}")
    games = [
        os.path.join(games_dir, name)
        for name in sorted(os.listdir(games_dir))
        if os.path.splitext(name)[1].lower() in GAME_EXTENSIONS
    ]
    if len(games) < 2:
        sys.exit(f"Need at least 2 games in {games_dir} (found {len(games)}).")
    return games


def pick_next_game(games: List[str], previous: Optional[str], allow_repeat: bool) -> str:
    """Pick a random game, avoiding an immediate repeat unless allowed."""
    pool = games if allow_repeat else [g for g in games if g != previous]
    return random.choice(pool or games)


def parse_hotkey(text: str) -> List[str]:
    """Turn 'shift+f1' into ['shift', 'f1'] for pyautogui."""
    return [part.strip().lower() for part in text.split("+") if part.strip()]


def focus_dolphin() -> None:
    """Bring a Dolphin window to the foreground (best effort).

    Not critical if Dolphin's "Background Input" option is enabled.
    """
    try:
        windows = [w for w in gw.getAllWindows() if "dolphin" in w.title.lower()]
        if windows:
            if windows[0].isMinimized:
                windows[0].restore()
            windows[0].activate()
            time.sleep(FOCUS_DELAY)
    except Exception:
        pass  # Focus problems should never crash a multi-hour session.


def send_hotkey(keys: List[str]) -> None:
    focus_dolphin()
    pyautogui.hotkey(*keys)


def launch_dolphin(dolphin: str, game: str) -> subprocess.Popen:
    """Start Dolphin in batch mode (no game list) on the given game."""
    return subprocess.Popen([dolphin, "-b", "-e", game])


def close_dolphin(process: Optional[subprocess.Popen]) -> None:
    """Terminate the Dolphin process we started, plus any child processes."""
    if process is None:
        return
    try:
        parent = psutil.Process(process.pid)
        procs = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        return
    for proc in procs:
        try:
            proc.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(procs, timeout=5)
    for proc in alive:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
def run_session(args: argparse.Namespace) -> None:
    dolphin = find_dolphin(args.dolphin)
    games = find_games(args.games_dir)
    load_keys = parse_hotkey(args.load_hotkey)
    save_keys = parse_hotkey(args.save_hotkey)

    print(f"Found {len(games)} games:")
    for game in games:
        print(f"  - {os.path.basename(game)}")

    session_end = time.time() + args.hours * 3600
    previous: Optional[str] = None
    process: Optional[subprocess.Popen] = None
    ready = False
    round_number = 0

    try:
        while time.time() < session_end:
            round_number += 1
            game = pick_next_game(games, previous, args.allow_repeat)
            print(f"\n[Round {round_number}] {os.path.basename(game)}")

            ready = False  # True once the saved state has been loaded.
            process = launch_dolphin(dolphin, game)
            time.sleep(args.boot_wait)

            send_hotkey(load_keys)  # No-op if this game has no saved state yet.
            ready = True
            time.sleep(args.state_delay)

            play_time = max(0.0, min(args.interval, session_end - time.time()))
            print(f"  Playing for {play_time:.0f}s...")
            time.sleep(play_time)

            send_hotkey(save_keys)
            time.sleep(args.state_delay)

            close_dolphin(process)
            process = None
            previous = game
            time.sleep(1)  # Let Dolphin fully release its files.

        print("\nSession finished.")
    except KeyboardInterrupt:
        print("\nInterrupted. Closing Dolphin...")
        if process is not None:
            try:
                # Saving before the old state was loaded would overwrite real
                # progress with a fresh boot, so only save once `ready`.
                if ready:
                    send_hotkey(save_keys)
                    time.sleep(args.state_delay)
            finally:
                close_dolphin(process)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Randomly switch between GameCube games in Dolphin, "
        "resuming each game where you left off."
    )
    parser.add_argument("--games-dir", default="games",
                        help="folder containing your game files (default: ./games)")
    parser.add_argument("--dolphin", help="path to Dolphin.exe (auto-detected if omitted)")
    parser.add_argument("--interval", type=float, default=60,
                        help="seconds of play per game (default: 60)")
    parser.add_argument("--hours", type=float, default=3,
                        help="total session length in hours (default: 3)")
    parser.add_argument("--boot-wait", type=float, default=12,
                        help="seconds to wait for a game to boot before loading "
                        "its state (default: 12)")
    parser.add_argument("--state-delay", type=float, default=2,
                        help="seconds to wait after each save/load hotkey (default: 2)")
    parser.add_argument("--load-hotkey", default="f1",
                        help="Dolphin 'Load State Slot 1' hotkey (default: f1)")
    parser.add_argument("--save-hotkey", default="shift+f1",
                        help="Dolphin 'Save State Slot 1' hotkey (default: shift+f1)")
    parser.add_argument("--allow-repeat", action="store_true",
                        help="allow the same game twice in a row")
    return parser


if __name__ == "__main__":
    run_session(build_parser().parse_args())
