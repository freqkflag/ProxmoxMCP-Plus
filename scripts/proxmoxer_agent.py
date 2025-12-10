#!/usr/bin/env python3
"""
Lightweight CLI utility that exposes common Proxmoxer actions for automation agents.

The helper loads the existing MCP JSON config, establishes a Proxmoxer
connection, and offers a few read-only commands that are useful for health
checks or scripted workflows (version, nodes, vms).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

from proxmoxer import ProxmoxAPI


def _load_config(config_path: str) -> Dict[str, Any]:
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    token_value: Optional[str] = data["auth"].get("token_value")
    if not token_value:
        env_var = data["auth"].get("token_env_var")
        if not env_var:
            raise RuntimeError("No token_value or token_env_var configured")
        token_value = os.getenv(env_var)
        if not token_value:
            raise RuntimeError(f"Environment variable {env_var} is not set")

    data["auth"]["token_value"] = token_value
    return data


def _connect(cfg: Dict[str, Any]) -> ProxmoxAPI:
    proxmox_cfg = cfg["proxmox"]
    auth_cfg = cfg["auth"]
    return ProxmoxAPI(
        host=proxmox_cfg["host"],
        port=proxmox_cfg.get("port", 8006),
        user=auth_cfg["user"],
        token_name=auth_cfg["token_name"],
        token_value=auth_cfg["token_value"],
        verify_ssl=proxmox_cfg.get("verify_ssl", True),
        service=proxmox_cfg.get("service", "PVE"),
    )


def cmd_version(api: ProxmoxAPI) -> None:
    info = api.version.get()
    print(json.dumps(info, indent=2))


def cmd_nodes(api: ProxmoxAPI) -> None:
    nodes = api.nodes.get()
    print(json.dumps(nodes, indent=2))


def cmd_vms(api: ProxmoxAPI, node: Optional[str]) -> None:
    if node:
        qemu = api.nodes(node).qemu.get()
    else:
        qemu = []
        for entry in api.nodes.get():
            qemu.extend(api.nodes(entry["node"]).qemu.get())
    print(json.dumps(qemu, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Proxmoxer agent helper. Uses MCP config to talk to the Proxmox API."
    )
    parser.add_argument(
        "--config",
        default=os.getenv("PROXMOX_MCP_CONFIG", "proxmox-config/config.json"),
        help="Path to MCP JSON config (default: %(default)s)",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="Show Proxmox API version information")
    sub.add_parser("nodes", help="List nodes")

    vms = sub.add_parser("vms", help="List virtual machines")
    vms.add_argument("--node", help="Restrict VM listing to a specific node")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = _load_config(args.config)
        api = _connect(cfg)
    except Exception as exc:  # pragma: no cover - CLI surface
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.command == "version":
        cmd_version(api)
    elif args.command == "nodes":
        cmd_nodes(api)
    elif args.command == "vms":
        cmd_vms(api, args.node)
    else:  # pragma: no cover
        parser.error(f"Unsupported command: {args.command}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
