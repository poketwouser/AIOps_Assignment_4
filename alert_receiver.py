"""Tiny webhook that Alertmanager posts to. Logs each alert as one line.

Run: python alert_receiver.py     (listens on 127.0.0.1:5001)
"""
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LOG = Path(__file__).parent / "results" / "logs" / "alerts.log"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG.open("a") as f:
            for a in body.get("alerts", []):
                line = (f"{now}  {a['status'].upper():8} {a['labels'].get('alertname')}"
                        f"  severity={a['labels'].get('severity')}"
                        f"  {a['annotations'].get('summary', '')}")
                print(line, flush=True)
                f.write(line + "\n")
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):   # keep the console to the alert lines only
        pass


if __name__ == "__main__":
    LOG.parent.mkdir(parents=True, exist_ok=True)
    print("alert receiver on http://127.0.0.1:5001/alert", flush=True)
    HTTPServer(("127.0.0.1", 5001), Handler).serve_forever()
