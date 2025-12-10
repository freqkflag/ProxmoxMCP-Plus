"""
Lightweight Python 3 compatible port of baseblack/Proxmoxia.

The original project targets Python 2 and cookie-based authentication.
This module keeps the same dynamic attribute interface while:
- Using ``requests`` for HTTP transport
- Supporting API tokens or ticket-based auth
- Remaining fully compatible with MCP automation agents
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests

LOG = logging.getLogger("proxmoxia")

class ProxmoxError(Exception):
    """Base error for Proxmoxia interactions."""


class ProxmoxAuthError(ProxmoxError):
    """Raised when authentication fails."""


class ProxmoxConnectionError(ProxmoxError):
    """Raised when connectivity to the API fails."""


class ProxmoxTypeError(TypeError):
    """Raised when invalid parameters are provided to a call."""


@dataclass
class ProxmoxAuthToken:
    """Holds either cookie-auth or API-token credentials."""

    ticket: Optional[str] = None
    csrf: Optional[str] = None
    token_header: Optional[str] = None

    def apply(self, headers: Dict[str, str]) -> None:
        """Apply authentication headers to a request."""
        if self.token_header:
            headers["Authorization"] = self.token_header
        if self.ticket:
            headers["Cookie"] = f"PVEAuthCookie={self.ticket}"
        if self.csrf:
            headers["CSRFPreventionToken"] = self.csrf


class ConnectorAPI:
    """Base transport layer for all dynamic requests."""

    def __init__(self, hostname: str, port: int = 8006, verify_ssl: bool = True):
        self.host = hostname
        self.port = port
        self.verify_ssl = verify_ssl
        self.baseurl = f"https://{self.host}:{self.port}/api2/json"
        self.session = requests.Session()
        self._auth: Optional[ProxmoxAuthToken] = None
        LOG.debug("API endpoint base url: %s", self.baseurl)

    def _request(self, method: str, filter_path: str, params: Optional[Dict[str, Any]]) -> Any:
        url = f"{self.baseurl}/{filter_path}"
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self._auth:
            self._auth.apply(headers)

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params if method == "GET" else None,
                data=params if method != "GET" else None,
                headers=headers,
                verify=self.verify_ssl,
                timeout=30,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (401, 403):
                raise ProxmoxAuthError(str(exc)) from exc
            raise ProxmoxConnectionError(str(exc)) from exc
        except requests.RequestException as exc:
            raise ProxmoxConnectionError(str(exc)) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProxmoxError(f"Malformed JSON response: {exc}") from exc

        return payload.get("data")

    def get(self, filter_path: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        LOG.debug("GET %s (args=%s)", filter_path, arguments)
        return self._request("GET", filter_path, arguments)

    def post(self, filter_path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        LOG.debug("POST %s (params=%s)", filter_path, params)
        return self._request("POST", filter_path, params or {})

    def put(self, filter_path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        LOG.debug("PUT %s (params=%s)", filter_path, params)
        return self._request("PUT", filter_path, params or {})

    def delete(self, filter_path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        LOG.debug("DELETE %s (params=%s)", filter_path, params)
        return self._request("DELETE", filter_path, params or {})


class Connector(ConnectorAPI):
    """Connector that can authenticate with passwords or API tokens."""

    def get_auth_token(self, username: str, password: str) -> ProxmoxAuthToken:
        url = f"{self.baseurl}/access/ticket"
        try:
            response = self.session.post(
                url,
                data={"username": username, "password": password},
                verify=self.verify_ssl,
                timeout=30,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ProxmoxAuthError(str(exc)) from exc
        except requests.RequestException as exc:
            raise ProxmoxConnectionError(str(exc)) from exc

        data = response.json().get("data")
        if not data:
            raise ProxmoxAuthError("Failed to obtain access token")

        token = ProxmoxAuthToken(ticket=data["ticket"], csrf=data["CSRFPreventionToken"])
        self._auth = token
        return token

    def use_api_token(self, username: str, token_name: str, token_value: str) -> ProxmoxAuthToken:
        if "@" not in username:
            raise ProxmoxAuthError("username must include realm (e.g. 'user@pve')")
        header = f"PVEAPIToken={username}!{token_name}={token_value}"
        token = ProxmoxAuthToken(token_header=header)
        self._auth = token
        return token


class Proxmox(ConnectorAPI):
    """Dynamic entry point mirroring the original Proxmoxia interface."""

    def __init__(self, conn: Connector):
        super().__init__(conn.host, conn.port, conn.verify_ssl)
        self.session = conn.session
        self._auth = conn._auth
        self.conn = conn

    def __getattr__(self, key: str) -> "AttrMethod":
        return AttrMethod(self, key)


class AttrMethod:
    """Generates nested API calls via attribute access."""

    def __init__(self, parent: ConnectorAPI, method_name: str):
        self.parent = parent
        self.method_name = method_name

    def __getattr__(self, key: str) -> "AttrMethod":
        encoded = quote(str(key))
        if encoded == "post":
            return AttrPostMethod(self.parent, self.method_name)
        if encoded == "put":
            return AttrPutMethod(self.parent, self.method_name)
        if encoded == "delete":
            return AttrDeleteMethod(self.parent, self.method_name)
        if encoded == "get":
            return AttrGetMethod(self.parent, self.method_name)
        return AttrMethod(self.parent, "/".join((self.method_name, encoded)))

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if args:
            segments = [self.method_name]
            segments.extend(quote(str(arg)) for arg in args)
            return AttrMethod(self.parent, "/".join(segments))
        return self.parent.get(self.method_name, kwargs or None)


class AttrGetMethod(AttrMethod):
    def __call__(self, **kwargs: Any) -> Any:
        return self.parent.get(self.method_name, kwargs or None)


class AttrPostMethod(AttrMethod):
    def __call__(self, **kwargs: Any) -> Any:
        return self.parent.post(self.method_name, kwargs or None)


class AttrPutMethod(AttrMethod):
    def __call__(self, **kwargs: Any) -> Any:
        return self.parent.put(self.method_name, kwargs or None)


class AttrDeleteMethod(AttrMethod):
    def __call__(self, **kwargs: Any) -> Any:
        return self.parent.delete(self.method_name, kwargs or None)


class Node(Proxmox):
    """Convenience helper mirroring upstream Node wrapper."""

    def __init__(self, conn: Connector, node: str):
        super().__init__(conn)
        self.node = node
        self.baseurl = f"{self.baseurl}/nodes/{self.node}"

