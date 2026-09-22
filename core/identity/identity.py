from __future__ import annotations
from typing import Dict, Any


class Identity:
    """
    Core Identity definition for JARVIS.
    Defines who the organism is, its purpose, and its genesis.
    """

    NAME = "JARVIS"
    VERSION = "0.3.0"
    DESIGNATION = "Modular Cognitive Organism"
    CREATOR = "UK"
    PURPOSE = (
        "To evolve autonomously, learn from experiences, "
        "and assist intelligently while maintaining internal consistency."
    )

    def __init__(self, metadata: dict = None):
        self.metadata = metadata or {}

    def get_profile(self) -> Dict[str, Any]:
        return {
            "name": self.NAME,
            "version": self.VERSION,
            "designation": self.DESIGNATION,
            "purpose": self.PURPOSE,
            "metadata": self.metadata,
        }
