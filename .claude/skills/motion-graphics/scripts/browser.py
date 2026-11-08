#!/usr/bin/env python3
"""Find a Chromium-family browser on this computer and drive it headless over the DevTools protocol (stdlib only).

    browser.py find          # prints the browser it would use, exit 1 if none
    browser.py check         # also starts it headless with a throwaway profile and loads a page

Any of Google Chrome, Chromium, Microsoft Edge, Brave or Vivaldi works: they share the DevTools protocol. Order:
settings `motion_graphics.browser` (a path, if set), then the usual install locations for macOS, Windows and Linux,
then PATH. Nothing is installed or downloaded.

The browser always runs headless with a fresh temporary profile (--user-data-dir in a temp folder, deleted after), so
the user's own browser, tabs, logins and extensions are never touched, even while it is open. Transport: a pipe on
macOS / Linux (--remote-debugging-pipe, fds 3/4), a local WebSocket on Windows (--remote-debugging-port=0, loopback
only). `--transport ws` forces the WebSocket path anywhere.
"""
from __future__ import annotations

import base64
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

MAC_APPS = ["Google Chrome", "Chromium", "Microsoft Edge", "Brave Browser", "Vivaldi", "Google Chrome Canary"]
WIN_REL = [r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe",
           r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Chromium\Application\chrome.exe",
           r"Vivaldi\Application\vivaldi.exe"]
PATH_NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
              "microsoft-edge-stable", "brave-browser", "vivaldi", "chrome", "msedge"]


def candidates():
    try:
        from vidkit import settings
        forced = settings.get("motion_graphics.browser")
        if forced:
            yield os.path.expanduser(str(forced))
    except Exception:
        pass
    sysname = platform.system()
    if sysname == "Darwin":
        for root in ("/Applications", os.path.expanduser("~/Applications")):
            for app in MAC_APPS:
                yield f"{root}/{app}.app/Contents/MacOS/{app}"
    elif sysname == "Windows":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                for rel in WIN_REL:
                    yield os.path.join(base, rel)
    for name in PATH_NAMES:
        p = shutil.which(name)
        if p:
            yield p


def find_browser():
    for c in candidates():
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def no_browser_exit():
    sys.exit("No Chromium-family browser found (Chrome, Chromium, Edge, Brave or Vivaldi). motion-graphics renders with "
             "one, headless, without touching your profile. Install one yourself (ask the user first), or point at it:\n"
             "  python3 tools/vidkit/settings.py set motion_graphics.browser \"/path/to/browser\"")


class _Pipe:
    def __init__(self, w, r):
        self.w, self.r, self.buf = w, r, b""

    def write(self, data):
        self.w.write(data + b"\0")

    def read(self):
        while b"\0" not in self.buf:
            chunk = self.r.read(1 << 20)
            if not chunk:
                return None
            self.buf += chunk
        raw, self.buf = self.buf.split(b"\0", 1)
        return raw


