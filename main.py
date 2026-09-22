# -*- coding: utf-8 -*-
"""
Thin entrypoint kept at the project root so nothing outside this folder
has to change. Anything that used to do:

    import dashboard
    dashboard.set_shared_organism(jarvis)
    dashboard.attach_console(console)
    dashboard.bind_query_executor(process_query)
    dashboard.start_server_in_thread()

can now do the exact same thing against `main` instead -- every name is
re-exported below from its new home in backend/.
"""
from backend.server import app, start_server_in_thread
from backend.integration import set_shared_organism, bind_query_executor, get_query_executor
from backend.ws_manager import attach_console
from backend import config

__all__ = [
    "app",
    "start_server_in_thread",
    "set_shared_organism",
    "bind_query_executor",
    "get_query_executor",
    "attach_console",
    "config",
]

if __name__ == "__main__":
    # Running `python main.py` directly starts the server in the foreground
    # (useful for local testing without the rest of the Organism project).
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
