"""
Agent adapter for lightweight Proxmox operations.

This module exposes a thin wrapper that automation agents (Temporal workers,
CLI helpers, etc.) can import to share the same configuration loader and API
bootstrap code that the MCP server uses. It focuses on:

- Loading `proxmox-config/config.json` (or env override) with validation.
- Establishing a Proxmox API client using the hardened ProxmoxManager.
- Providing read-only helpers that agents can call for quick checks.
- Offering an action-plan skeleton so higher-level workflows can keep intent
  + runtime parameters together before executing destructive operations.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..config.loader import load_config
from ..config.models import AuthConfig, Config, ProxmoxConfig
from ..core.proxmox import ProxmoxManager

ClientFactory = Callable[[ProxmoxConfig, AuthConfig], Any]


@dataclass
class AdapterActionPlan:
    """Structured intent for a future Proxmox action.

    Agents can hang on to a plan object while the workflow awaits approvals
    or retries. By default plans are dry-run only; execution pipelines can
    flip ``dry_run`` once the workflow reaches a confirmed/destructive state.
    """

    action: str
    parameters: Dict[str, Any]
    dry_run: bool = True
    notes: Optional[str] = None
    evidence: List[str] = field(default_factory=list)


class ProxmoxAgentAdapter:
    """Shareable adapter that keeps agent workers aligned with MCP settings."""

    DEFAULT_CONFIG_PATH = "proxmox-config/config.json"
    CONFIG_ENV_VAR = "PROXMOX_MCP_CONFIG"

    def __init__(
        self,
        config_path: Optional[str] = None,
        *,
        client_factory: Optional[ClientFactory] = None,
        auto_connect: bool = True,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger("proxmox-mcp.agent.adapter")
        cfg_path = config_path or os.getenv(self.CONFIG_ENV_VAR) or self.DEFAULT_CONFIG_PATH
        self.logger.debug("Loading MCP config from %s", cfg_path)
        self.config: Config = load_config(cfg_path)
        self._client_factory = client_factory or self._default_client_factory
        self._api: Any = None

        if auto_connect:
            self.connect()

    def _default_client_factory(self, prox_cfg: ProxmoxConfig, auth_cfg: AuthConfig) -> Any:
        """Default client factory that reuses the hardened ProxmoxManager."""
        return ProxmoxManager(prox_cfg, auth_cfg).get_api()

    def connect(self, force: bool = False) -> Any:
        """Establish (or refresh) the underlying Proxmox API client."""
        if self._api is not None and not force:
            return self._api

        self.logger.info("Connecting adapter to Proxmox host %s", self.config.proxmox.host)
        self._api = self._client_factory(self.config.proxmox, self.config.auth)
        return self._api

    @property
    def api(self) -> Any:
        """Return the connected Proxmox API client."""
        if self._api is None:
            raise RuntimeError("Adapter is not connected. Call connect() first.")
        return self._api

    # --- Read-only helpers -------------------------------------------------
    def health_check(self) -> Dict[str, Any]:
        """Return API version info as a lightweight health signal."""
        self.logger.debug("Running adapter health check")
        return self.connect().version.get()

    def list_nodes(self) -> List[Dict[str, Any]]:
        """Return cluster nodes."""
        self.logger.debug("Listing Proxmox nodes")
        return self.connect().nodes.get()

    def list_vms(self, node: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return QEMU VMs for a node or the entire cluster."""
        client = self.connect()
        if node:
            self.logger.debug("Listing VMs on node %s", node)
            return client.nodes(node).qemu.get()

        self.logger.debug("Listing VMs across cluster")
        vms: List[Dict[str, Any]] = []
        for entry in client.nodes.get():
            vms.extend(client.nodes(entry["node"]).qemu.get())
        return vms

    # --- Planning hooks ----------------------------------------------------
    def plan_vm_creation(
        self,
        *,
        node: str,
        vm_id: int,
        name: str,
        cpu: int,
        memory_mb: int,
        disk_gb: int,
        dry_run: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AdapterActionPlan:
        """Create a skeleton action plan for provisioning a VM."""
        plan = AdapterActionPlan(
            action="create_vm",
            parameters={
                "node": node,
                "vmid": vm_id,
                "name": name,
                "cpu": cpu,
                "memory_mb": memory_mb,
                "disk_gb": disk_gb,
                **(metadata or {}),
            },
            dry_run=dry_run,
            notes="Plan generated by ProxmoxAgentAdapter",
        )
        self.logger.debug("Prepared VM creation plan: %s", plan)
        return plan

    def execute_plan(self, plan: AdapterActionPlan) -> Dict[str, Any]:
        """Placeholder executor for future destructive actions.

        The execute path purposely raises for now so workflows never trigger
        destructive behaviour accidentally. Future iterations will pass the
        plan through policy/approval gates before calling the relevant
        Proxmox API endpoint.
        """
        raise NotImplementedError(
            f"Execution for action '{plan.action}' is not implemented yet. "
            "Use plan objects for approvals/logging only."
        )