class _WebSocket:
    """A minimal RFC 6455 client: text frames, masking, fragmentation, ping/pong. Loopback only."""

    def __init__(self, host, port, path):
        self.s = socket.create_connection((host, port), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("browser closed the WebSocket handshake")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(head.split(b"\r\n", 1)[0].decode(errors="replace"))
        self.rest = head.split(b"\r\n\r\n", 1)[1]

    def _recv(self, n):
        while len(self.rest) < n:
            chunk = self.s.recv(max(1 << 16, n - len(self.rest)))
            if not chunk:
                raise ConnectionError("browser closed the WebSocket")
            self.rest += chunk
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def _frame(self, op, data):
        hdr = bytes([0x80 | op])
        n = len(data)
        hdr += bytes([0x80 | n]) if n < 126 else (bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536
                                                  else bytes([0x80 | 127]) + struct.pack(">Q", n))
        mask = os.urandom(4)
        body = bytes(b ^ mask[i & 3] for i, b in enumerate(data)) if n < 4096 else _xor(data, mask)
        self.s.sendall(hdr + mask + body)

    def write(self, data):
        self._frame(0x1, data)

    def read(self):
        msg = b""
        while True:
            b0, b1 = self._recv(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv(8))[0]
            mask = self._recv(4) if b1 & 0x80 else None
            data = self._recv(n)
            if mask:
                data = _xor(data, mask)
            op = b0 & 0x0F
            if op == 0x8:
                return None
            if op == 0x9:
                self._frame(0xA, data)
                continue
            if op in (0x0, 0x1, 0x2):
                msg += data
                if b0 & 0x80:
                    return msg


def _xor(data, mask):
    n = len(data)
    m = int.from_bytes((mask * (n // 4 + 1))[:n], "big")
    return (int.from_bytes(data, "big") ^ m).to_bytes(n, "big")


class Browser:
    """Headless Chromium with a throwaway profile. send() returns a command's result; page JS errors are collected."""

    def __init__(self, transport=None, path=None):
        self.exe = path or find_browser()
        if not self.exe:
            no_browser_exit()
        self.profile = tempfile.mkdtemp(prefix="motion-browser-")
        self.events, self.n = [], 0
        transport = transport or ("ws" if platform.system() == "Windows" else "pipe")
        flags = ["--headless", f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
                 "--disable-extensions", "--disable-sync", "--hide-scrollbars", "--mute-audio",
                 "--force-color-profile=srgb", "--allow-file-access-from-files", "--disable-background-timer-throttling",
                 "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows"]
        if transport == "pipe":
            import fcntl
            rc, wc = os.pipe()
            rv, wv = os.pipe()

            def child():        # the browser reads commands on fd 3 and writes replies on fd 4
                a = fcntl.fcntl(rc, fcntl.F_DUPFD, 10)
                b = fcntl.fcntl(wv, fcntl.F_DUPFD, 10)
                os.dup2(a, 3)
                os.dup2(b, 4)
            self.p = subprocess.Popen([self.exe, "--remote-debugging-pipe", *flags, "about:blank"], close_fds=False,
                                      preexec_fn=child, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            os.close(rc)
            os.close(wv)
            self.t = _Pipe(os.fdopen(wc, "wb", buffering=0), os.fdopen(rv, "rb", buffering=0))
        else:
            self.p = subprocess.Popen([self.exe, "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
                                       *flags, "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            port_file = Path(self.profile) / "DevToolsActivePort"
            for _ in range(300):
                if port_file.exists() and len(port_file.read_text().split()) >= 2:
                    break
                if self.p.poll() is not None:
                    sys.exit("the browser exited at start: " + self.p.stderr.read().decode(errors="replace")[-500:])
                time.sleep(0.05)
            else:
                self.close()
                sys.exit("the browser never opened its DevTools port")
            port, path = port_file.read_text().split()[:2]
            self.t = _WebSocket("127.0.0.1", int(port), path)
        tid = self.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.sid = self.send("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        self.send("Runtime.enable", page=True)

    def send(self, method, params=None, page=False):
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params or {}}
        if page:
            msg["sessionId"] = self.sid
        self.t.write(json.dumps(msg).encode())
        while True:
            raw = self.t.read()
            if raw is None:
                err = self.p.stderr.read().decode(errors="replace")[-600:] if self.p.poll() is not None else ""
                sys.exit("the browser closed the connection. " + err)
            j = json.loads(raw)
            if j.get("id") == self.n:
                if "error" in j:
                    sys.exit(f"{method}: {j['error'].get('message')}")
                return j.get("result", {})
            if j.get("method") == "Runtime.exceptionThrown":
                d = j["params"]["exceptionDetails"]
                self.events.append((d.get("exception") or {}).get("description") or d.get("text"))

    def js(self, expr, wait=False):
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": wait}, page=True)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            sys.exit(f"page error: {(d.get('exception') or {}).get('description') or d.get('text')}")
        return r.get("result", {}).get("value")

    def screenshot(self):
        return base64.b64decode(self.send("Page.captureScreenshot", {"format": "png", "optimizeForSpeed": True},
                                          page=True)["data"])

    def close(self):
        try:
            self.send("Browser.close")
            self.p.wait(5)
        except BaseException:
            try:
                self.p.kill()
            except Exception:
                pass
        shutil.rmtree(self.profile, ignore_errors=True)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["find", "check"])
    ap.add_argument("--transport", choices=["pipe", "ws"])
    a = ap.parse_args()
    exe = find_browser()
    if not exe:
        print(json.dumps({"browser": None}))
        return 1
    if a.cmd == "find":
        print(json.dumps({"browser": exe}))
        return 0
    b = Browser(a.transport, exe)
    try:
        b.send("Page.navigate", {"url": "data:text/html,<p id=x>ok</p>"}, page=True)
        for _ in range(100):
            if b.js("document.readyState") == "complete":
                break
            time.sleep(0.05)
        ver = b.send("Browser.getVersion")
        ok = b.js("document.getElementById('x') && document.getElementById('x').textContent")
        png = b.screenshot()
    finally:
        b.close()
    print(json.dumps({"browser": exe, "product": ver.get("product"), "page": ok, "screenshot_bytes": len(png),
                      "transport": a.transport or ("ws" if platform.system() == "Windows" else "pipe")}))
    return 0 if ok == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
