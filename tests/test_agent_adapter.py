import json
from pathlib import Path

import pytest

from proxmox_mcp.agent.adapter import AdapterActionPlan, ProxmoxAgentAdapter


class _DummyEndpoint:
    def __init__(self, payload):
        self._payload = payload

    def get(self):
        return self._payload


class _DummyQemuEndpoint(_DummyEndpoint):
    pass


class _DummyNodeEndpoint:
    def __init__(self, nodes):
        self._nodes = nodes

    def get(self):
        return self._nodes

    def __call__(self, node_name):
        return _DummyNodeResource(node_name)


class _DummyNodeResource:
    def __init__(self, node_name):
        self.node_name = node_name
        self.qemu = _DummyQemuEndpoint([{"node": node_name, "vmid": 100}])


class _DummyClient:
    def __init__(self):
        self.version = _DummyEndpoint({"version": "test"})
        self.nodes = _DummyNodeEndpoint([{"node": "pve"}])


def _write_config(tmp_path: Path) -> Path:
    config = {
        "proxmox": {"host": "pve.local", "port": 8006, "verify_ssl": False, "service": "PVE"},
        "auth": {"user": "api@pve", "token_name": "demo", "token_value": "abc123"},
        "logging": {"level": "INFO", "format": "%(message)s"},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(config))
    return cfg_path


def test_adapter_lazy_connection(tmp_path):
    cfg_path = _write_config(tmp_path)
    adapter = ProxmoxAgentAdapter(config_path=str(cfg_path), auto_connect=False, client_factory=lambda *_: _DummyClient())

    with pytest.raises(RuntimeError):
        _ = adapter.api

    client = adapter.connect()
    assert client is adapter.api


def test_adapter_builds_action_plan(tmp_path):
    cfg_path = _write_config(tmp_path)
    adapter = ProxmoxAgentAdapter(config_path=str(cfg_path), auto_connect=False, client_factory=lambda *_: _DummyClient())

    plan = adapter.plan_vm_creation(
        node="pve",
        vm_id=101,
        name="demo-vm",
        cpu=2,
        memory_mb=2048,
        disk_gb=32,
    )

    assert isinstance(plan, AdapterActionPlan)
    assert plan.parameters["vmid"] == 101
    assert plan.dry_run is True

    with pytest.raises(NotImplementedError):
        adapter.execute_plan(plan)
