#!/usr/bin/env python3
"""
Minimal Chrome DevTools Protocol client — pure stdlib, zero dependencies.
Talks to Chrome via --remote-debugging-port=9222.

Usage:
    python3 cdp_client.py <javascript_file.js>
"""

import json
import socket
import ssl
import struct
import sys
import os
import time
from base64 import b64encode
from http.client import HTTPConnection
from urllib.parse import urlparse


class CDPClient:
    """WebSocket-based CDP client using only stdlib."""

    OPCODE_TEXT = 0x1
    OPCODE_CLOSE = 0x8

    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self._msg_id = 0
        self._pending: dict[int, dict] = {}

    # ── public API ──────────────────────────────────────────────

    def connect(self, page_url: str | None = None):
        """Find a page and connect its WebSocket."""
        pages = self._http_get(f"http://{self.host}:{self.port}/json")
        target = None
        for p in pages:
            if p.get("type") == "page":
                target = p
                if page_url and page_url not in p.get("url", ""):
                    target = None
                    continue
                break
        if not target:
            raise RuntimeError(f"No page found (filter={page_url}). Pages: {[p.get('url','')[:60] for p in pages]}")

        ws_url = target["webSocketDebuggerUrl"]
        self._ws_connect(ws_url)
        print(f"[CDP] connected to {target['title'][:60]} | {target['url'][:80]}")

    def navigate(self, url: str, timeout_ms: int = 30000):
        """Navigate the page and wait for load."""
        # Enable Page domain to receive events
        self._call("Page.enable", {})
        result = self._call("Page.navigate", {"url": url})
        if "error" in result:
            print(f"[CDP] navigate error: {result['error']}")
            return
        # Wait for Page.loadEventFired
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            msg = self._recv(timeout_ms=2000)
            if msg and msg.get("method") == "Page.loadEventFired":
                break
            if msg and msg.get("method") == "Page.frameStoppedLoading":
                time.sleep(0.3)
                break
        time.sleep(0.5)  # let JS settle

    def eval(self, expression: str, await_promise: bool = True, timeout_ms: int = 120_000) -> dict:
        """Evaluate JavaScript in the page, return result as Python dict."""
        deadline = time.time() + timeout_ms / 1000
        # Auto-wrap async function declarations in IIFE so they actually execute
        stripped = expression.strip()
        if stripped.startswith("async ") and "=>" in stripped.split("{")[0] and not stripped.endswith("()"):
            expression = f"({stripped})()"

        params = {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
        }
        result = self._call("Runtime.evaluate", params, timeout_ms)
        err = result.get("result", {}).get("exceptionDetails")
        if err:
            raise RuntimeError(f"JS exception: {json.dumps(err, indent=2)[:500]}")
        return result.get("result", {}).get("result", {}).get("value")
        # Wait for pending promise result
        while time.time() < deadline:
            msg = self._recv()
            msg_id = msg.get("id")
            result = msg.get("result", {}).get("result", {}).get("value")
            if result is not None and isinstance(result, dict):
                return result
            if "exceptionDetails" in (msg.get("result", {}) or {}):
                raise RuntimeError(str(msg)[:500])
        raise TimeoutError("eval timed out")

    def ping(self, timeout_ms: int = 5000) -> bool:
        """Check if CDP connection is alive by sending a lightweight eval."""
        try:
            result = self.eval("1+1", await_promise=False, timeout_ms=timeout_ms)
            return result == 2
        except Exception:
            return False

    def is_connected(self) -> bool:
        """Check if underlying socket is alive."""
        return self.sock is not None

    def reconnect(self, page_url: str | None = None):
        """Tear down and rebuild the CDP WebSocket connection."""
        self.close()
        time.sleep(1)
        self.connect(page_url=page_url)

    def close(self):
        if self.sock:
            try:
                self._send_frame(self.OPCODE_CLOSE, b"")
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    # ── HTTP helper ─────────────────────────────────────────────

    def _http_get(self, url: str) -> list | dict:
        u = urlparse(url)
        conn = HTTPConnection(u.hostname, u.port, timeout=5)
        conn.request("GET", u.path + ("?" + u.query if u.query else ""))
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return json.loads(data)

    # ── WebSocket layer ─────────────────────────────────────────

    def _ws_connect(self, url: str):
        u = urlparse(url)
        host = u.hostname
        port = u.port or (443 if u.scheme == "wss" else 80)
        use_tls = u.scheme == "wss"
        path = u.path + ("?" + u.query if u.query else "")

        # TCP connect
        sock = socket.create_connection((host, port), timeout=10)
        # TLS wrapper only for wss://
        if use_tls:
            ctx = ssl.create_default_context()
            self.sock = ctx.wrap_socket(sock, server_hostname=host)
        else:
            self.sock = sock

        # WebSocket upgrade handshake
        key = b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        self.sock.sendall(req.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
        if b"101" not in response.split(b"\r\n")[0]:
            raise RuntimeError(f"WebSocket upgrade failed: {response[:200]}")

    def _send_frame(self, opcode: int, payload: bytes):
        length = len(payload)
        mask_bit = 0x80  # client MUST mask
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(mask_bit | length)
        elif length < 65536:
            header.append(mask_bit | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(mask_bit | 127)
            header.extend(struct.pack(">Q", length))
        mask_key = os.urandom(4)
        header.extend(mask_key)
        masked = bytearray(length)
        for i in range(length):
            masked[i] = payload[i] ^ mask_key[i % 4]
        self.sock.sendall(bytes(header) + bytes(masked))

    def _recv_frame(self) -> tuple[int, bytes]:
        buf = self._recv_exact(2)
        opcode = buf[0] & 0x0F
        masked = (buf[1] & 0x80) != 0
        length = buf[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        data = bytearray(self._recv_exact(length))
        if masked:
            for i in range(length):
                data[i] ^= mask[i % 4]
        return opcode, bytes(data)

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            try:
                chunk = self.sock.recv(n - len(data))
            except (socket.timeout, TimeoutError, BlockingIOError):
                continue
            if not chunk:
                raise ConnectionError("WebSocket closed")
            data += chunk
        return data

    # ── CDP protocol ────────────────────────────────────────────

    def _call(self, method: str, params: dict, timeout_ms: int = 30000) -> dict:
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method, "params": params}
        self._send_frame(self.OPCODE_TEXT, json.dumps(msg).encode())
        deadline = time.time() + timeout_ms / 1000
        buf = b""
        while time.time() < deadline:
            try:
                opcode, data = self._recv_frame()
            except (ConnectionError, TimeoutError, socket.timeout):
                continue
            if opcode == self.OPCODE_TEXT:
                buf += data
                try:
                    parsed = json.loads(buf)
                    if parsed.get("id") == self._msg_id:
                        return parsed
                    # Notification (has method, no id) or other response — discard
                    buf = b""
                except json.JSONDecodeError:
                    pass  # partial frame, keep accumulating
            elif opcode == self.OPCODE_CLOSE:
                raise ConnectionError("CDP: Chrome closed WebSocket")
        raise TimeoutError(f"CDP call {method} timed out after {timeout_ms}ms")

    def _recv(self, timeout_ms: int = 5000) -> dict | None:
        """Block and receive next message."""
        deadline = time.time() + timeout_ms / 1000
        buf = b""
        while time.time() < deadline:
            try:
                self.sock.settimeout(0.5)
                opcode, data = self._recv_frame()
                if opcode == self.OPCODE_TEXT:
                    buf += data
                    try:
                        return json.loads(buf)
                    except json.JSONDecodeError:
                        pass
                elif opcode == self.OPCODE_CLOSE:
                    return None
            except (socket.timeout, ssl.SSLWantReadError):
                continue
            except BlockingIOError:
                continue
        return None


# ── CLI ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 cdp_client.py <javascript_file.js>")
        print("       Reads JS from file, executes in browser, prints JSON result.")
        sys.exit(1)

    js_file = sys.argv[1]
    with open(js_file) as f:
        js_code = f.read()

    # Detect async: wrap in IIFE async if contains 'await'
    if "await " in js_code:
        js_code = f"(async () => {{\n{js_code}\n}})()"

    cdp = CDPClient()
    try:
        cdp.connect()
        result = cdp.eval(js_code, await_promise=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        cdp.close()
