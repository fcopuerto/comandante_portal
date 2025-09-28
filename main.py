"""Executable entry point for CobaltaX Server Monitor.

When packaged with PyInstaller, use this module as the entry script.
It ensures environment initialization (optional) and launches the GUI.
"""
from __future__ import annotations
import os
import sys

# Optional: Provide a switch to reset secure store (development / support use only)
if '--reset-store' in sys.argv:
    from pathlib import Path
    base = Path.home() / '.cobaltax'
    for name in ['config_store.sqlite', 'config_cache.json']:
        p = base / name
        if p.exists():
            try:
                p.unlink()
                print(f"Removed {p}")
            except Exception as e:
                print(f"Could not remove {p}: {e}")
    # Do not delete key file automatically for safety

# Defer heavy imports until after potential env handling
# Allow a portable .env in same folder as exe for first run convenience
for candidate in ('.env', '_.env'):
    if os.path.exists(candidate):
        try:
            with open(candidate, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    if k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass
        break

# Launch application (explicitly invoke main() since importing alone won't start GUI)
try:
    import server_monitor
    if hasattr(server_monitor, 'main'):
        server_monitor.main()
    else:  # fallback: attempt to instantiate GUI directly
        from server_monitor import ServerMonitorGUI  # type: ignore
        app = ServerMonitorGUI()
        app.run()
except Exception as e:  # If anything fails, show a simple dialog fallback
    import traceback
    import tkinter as tk
    import tkinter.messagebox as mb
    try:
        root = tk.Tk(); root.withdraw()
        mb.showerror("Startup Error",
                     f"Failed to start application:\n{e}\n\nTraceback:\n{traceback.format_exc()}")
    except Exception:
        print("Startup Error:", e)
        print(traceback.format_exc())
    sys.exit(1)
