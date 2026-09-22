# -*- coding: utf-8 -*-
"""
The three glue hooks the rest of the Jarvis Organism project calls into
this web server with. Kept as their own tiny module so routes_ws.py can
grab the current executor without importing all of server.py.
"""
import sys

jarvis = None
brain = None
query_executor_func = None


def set_shared_organism(shared_jarvis, shared_brain=None):
    global jarvis, brain
    jarvis = shared_jarvis
    brain = shared_brain or (
        shared_jarvis.get_organ("brain") if shared_jarvis else None
    )


def bind_query_executor(executor_func):
    global query_executor_func
    query_executor_func = executor_func


def get_query_executor():
    """Return the live executor used by the running JARVIS process.

    Priority:
      1. Explicitly bound executor (normal CLI path).
      2. Imported ``cli`` module (jarvis-dev imports cli as a module, so
         ``__main__`` is the launcher and cannot be used as the fallback).
      3. __main__.process_query for backwards compatibility.
    """
    if callable(query_executor_func):
        return query_executor_func

    cli_module = sys.modules.get("cli")
    cli_executor = getattr(cli_module, "process_query", None) if cli_module else None
    if callable(cli_executor):
        return cli_executor

    return getattr(sys.modules.get("__main__"), "process_query", None)
