# Plasma Guard

A modern, simple antivirus GUI for Linux, powered by [ClamAV](https://www.clamav.net/). Built with Qt6/PySide6.

<img width="512" height="512" alt="icon" src="https://github.com/user-attachments/assets/125faef0-4ea1-4873-b8ce-892e4a47506e" />


---

## Features

- **Dashboard** — live status: engine version, database age, quarantine count, last scan, USB drives
- **Quick scan** — one-click scan of Home, Downloads, Documents, or any mounted USB drive
- **File/folder picker** — scan any file or directory
- **Drag & drop** — drag a file onto the sidebar drop zone to scan instantly
- **Live scan view** — real-time progress, file counter, threat table, and full log stream
- **Database updates** — one-click `freshclam` with timeout and error handling
- **Quarantine manager** — list, restore (with warning), delete, or empty quarantine. Files are password-zipped
- **Scan history** — every scan is saved and browsable with full report details
- **Scheduled scans** — via systemd user timer (no root required). Daily, weekly, or monthly
- **System tray** — StatusNotifierItem with context menu and notifications
- **Settings panel** — scan flags, auto-quarantine, scheduler, tray behaviour, and diagnostics
- **Dark/light aware** — QSS stylesheet adapts to your Plasma theme

---

## Screens / Pages

| Page       | Hotkey | Description                              |
|------------|--------|------------------------------------------|
| Dashboard  | Ctrl+1 | Status cards, quick actions, recent scans |
| Scan       | Ctrl+2 | Start scans, live progress & threat list  |
| Quarantine | Ctrl+3 | Manage quarantined files                  |
| Logs       | Ctrl+4 | Browse scan history                      |
| Settings   | Ctrl+5 | Configure everything                     |

---

## Requirements

- **Linux** with any desktop environment (KDE Plasma, GNOME, Xfce, etc.)
- **Python 3.10+**
- **ClamAV** — `clamscan` and `freshclam`
- **PySide6** — Qt6 Python bindings
- **systemd** — for scheduled scans (optional)

## Install

```bash
git clone https://github.com/YOUR_USER/plasma-guard.git
cd plasma-guard
bash packaging/install.sh
```

The installer will install ClamAV if missing, install PySide6 and the Python package, register the `.desktop` file and icons, and set up a weekly scheduled scan by default.

Launch from the application menu (**Plasma Guard**) or:

```bash
plasma-guard
```

## Uninstall

```bash
bash packaging/uninstall.sh            # keep user data
bash packaging/uninstall.sh --purge    # wipe everything
```

---

## Project layout

```
plasma-guard/
├── plasma_guard/
│   ├── app.py              # QApplication + CLI entry
│   ├── main_window.py      # Sidebar + stacked pages
│   ├── tray.py             # System tray icon
│   ├── scanner.py          # clamscan wrapper
│   ├── updater.py          # freshclam wrapper
│   ├── quarantine.py       # Quarantine vault
│   ├── scheduler.py        # systemd timer integration
│   ├── config.py           # JSON settings
│   ├── reports.py          # Scan report persistence
│   ├── notifications.py    # Desktop notifications
│   ├── workers.py          # QThread workers
│   ├── paths.py            # XDG directory paths
│   ├── icons.py            # Icon helpers
│   ├── diagnose.py         # System diagnostics
│   ├── dropzone.py         # Drag-and-drop scanner
│   └── ui/
│       ├── style.py        # QSS stylesheet
│       ├── dashboard.py
│       ├── scan_view.py
│       ├── quarantine_view.py
│       ├── logs_view.py
│       └── settings_view.py
├── assets/                 # Icons (SVG + PNG)
├── systemd/                # systemd user units
├── packaging/              # Install/uninstall scripts
├── tests/                  # Test suite
├── pyproject.toml
├── requirements.txt
├── LICENSE
└── README.md
```

---

## Notes

- **User-level** — no root required to run
- **On-demand only** — real-time scanning is not included (easily added via `clamonacc`)
- The shield icon is included as SVG and PNG at all standard sizes

## License

MIT
