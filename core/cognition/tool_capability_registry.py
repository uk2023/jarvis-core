"""TOOL & CAPABILITY LIFECYCLE MANAGEMENT.

UK requirement (section 8): Fix the tool lifecycle.

When JARVIS creates a tool:
  CREATE → VERIFY → REGISTER → RECORD CAPABILITY → 
  ASSOCIATE WITH PROJECT/PATH → MAKE DISCOVERABLE → FUTURE INVOCATION

This module tracks real state, not invented paths or hallucinated results.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import json


class ToolStatus(Enum):
    """Lifecycle status of a tool."""
    CREATED = "created"
    VERIFIED = "verified"
    REGISTERED = "registered"
    AVAILABLE = "available"
    FAILED = "failed"
    BROKEN = "broken"


@dataclass
class ToolInfo:
    """Information about a tool JARVIS has created or knows about."""
    name: str
    type_: str  # "script", "module", "executable", "library", etc.
    created_at: float
    created_by: str = "JARVIS"
    
    # Real path information (NEVER invented)
    path: Optional[str] = None
    working_directory: Optional[str] = None
    
    # Status tracking with evidence
    status: ToolStatus = ToolStatus.CREATED
    status_history: List[tuple[float, ToolStatus, str]] = field(default_factory=list)  # (time, status, reason)
    
    # Verification
    verified_at: Optional[float] = None
    verification_evidence: Optional[str] = None  # what test/check proved it works
    
    # Registration
    registered_at: Optional[float] = None
    registered_as: Optional[str] = None  # how it's invoked/named
    
    # Project association
    project_id: Optional[str] = None
    associated_projects: List[str] = field(default_factory=list)
    
    # Capability registration
    capability_tags: List[str] = field(default_factory=list)  # "pdf_reading", "image_processing", etc.
    can_be_discovered_as: List[str] = field(default_factory=list)  # how user can ask for it
    
    # Error/failure tracking
    errors: List[str] = field(default_factory=list)
    last_error: Optional[str] = None
    
    # Usage tracking
    last_used_at: Optional[float] = None
    usage_count: int = 0
    
    def update_status(self, new_status: ToolStatus, evidence: str) -> None:
        """Update status with evidence."""
        old_status = self.status
        self.status = new_status
        self.status_history.append((time.time(), new_status, evidence))
        
        # Update timestamp based on status
        if new_status == ToolStatus.VERIFIED:
            self.verified_at = time.time()
            self.verification_evidence = evidence
        elif new_status == ToolStatus.REGISTERED:
            self.registered_at = time.time()
    
    def record_error(self, error_msg: str) -> None:
        """Record that an error occurred."""
        self.errors.append(error_msg)
        self.last_error = error_msg
        self.status = ToolStatus.BROKEN
        self.status_history.append((time.time(), ToolStatus.BROKEN, f"Error: {error_msg}"))
    
    def mark_used(self) -> None:
        """Record that this tool was just used."""
        self.last_used_at = time.time()
        self.usage_count += 1
    
    def is_available(self) -> bool:
        """Can this tool be used right now?"""
        return (
            self.status in (ToolStatus.REGISTERED, ToolStatus.AVAILABLE)
            and self.path is not None
            and (self.path == "" or os.path.exists(self.path))
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging/storage."""
        return {
            "name": self.name,
            "type": self.type_,
            "path": self.path,
            "status": self.status.value,
            "verified": self.verified_at is not None,
            "registered": self.registered_at is not None,
            "available": self.is_available(),
            "project": self.project_id,
            "capability_tags": self.capability_tags,
            "errors": self.errors,
        }


