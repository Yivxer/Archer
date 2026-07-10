import http.server
import json
import os
import subprocess
import threading
from pathlib import Path


class _ReadyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return
        if self.path == "/ready":
            body = json.dumps({"ready": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


def test_journey_smoke_case_zero_runs_terminal_smoke(tmp_path):
    token_file = tmp_path / "desktop-api-token"
    token_file.write_text("test-token", encoding="utf-8")
    fake_root = tmp_path / "repo"
    fake_terminal = fake_root / "terminal"
    fake_terminal.mkdir(parents=True)
    fake_archer = fake_terminal / "archer.py"
    fake_archer.write_text(
        """#!/usr/bin/env python3
import sys
print("ARCHER_TERMINAL_SMOKE_OK")
raise SystemExit(0 if "--smoke" in sys.argv else 2)
""",
        encoding="utf-8",
    )
    fake_archer.chmod(0o755)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ReadyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {
            **os.environ,
            "ARCHER_API_BASE": f"http://127.0.0.1:{server.server_port}",
            "ARCHER_TOKEN_FILE": str(token_file),
            "ARCHER_JOURNEY_ROOT": str(fake_root),
        }
        result = subprocess.run(
            ["bash", "scripts/journey_smoke.sh", "--case", "0"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0
    assert "终端 smoke 通过" in result.stdout
