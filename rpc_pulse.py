#!/usr/bin/env python3
"""
rpc-pulse — Production-grade JSON-RPC health monitor, smart proxy, and alerter.
Features:
- Smart Local RPC Proxy with automatic failover.
- Rich Terminal UI (TUI) with graceful fallback to ANSI.
- Webhook Alerting (Discord/Telegram) with cooldown management.
- Zero mandatory third-party dependencies.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import threading
import socketserver
from datetime import datetime, timezone
from collections import deque

# Optional rich TUI support
try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

DEFAULT_CONFIG_PATH = "config.json"
LOG_FILE = "rpc_pulse_log.jsonl"

# ANSI Colors for fallback TUI
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"
CLEAR_SCREEN = "\033[2J\033[H"


class EndpointState:
    """Holds real-time metrics and history for a single endpoint."""
    def __init__(self, name):
        self.name = name
        self.status = "UNKNOWN"
        self.latency_ms = None
        self.height = None
        self.lag = 0
        self.latency_history = deque(maxlen=20)
        self.success_count = 0
        self.total_checks = 0
        self.last_error = None
        self.last_alert_time = {}  # Maps alert_reason -> timestamp


class RPCMonitor:
    """Core monitoring logic and state management."""
    def __init__(self, config):
        self.config = config
        self.endpoints = config.get("endpoints", [])
        self.states = {ep["name"]: EndpointState(ep["name"]) for ep in self.endpoints}
        self.lock = threading.Lock()
        self.running = True

    def get_best_endpoint(self):
        """Returns the healthiest endpoint for proxy routing."""
        with self.lock:
            valid_endpoints = []
            for ep in self.endpoints:
                state = self.states[ep["name"]]
                if state.status == "OK" and state.latency_ms is not None:
                    valid_endpoints.append((ep, state.latency_ms))
            
            if not valid_endpoints:
                return None
            
            valid_endpoints.sort(key=lambda x: x[1])
            return valid_endpoints[0][0]

    def check_endpoint(self, endpoint):
        """Perform a single health check on an endpoint."""
        name = endpoint.get("name", endpoint["url"])
        url = endpoint["url"]
        method = endpoint.get("method", "eth_blockNumber")
        params = endpoint.get("params", [])
        result_path = endpoint.get("result_path", "result")
        timeout = self.config.get("timeout_seconds", 5)

        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                latency_ms = round((time.monotonic() - start) * 1000, 1)
                data = json.loads(raw)

                if "error" in data and data["error"]:
                    return {"ok": False, "latency_ms": latency_ms, "error": str(data["error"]), "height": None}

                raw_height = self._extract_path(data, result_path)
                height = None
                if isinstance(raw_height, str) and raw_height.startswith("0x"):
                    height = int(raw_height, 16)
                elif isinstance(raw_height, (int, float)):
                    height = int(raw_height)

                return {"ok": True, "latency_ms": latency_ms, "error": None, "height": height}
        except urllib.error.URLError as e:
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            return {"ok": False, "latency_ms": latency_ms, "error": str(e.reason), "height": None}
        except Exception as e:
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            return {"ok": False, "latency_ms": latency_ms, "error": str(e), "height": None}

    def _extract_path(self, data, dotted_path):
        current = data
        for part in dotted_path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                current = current[idx] if idx < len(current) else None
            else:
                return None
        return current

    def run_cycle(self):
        """Execute one full monitoring cycle."""
        timeout = self.config.get("timeout_seconds", 5)
        results = {}
        
        for ep in self.endpoints:
            res = self.check_endpoint(ep)
            results[ep["name"]] = res

        with self.lock:
            max_heights = {}
            for ep in self.endpoints:
                group = ep.get("group", ep["name"])
                res = results[ep["name"]]
                if res["ok"] and res["height"] is not None:
                    current_max = max_heights.get(group, 0)
                    max_heights[group] = max(current_max, res["height"])

            for ep in self.endpoints:
                name = ep["name"]
                res = results[name]
                state = self.states[name]
                group = ep.get("group", name)
                
                state.total_checks += 1
                if res["ok"]:
                    state.success_count += 1
                    state.status = "OK"
                else:
                    state.status = "FAIL"
                
                state.latency_ms = res["latency_ms"]
                state.height = res["height"]
                state.last_error = res["error"]
                
                if res["ok"] and res["latency_ms"] is not None:
                    state.latency_history.append(res["latency_ms"])

                if state.height is not None and max_heights.get(group) is not None:
                    state.lag = max_heights[group] - state.height
                else:
                    state.lag = 0

                self._evaluate_and_alert(ep, state)

        self._write_log()

    def _evaluate_and_alert(self, endpoint, state):
        """Check thresholds and trigger alerts if necessary."""
        alerts_config = self.config.get("alerts", {})
        cooldown_minutes = alerts_config.get("cooldown_minutes", 10)
        cooldown_seconds = cooldown_minutes * 60
        now = time.time()

        latency_threshold = endpoint.get("latency_threshold_ms", 1000)
        height_lag_threshold = endpoint.get("height_lag_threshold", 5)

        alerts_to_send = []

        if state.status == "FAIL":
            alerts_to_send.append(("FAIL", f"Endpoint is DOWN or returning errors: {state.last_error}"))
        elif state.status == "OK" and state.last_error is not None:
            alerts_to_send.append(("RECOVERY", "Endpoint has recovered and is now OK."))
            state.last_error = None

        if state.status == "OK" and state.lag > height_lag_threshold:
            alerts_to_send.append(("LAG", f"Block height lag is {state.lag} (threshold: {height_lag_threshold})"))

        if state.status == "OK" and state.latency_ms and state.latency_ms > (latency_threshold * 1.5):
            alerts_to_send.append(("LATENCY", f"High latency detected: {state.latency_ms}ms"))

        for alert_type, message in alerts_to_send:
            last_alert = state.last_alert_time.get(alert_type, 0)
            if now - last_alert > cooldown_seconds:
                self._send_webhook(endpoint["name"], alert_type, message, alerts_config)
                state.last_alert_time[alert_type] = now

    def _send_webhook(self, name, alert_type, message, alerts_config):
        """Send alert to Discord or Telegram."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        color = 16711680 if alert_type == "FAIL" else 16776960 if alert_type == "RECOVERY" else 16753920
        
        discord_url = alerts_config.get("discord_webhook_url")
        tg_token = alerts_config.get("telegram_bot_token")
        tg_chat = alerts_config.get("telegram_chat_id")

        discord_payload = {
            "embeds": [{
                "title": f"🚨 RPC Alert: {alert_type}",
                "description": f"**Endpoint:** {name}\n**Message:** {message}\n**Time:** {timestamp}",
                "color": color
            }]
        }

        tg_text = f"🚨 *RPC Alert: {alert_type}*\n\n*Endpoint:* `{name}`\n*Message:* {message}\n*Time:* {timestamp}"

        if discord_url:
            try:
                req = urllib.request.Request(discord_url, data=json.dumps(discord_payload).encode("utf-8"), headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass

        if tg_token and tg_chat:
            try:
                url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
                payload = {"chat_id": tg_chat, "text": tg_text, "parse_mode": "Markdown"}
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass

    def _write_log(self):
        """Append current state to JSONL log file."""
        log_path = self.config.get("log_file", LOG_FILE)
        max_mb = self.config.get("log_max_mb", 5)
        
        if os.path.exists(log_path) and (os.path.getsize(log_path) > max_mb * 1024 * 1024):
            os.rename(log_path, f"{log_path}.1")

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(log_path, "a", encoding="utf-8") as f:
            with self.lock:
                for name, state in self.states.items():
                    entry = {
                        "timestamp": timestamp,
                        "name": name,
                        "status": state.status,
                        "latency_ms": state.latency_ms,
                        "height": state.height,
                        "lag": state.lag,
                        "success_rate": round((state.success_count / state.total_checks) * 100, 1) if state.total_checks > 0 else 0
                    }
                    f.write(json.dumps(entry) + "\n")


class SmartProxyHandler(socketserver.BaseHTTPRequestHandler):
    """HTTP Handler for the local smart proxy."""
    monitor = None  # Will be set by the server

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        proxy_config = self.monitor.config.get("proxy", {})
        timeout = self.monitor.config.get("timeout_seconds", 5)
        
        best_ep = self.monitor.get_best_endpoint()
        if not best_ep:
            self.send_error(503, "No healthy RPC endpoints available")
            return

        url = best_ep["url"]
        attempts = [best_ep]
        
        for ep in attempts:
            try:
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    self.send_response(resp.status)
                    for key, val in resp.headers.items():
                        if key.lower() not in ('transfer-encoding', 'connection'):
                            self.send_header(key, val)
                    self.end_headers()
                    self.wfile.write(resp.read())
                    return
            except Exception:
                continue
        
        self.send_error(502, "All RPC endpoints failed to respond")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


def render_tui(monitor):
    """Render the Terminal UI, using Rich if available, otherwise ANSI fallback."""
    if HAS_RICH:
        console = Console()
        table = Table(title="RPC Pulse Monitor", expand=True)
        table.add_column("Endpoint", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Latency", justify="right")
        table.add_column("Sparkline", justify="center")
        table.add_column("Height", justify="right")
        table.add_column("Lag", justify="right")
        table.add_column("Success %", justify="right")

        with monitor.lock:
            for name, state in monitor.states.items():
                status_color = "green" if state.status == "OK" else "red"
                status_text = Text(state.status, style=status_color)
                
                latency_str = f"{state.latency_ms}ms" if state.latency_ms else "N/A"
                height_str = str(state.height) if state.height else "N/A"
                lag_str = str(state.lag) if state.lag else "N/A"
                success_str = f"{(state.success_count/state.total_checks*100):.1f}%" if state.total_checks > 0 else "N/A"
                
                spark = ""
                if state.latency_history:
                    max_lat = max(state.latency_history) or 1
                    for lat in state.latency_history:
                        intensity = int((lat / max_lat) * 8)
                        spark += ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"][intensity]
                
                table.add_row(name, status_text, latency_str, spark, height_str, lag_str, success_str)
        
        return table
    else:
        lines = [CLEAR_SCREEN, f"{BOLD}{'RPC PULSE MONITOR':^64}{RESET}", "-" * 64]
        header = f"{'ENDPOINT':<25} | {'STATUS':<6} | {'LATENCY':<10} | {'HEIGHT':<12} | {'LAG':<6} | {'SUCCESS'}"
        lines.append(header)
        lines.append("-" * 64)
        
        with monitor.lock:
            for name, state in monitor.states.items():
                color = GREEN if state.status == "OK" else RED
                status = f"{color}{state.status:<6}{RESET}"
                latency = f"{state.latency_ms}ms" if state.latency_ms else "N/A"
                height = str(state.height) if state.height else "N/A"
                lag = str(state.lag) if state.lag else "N/A"
                success = f"{(state.success_count/state.total_checks*100):.1f}%" if state.total_checks > 0 else "N/A"
                
                spark = ""
                if state.latency_history:
                    max_lat = max(state.latency_history) or 1
                    for lat in state.latency_history:
                        intensity = int((lat / max_lat) * 4)
                        spark += ["▂", "▃", "▄", "▅", "█"][intensity]
                
                lines.append(f"{name:<25} | {status} | {latency:<10} | {height:<12} | {lag:<6} | {success} {spark}")
        lines.append("-" * 64)
        lines.append("Press Ctrl+C to stop")
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="rpc-pulse — Production-grade RPC monitor & proxy")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config JSON file")
    parser.add_argument("--once", action="store_true", help="Run a single check cycle and exit")
    parser.add_argument("--tui", action="store_true", help="Enable interactive Terminal UI")
    args = parser.parse_args()

    try:
        with open(args.config, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"{RED}Config file not found: {args.config}{RESET}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"{RED}Invalid JSON in config file: {e}{RESET}")
        sys.exit(1)

    monitor = RPCMonitor(config)
    
    if args.once:
        monitor.run_cycle()
        print(render_tui(monitor) if not HAS_RICH else "Single check completed. Check logs for details.")
        sys.exit(0)

    proxy_config = config.get("proxy", {})
    if proxy_config.get("enabled", False):
        port = proxy_config.get("port", 8545)
        SmartProxyHandler.monitor = monitor
        server = ThreadedHTTPServer(("127.0.0.1", port), SmartProxyHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        print(f"{GREEN}Smart Proxy started on http://127.0.0.1:{port}{RESET}")

    print(f"{BOLD}Starting RPC Pulse Monitor...{RESET}")
    if not HAS_RICH and args.tui:
        print(f"{YELLOW}Note: 'rich' library not found. Using ANSI fallback TUI. Install with: pip install rich{RESET}")

    interval = config.get("interval_seconds", 10)
    try:
        while True:
            monitor.run_cycle()
            if args.tui:
                print(render_tui(monitor))
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n{BOLD}Stopped by user.{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()