class ToolCapabilityRegistry:
    """Manages the registry of tools and capabilities JARVIS has."""
    
    def __init__(self):
        self.tools: Dict[str, ToolInfo] = {}  # name -> ToolInfo
        self.capability_index: Dict[str, List[str]] = {}  # capability_tag -> [tool_names]
        self.discovery_index: Dict[str, List[str]] = {}  # how_to_ask -> [tool_names]
    
    def create_tool(
        self,
        name: str,
        type_: str,
        path: Optional[str] = None,
        working_directory: Optional[str] = None,
    ) -> ToolInfo:
        """
        Record a tool that JARVIS has created.
        NEVER accept invented/hallucinated paths -- verify they exist.
        """
        # Verify path exists if provided
        if path and path != "" and not os.path.exists(path):
            raise ValueError(f"Tool path does not exist: {path}")
        
        tool = ToolInfo(
            name=name,
            type_=type_,
            created_at=time.time(),
            path=path,
            working_directory=working_directory,
        )
        self.tools[name.lower()] = tool
        return tool
    
    def verify_tool(self, name: str, evidence: str) -> bool:
        """Mark a tool as verified with evidence of what test passed."""
        tool = self.tools.get(name.lower())
        if not tool:
            return False
        
        tool.update_status(ToolStatus.VERIFIED, evidence)
        return True
    
    def register_capability(
        self,
        tool_name: str,
        capability_tags: List[str],
        discovery_phrases: List[str],
    ) -> bool:
        """
        Register a tool as an available capability.
        E.g., after PDF reader is verified, register it as a "pdf_reading" capability.
        """
        tool = self.tools.get(tool_name.lower())
        if not tool or tool.status != ToolStatus.VERIFIED:
            return False
        
        tool.capability_tags = capability_tags
        tool.can_be_discovered_as = discovery_phrases
        tool.update_status(ToolStatus.REGISTERED, f"Registered with capabilities: {capability_tags}")
        
        # Update indices
        for tag in capability_tags:
            if tag not in self.capability_index:
                self.capability_index[tag] = []
            self.capability_index[tag].append(tool_name)
        
        for phrase in discovery_phrases:
            if phrase not in self.discovery_index:
                self.discovery_index[phrase] = []
            self.discovery_index[phrase].append(tool_name)
        
        tool.update_status(ToolStatus.AVAILABLE, "Now discoverable")
        return True
    
    def find_tool_by_discovery(self, user_ask: str) -> Optional[ToolInfo]:
        """Find a tool based on how the user asked for it.

        BUG FOUND BY tests/test_e2e_scenarios.py (2026-09-18): exact
        substring matching against registered discovery phrases failed
        on a real rephrasing -- "ye PDF padh ke batao isme kya likha
        hai" did not contain "pdf padhna"/"pdf padho" as a literal
        substring, so a tool that was correctly created, verified,
        registered AND discoverable by design still came back
        unfound. That is precisely the create-then-forget bug UK
        described (section 8) -- caused this time not by missing
        lifecycle tracking (which is fine) but by the discovery match
        itself being too literal.

        Exact-phrase match stays as the fast first pass (cheap, no
        false positives). When it misses, fall back to token-overlap
        matching on 4-character stems -- catches inflected variants
        of a registered phrase ("padhna"/"padho"/"padh ke" all share
        the "padh" stem) without needing an LLM call for every tool
        lookup. This is intentionally a narrower, purely mechanical
        fallback (matching morphological variants of words the tool
        was ALREADY explicitly registered under), not a judgment call
        like discuss-vs-act -- UK's objection to keyword hardcoding
        was about JUDGMENT decisions standing in for LLM understanding,
        not about string matching in general. A genuinely semantic
        version of this (LLM-based capability resolution) is listed as
        a Phase 2 enhancement.
        """
        lowered = user_ask.lower()

        # Fast path: exact phrase match.
        for phrase, tool_names in self.discovery_index.items():
            if phrase.lower() in lowered:
                for name in tool_names:
                    tool = self.tools.get(name.lower())
                    if tool and tool.is_available():
                        return tool

        # Fallback: token-stem overlap against each registered phrase.
        user_tokens = [t for t in re.findall(r"\w+", lowered) if len(t) >= 3]
        best_match: Optional[List[str]] = None
        best_score = 0
        for phrase, tool_names in self.discovery_index.items():
            phrase_tokens = [t for t in re.findall(r"\w+", phrase.lower()) if len(t) >= 3]
            overlap = sum(
                1 for pt in phrase_tokens
                if any(ut[:4] == pt[:4] for ut in user_tokens)
            )
            if overlap > best_score:
                best_score = overlap
                best_match = tool_names
        if best_match and best_score >= 1:
            for name in best_match:
                tool = self.tools.get(name.lower())
                if tool and tool.is_available():
                    return tool
        return None

    def find_tool_for_capability(self, capability_tag: str) -> Optional[ToolInfo]:
        """Find a tool that provides a certain capability."""
        tool_names = self.capability_index.get(capability_tag, [])
        if tool_names:
            for name in tool_names:
                tool = self.tools.get(name.lower())
                if tool and tool.is_available():
                    return tool
        return None
    
    
    def get_available_capabilities(self) -> List[str]:
        """List capabilities that are currently available."""
        available = set()
        for tool in self.tools.values():
            if tool.is_available():
                available.update(tool.capability_tags)
        return list(available)
    
    def tool_exists(self, name: str) -> bool:
        """Check if a tool is known to JARVIS."""
        return name.lower() in self.tools
    
    def tool_available(self, name: str) -> bool:
        """Check if a tool is available to use right now."""
        tool = self.tools.get(name.lower())
        return tool is not None and tool.is_available()
    
    def get_tool_info(self, name: str) -> Optional[ToolInfo]:
        """Get full information about a tool."""
        return self.tools.get(name.lower())
    
    def list_all_tools(self) -> List[Dict[str, Any]]:
        """List all known tools."""
        return [tool.to_dict() for tool in self.tools.values()]


# Global registry instance (one per JARVIS process)
_global_registry: Optional[ToolCapabilityRegistry] = None


def get_global_registry() -> ToolCapabilityRegistry:
    """Get or create the global tool registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolCapabilityRegistry()
    return _global_registry


def initialize_registry(registry: Optional[ToolCapabilityRegistry] = None) -> None:
    """Set the global registry."""
    global _global_registry
    _global_registry = registry or ToolCapabilityRegistry()


# Time import needed for timestamps
import time
