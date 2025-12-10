#!/usr/bin/env python3
"""
CLI utility that exposes the Python 3 compatible Proxmoxia adapter.

Agents can use this script to run quick checks (version, nodes, VMs) using
the same MCP configuration and API token credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from proxmox_mcp.vendor.proxmoxia import Connector, Node, Proxmox  # noqa: E402


def load_config(config_path: str) -> Dict[str, Any]:
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


def connect(cfg: Dict[str, Any]) -> Proxmox:
    prox_cfg = cfg["proxmox"]
    auth_cfg = cfg["auth"]
    connector = Connector(
        prox_cfg["host"],
        prox_cfg.get("port", 8006),
        prox_cfg.get("verify_ssl", True),
    )
    connector.use_api_token(auth_cfg["user"], auth_cfg["token_name"], auth_cfg["token_value"])
    return Proxmox(connector)


def cmd_version(client: Proxmox) -> None:
    print(json.dumps(client.version(), indent=2))


def cmd_nodes(client: Proxmox) -> None:
    print(json.dumps(client.nodes(), indent=2))


def cmd_vms(client: Proxmox, node: Optional[str]) -> None:
    if node:
        vms = Node(client.conn, node).qemu()
    else:
        vms = []
        for entry in client.nodes():
            node_client = Node(client.conn, entry["node"])
            vms.extend(node_client.qemu())
    print(json.dumps(vms, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Proxmoxia agent helper. Uses MCP config and API tokens."
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
        cfg = load_config(args.config)
        client = connect(cfg)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.command == "version":
        cmd_version(client)
    elif args.command == "nodes":
        cmd_nodes(client)
    elif args.command == "vms":
        cmd_vms(client, args.node)
    else:
        parser.error(f"Unsupported command: {args.command}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
