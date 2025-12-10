"""
Proxmox MCP Server - A Model Context Protocol server for interacting with Proxmox hypervisors.
"""

__version__ = "0.1.0"
__all__ = ["ProxmoxMCPServer"]


def __getattr__(name):
    """Lazily expose heavy modules to avoid import side effects on startup."""
    if name == "ProxmoxMCPServer":
        from .server import ProxmoxMCPServer

        return ProxmoxMCPServer
    raise AttributeError(f"module 'proxmox_mcp' has no attribute {name!r}")
