# GC Shuffler

Randomly switch between GameCube games in the [Dolphin emulator](https://dolphin-emu.org/) every N seconds, for hours. When you land on a game you've already played, it resumes exactly where you left off — like [BizHawk Shuffler](https://github.com/authorblues/bizhawk-shuffler-2), but for GameCube.

## How it works

Dolphin names its save-state files after the game ID, so slot 1 of one game never overwrites slot 1 of another. GC Shuffler uses that:

1. Launch Dolphin on a random game (`Dolphin.exe -b -e <game>`).
2. Wait for it to boot, then press **Load State Slot 1** (restores progress, does nothing on a first visit).
3. Let you play for the interval (60 s by default).
4. Press **Save State Slot 1**, close Dolphin, pick another game (never the same one twice in a row, unless you allow it).

## Requirements

- Windows
- Python 3.8+
- [Dolphin](https://dolphin-emu.org/download/) with your own legally obtained game dumps

## Setup

```powershell
git clone https://github.com/PiousProg/gc-shuffler.git
cd gc-shuffler
pip install -r requirements.txt
```

One-time Dolphin configuration:

1. Open Dolphin, go to **Options → Hotkey Settings**.
2. Enable **Background Input** so key presses are accepted even if the window briefly loses focus.
3. Check that **Load State Slot 1** is `F1` and **Save State Slot 1** is `Shift+F1` (the defaults).

## Usage

Put your game files (`.iso`, `.gcm`, `.rvz`, `.gcz`, `.wbfs`, `.ciso`) in one folder.

### Graphical interface

```powershell
python gc_shuffler_gui.py
```

Choose `Dolphin.exe` and your games folder, adjust the settings, and press **Start**. The window shows the current game, a countdown, how many times each game has come up, and a log. **Stop** saves the current game and closes Dolphin. Settings are remembered in `gc_shuffler_gui.json`. The GUI needs `gc_shuffler.py` in the same folder and uses Tkinter, which ships with the standard Python installer.

### Standalone .exe (no Python needed)

Download `GCShuffler.exe` from the [Releases](../../releases) page and run it. It is the same graphical interface, with settings saved next to the `.exe`. Windows SmartScreen may warn about an unsigned app; choose "More info" then "Run anyway".

To build it yourself, run `build_exe.bat` (output: `dist\GCShuffler.exe`). Pushing a tag like `v1.0.0` also builds it on GitHub Actions and attaches it to the release automatically.

### Command line

```powershell
python gc_shuffler.py --games-dir "C:\path\to\games"
```

Stop at any time with `Ctrl+C`; the current game is saved first.

#### Options

| Option | Default | Description |
| --- | --- | --- |
| `--games-dir` | `games` | Folder containing your game files |
| `--dolphin` | auto-detect | Path to `Dolphin.exe` |
| `--interval` | `60` | Seconds of play per game |
| `--hours` | `3` | Total session length |
| `--boot-wait` | `12` | Seconds to wait for a game to boot before loading its state |
| `--state-delay` | `2` | Seconds to wait after each save/load hotkey |
| `--load-hotkey` | `f1` | Dolphin "Load State Slot 1" hotkey |
| `--save-hotkey` | `shift+f1` | Dolphin "Save State Slot 1" hotkey |
| `--allow-repeat` | off | Allow the same game twice in a row |

Example: 90-second rounds for 4 hours with a custom Dolphin location:

```powershell
python gc_shuffler.py --games-dir D:\GC --dolphin "D:\Dolphin\Dolphin.exe" --interval 90 --hours 4
```

## Limitations

- Each switch closes and relaunches Dolphin, so expect roughly 12–15 seconds of loading per round rather than an instant swap. Slow-booting games may need a higher `--boot-wait`.
- Hotkeys are simulated, so avoid touching the keyboard right as a switch happens.
- Save states are Dolphin's regular slot 1 states: they will overwrite any manual slot 1 save you have for those games. Back them up first (`Documents\Dolphin Emulator\StateSaves`) if that matters to you.
- Windows only for now.

## Legal

This project does not include or distribute any game files or Nintendo software. You are responsible for using game dumps you legally own. Not affiliated with or endorsed by Nintendo or the Dolphin project.

## License

[MIT](LICENSE)
