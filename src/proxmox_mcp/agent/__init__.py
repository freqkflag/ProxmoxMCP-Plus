"""
Agent-facing helpers in the ProxmoxMCP package.

These utilities let out-of-process agents (Temporal workers, CLI helpers,
etc.) reuse the same configuration loader and Proxmox API setup that the MCP
server relies on without importing the entire server stack.
"""

from .adapter import AdapterActionPlan, ProxmoxAgentAdapter

__all__ = ["AdapterActionPlan", "ProxmoxAgentAdapter"]
