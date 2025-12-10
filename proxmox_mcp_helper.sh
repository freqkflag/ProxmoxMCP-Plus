#!/usr/bin/env bash
set -euo pipefail

# Default configuration values (override via env vars before running)
CTID=${CTID:-2900}
HOSTNAME=${HOSTNAME:-"proxmox-mcp"}
CORE_COUNT=${CORE_COUNT:-2}
MEMORY_MB=${MEMORY_MB:-4096}
SWAP_MB=${SWAP_MB:-512}
STORAGE=${STORAGE:-local-lvm}
BRIDGE=${BRIDGE:-vmbr0}
GATEWAY=${GATEWAY:-"192.168.12.1"}
IP_ADDRESS=${IP_ADDRESS:-"192.168.12.50/24"}
UNPRIVILEGED=${UNPRIVILEGED:-1}
TEMPLATE=${TEMPLATE:-"local:vztmpl/debian-12-standard_12.2-1_amd64.tar.zst"}

# MCP-specific values (mirrors proxmox-config/config.json)
MCP_REPO=${MCP_REPO:-"https://github.com/RekklesNA/ProxmoxMCP-Plus.git"}
PROXMOX_API_HOST=${PROXMOX_API_HOST:-"192.168.12.2"}
PROXMOX_API_PORT=${PROXMOX_API_PORT:-8006}
PROXMOX_API_USER=${PROXMOX_API_USER:-"root@pam"}
PROXMOX_API_TOKEN_NAME=${PROXMOX_API_TOKEN_NAME:-"PROXMOX_API_TOKEN"}
PROXMOX_API_TOKEN_VALUE=${PROXMOX_API_TOKEN_VALUE:-"fcf7d2c7-cc9f-4093-9846-5acf016183ab"}
VERIFY_SSL=${VERIFY_SSL:-false}

if [[ $(id -u) -ne 0 ]]; then
  echo "This script must run on the Proxmox host as root." >&2
  exit 1
fi

if pct status "$CTID" >/dev/null 2>&1; then
  echo "Container $CTID already exists. Aborting to avoid overwriting." >&2
  exit 1
fi

# Ensure template is present
if ! pveam list ${TEMPLATE%%:*} | grep -q "${TEMPLATE##*/}"; then
  echo "Downloading LXC template ${TEMPLATE##*/}..."
  pveam download ${TEMPLATE%%:*} "${TEMPLATE##*/}"
fi

echo "Creating container $CTID ($HOSTNAME)..."
pct create "$CTID" "$TEMPLATE" \
  -hostname "$HOSTNAME" \
  -cores "$CORE_COUNT" \
  -memory "$MEMORY_MB" \
  -swap "$SWAP_MB" \
  -storage "$STORAGE" \
  -net0 "name=eth0,bridge=$BRIDGE,ip=$IP_ADDRESS,gw=$GATEWAY" \
  -unprivileged "$UNPRIVILEGED" \
  -password "$(openssl rand -base64 18)"

echo "Starting container..."
pct start "$CTID"
sleep 5

echo "Bootstrapping OS dependencies..."
pct exec "$CTID" -- bash -eu <<'INNER'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y git python3 python3-venv python3-pip curl
useradd -m -s /bin/bash mcp || true
mkdir -p /opt
chown mcp:mcp /opt
INNER

echo "Deploying ProxmoxMCP-Plus inside container..."
pct exec "$CTID" -- bash -eu <<INNER
su - mcp -c '
set -euo pipefail
if [ ! -d /home/mcp/ProxmoxMCP-Plus ]; then
  git clone "${MCP_REPO}" /home/mcp/ProxmoxMCP-Plus
fi
cd /home/mcp/ProxmoxMCP-Plus
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
mkdir -p proxmox-config
cat <<\"CONFIG\" > proxmox-config/config.json
{
    "proxmox": {
        "host": "${PROXMOX_API_HOST}",
        "port": ${PROXMOX_API_PORT},
        "verify_ssl": ${VERIFY_SSL},
        "service": "PVE"
    },
    "auth": {
        "user": "${PROXMOX_API_USER}",
        "token_name": "${PROXMOX_API_TOKEN_NAME}",
        "token_value": "${PROXMOX_API_TOKEN_VALUE}"
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "file": "proxmox_mcp.log"
    }
}
CONFIG
'
INNER

echo "Creating systemd service..."
pct exec "$CTID" -- bash -eu <<'INNER'
cat <<'SERVICE' > /etc/systemd/system/proxmox-mcp.service
[Unit]
Description=Proxmox MCP Plus Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=mcp
WorkingDirectory=/home/mcp/ProxmoxMCP-Plus
Environment=PROXMOX_MCP_CONFIG=/home/mcp/ProxmoxMCP-Plus/proxmox-config/config.json
ExecStart=/home/mcp/ProxmoxMCP-Plus/.venv/bin/python -m proxmox_mcp.server
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
systemctl enable --now proxmox-mcp.service
INNER

echo "Container $CTID provisioned. Use 'pct console $CTID' or 'pct exec $CTID -- systemctl status proxmox-mcp' to verify."
