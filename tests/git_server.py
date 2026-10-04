"""A local smart-HTTP Git remote, so real CLI contracts need no GitHub access."""

from __future__ import annotations

import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def serve_git(root):
    class GitHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            url = urlsplit(self.path)
            env = dict(os.environ)
            env.update(
                {
                    "GIT_PROJECT_ROOT": str(root),
                    "GIT_HTTP_EXPORT_ALL": "1",
                    "REQUEST_METHOD": self.command,
                    "PATH_INFO": url.path,
                    "QUERY_STRING": url.query,
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "REMOTE_ADDR": "127.0.0.1",
                }
            )
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            result = subprocess.run(
                ["git", "http-backend"], input=body, env=env, capture_output=True, check=True
            )
            headers, content = result.stdout.split(b"\r\n\r\n", 1)
            parsed = [line.decode().split(":", 1) for line in headers.split(b"\r\n")]
            status = next((int(v.strip().split()[0]) for k, v in parsed if k == "Status"), 200)
            self.send_response(status)
            for key, value in parsed:
                if key != "Status":
                    self.send_header(key, value.strip())
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), GitHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
