#!/usr/bin/env python3
"""
Hermes Agent Monitor — macOS Menu Bar App
Gateway / API Server / MCP / Cron status monitoring.
Click to open dashboard, restart gateway, view logs.

Usage:
  python3 hermes-monitor-mac.py
"""

import json
import os
import subprocess
import urllib.request
import webbrowser
from pathlib import Path

import rumps

HERMES_HOME = Path.home() / ".hermes"
API_PORT = 8642
API_KEY = ""
POLL_INTERVAL = 30
DASHBOARD_URL = f"http://127.0.0.1:{API_PORT}/dashboard"

# Read API key from .env
def load_api_key():
    global API_KEY, API_PORT
    env_file = HERMES_HOME / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("API_SERVER_KEY="):
                API_KEY = line.split("=", 1)[1].strip()
            if line.startswith("API_SERVER_PORT="):
                try:
                    API_PORT = int(line.split("=", 1)[1].strip())
                except ValueError:
                    pass

def api_get(path, timeout=5):
    """Call Hermes dashboard API."""
    url = f"http://127.0.0.1:{API_PORT}{path}"
    headers = {"User-Agent": "HermesMonitor/1.0"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except Exception:
        return None


def check_gateway():
    """Check gateway health."""
    data = api_get("/health")
    if data and data.get("status") == "ok":
        return True, "running"
    return False, "down"


def check_api_server():
    """Check API server models endpoint."""
    data = api_get("/v1/models")
    if data and "data" in data:
        return True, f"{len(data['data'])} model(s)"
    return False, "down"


def get_overview():
    """Get dashboard overview."""
    return api_get("/api/dashboard/overview")


class HermesMonitorApp(rumps.App):
    def __init__(self):
        super().__init__(
            "Hermes",
            icon=None,
            quit_button=None,
        )
        load_api_key()

        # Menu items
        self.status_item = rumps.MenuItem("Status: checking...")
        self.model_item = rumps.MenuItem("Model: ...")
        self.gateway_item = rumps.MenuItem("Gateway: ...")
        self.api_item = rumps.MenuItem("API Server: ...")
        self.mcp_item = rumps.MenuItem("MCP: ...")
        self.cron_item = rumps.MenuItem("Cron: ...")
        self.sep1 = rumps.separator
        self.dashboard_btn = rumps.MenuItem("Dashboard Open", callback=self.open_dashboard)
        self.restart_btn = rumps.MenuItem("Gateway Restart", callback=self.restart_gateway)
        self.logs_btn = rumps.MenuItem("View Logs", callback=self.view_logs)
        self.sep2 = rumps.separator
        self.quit_btn = rumps.MenuItem("Quit", callback=rumps.quit_application)

        self.menu = [
            self.status_item,
            self.model_item,
            self.gateway_item,
            self.api_item,
            self.mcp_item,
            self.cron_item,
            self.sep1,
            self.dashboard_btn,
            self.restart_btn,
            self.logs_btn,
            self.sep2,
            self.quit_btn,
        ]

        # Initial check
        self.update_status(None)

    @rumps.timer(POLL_INTERVAL)
    def update_status(self, _):
        """Periodic status update."""
        gw_ok, gw_msg = check_gateway()
        api_ok, api_msg = check_api_server()

        if gw_ok and api_ok:
            self.title = "\u2705"  # Green check
            self.status_item.title = "Status: All OK"
        elif gw_ok:
            self.title = "\u26A0\uFE0F"  # Warning
            self.status_item.title = "Status: API issue"
        else:
            self.title = "\u274C"  # Red X
            self.status_item.title = "Status: Gateway down"

        self.gateway_item.title = f"Gateway: {gw_msg}"
        self.api_item.title = f"API Server: {api_msg}"

        # Get detailed overview
        overview = get_overview()
        if overview:
            self.model_item.title = f"Model: {overview.get('model', '?')}"
            mcp = overview.get("mcp_servers", {})
            self.mcp_item.title = f"MCP: {len(mcp)} server(s) ({', '.join(mcp.keys())})" if mcp else "MCP: none"
            crons = overview.get("cron_summary", [])
            active = sum(1 for c in crons if c.get("enabled"))
            errs = sum(1 for c in crons if c.get("last_status") and c.get("last_status") != "ok")
            self.cron_item.title = f"Cron: {active}/{len(crons)} active" + (f" ({errs} errors)" if errs else "")
        else:
            self.model_item.title = "Model: ?"
            self.mcp_item.title = "MCP: ?"
            self.cron_item.title = "Cron: ?"

    def open_dashboard(self, _):
        """Open dashboard in browser."""
        url = f"http://127.0.0.1:{API_PORT}/dashboard"
        if API_KEY:
            url += f"?key={API_KEY}"
        webbrowser.open(url)

    def restart_gateway(self, _):
        """Restart gateway via launchctl."""
        try:
            uid = os.getuid()
            subprocess.run(
                ["launchctl", "kickstart", "-k", f"gui/{uid}/ai.hermes.gateway"],
                capture_output=True, timeout=10,
            )
            rumps.notification("Hermes", "", "Gateway restart requested")
        except Exception as e:
            rumps.notification("Hermes", "Error", str(e))

    def view_logs(self, _):
        """Open gateway log in Console.app."""
        log_file = HERMES_HOME / "logs" / "gateway.log"
        if log_file.exists():
            subprocess.Popen(["open", "-a", "Console", str(log_file)])
        else:
            rumps.notification("Hermes", "", "Log file not found")


if __name__ == "__main__":
    HermesMonitorApp().run()
