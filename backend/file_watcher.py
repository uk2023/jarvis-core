# -*- coding: utf-8 -*-
"""Universal dynamic logic hot-reload watcher."""
import importlib
import os
import sys
import threading
import time
import traceback

from . import config
from .ws_manager import debug_log, broadcast_to_clients


def start_universal_file_watcher():
    file_mtimes = {}
    try:
        for root, dirs, files in os.walk(config.BASE_DIR):
            for file in files:
                filepath = os.path.join(root, file)
                try:
                    file_mtimes[filepath] = os.path.getmtime(filepath)
                except Exception:
                    pass
    except Exception:
        pass

    def _watch_loop():
        while True:
            time.sleep(1.0)
            try:
                for root, dirs, files in os.walk(config.BASE_DIR):
                    if "database" in dirs:
                        dirs.remove("database")

                    for file in files:
                        if any(
                            x in root
                            for x in [
                                "__pycache__",
                                ".git",
                                "database",
                                ".db",
                                ".log",
                                ".tmp",
                                ".json",
                            ]
                        ):
                            continue

                        filepath = os.path.join(root, file)
                        if file.endswith((".db", ".db-wal", ".db-shm", ".log", ".tmp", ".json")):
                            continue

                        try:
                            current_mtime = os.path.getmtime(filepath)
                            if filepath in file_mtimes:
                                if file_mtimes[filepath] != current_mtime:
                                    file_mtimes[filepath] = current_mtime
                                    rel_path = os.path.relpath(filepath, config.BASE_DIR)

                                    if file.endswith(".py"):
                                        clean_rel_path = rel_path.replace("\\", "/")
                                        if clean_rel_path.endswith(".py"):
                                            clean_rel_path = clean_rel_path[:-3]
                                        if clean_rel_path.endswith("/__init__"):
                                            clean_rel_path = clean_rel_path[:-9]

                                        # Maps 'backend/file_watcher.py' -> 'backend.file_watcher'
                                        module_name = clean_rel_path.replace("/", ".")

                                        debug_log(
                                            f"⚡ HOT-RELOADING LOGIC: -> {rel_path}",
                                            "bold magenta",
                                        )
                                        try:
                                            if module_name in sys.modules:
                                                importlib.reload(sys.modules[module_name])
                                                debug_log(
                                                    f"✔ Successfully reloaded Python module: {module_name}",
                                                    "green",
                                                )
                                            else:
                                                importlib.import_module(module_name)
                                                debug_log(
                                                    f"✔ Successfully imported new module: {module_name}",
                                                    "green",
                                                )
                                        except Exception as reload_err:
                                            err_str = traceback.format_exc()
                                            debug_log(
                                                f"❌ Hot-reload error in {module_name}:\n{err_str}",
                                                "bold red",
                                            )
                                            broadcast_to_clients({
                                                "type": "system_error",
                                                "source": f"Hot-Reload Watcher ({rel_path})",
                                                "error": str(reload_err),
                                                "traceback": err_str,
                                            })

                                    broadcast_to_clients({
                                        "type": "file_sync",
                                        "file": rel_path,
                                        "message": f"Live updated: {rel_path}",
                                    })
                            else:
                                file_mtimes[filepath] = current_mtime
                        except Exception:
                            pass
            except Exception:
                pass

    t = threading.Thread(target=_watch_loop, daemon=True)
    t.start()
    debug_log(
        "Universal Dynamic Logic Hot-Reload Watcher Active (Databases Excluded)",
        "bold green",
    )
