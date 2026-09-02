#!/usr/bin/env python3
"""
rpc-pulse — a lightweight, zero-dependency JSON-RPC health & latency monitor
for blockchain nodes (Solana, EVM chains, Somnia, and any JSON-RPC endpoint).
Usage:
python rpc_pulse.py                  # run continuously using config.json
python rpc_pulse.py --once           # run a single check cycle and exit
python rpc_pulse.py --config my.json # use a custom config file
python rpc_pulse.py --interval 15    # override polling interval (seconds)
No third-party dependencies — uses only the Python standard library so it
runs anywhere Python 3.7+ is available, including older/lower-spec machines.
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
import concurrent.futures
from datetime import datetime, timezone

DEFAULT_CONFIG_PATH = "config.json"
DEFAULT_INTERVAL_SECONDS = 30
DEFAULT_TIMEOUT_SECONDS = 5
LOG_FILE = "rpc_pulse_log.jsonl"

# ANSI colors (safe no-ops on terminals that don't support them)
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

def load_config(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"{RED}Config file not found: {path}{RESET}")
        print("Copy config.example.json to config.json and edit it, then re-run.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"{RED}Invalid JSON in config file {path}: {e}{RESET}")
        sys.exit(1)

    if "endpoints" not in config or not isinstance(config["endpoints"], list):
        print(f"{RED}Config must contain an 'endpoints' list.{RESET}")
        sys.exit(1)
        
    return config

def extract_path(data, dotted_path):
    """Extract a value from nested JSON using a dotted path, e.g. 'result.value'."""
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

def check_endpoint(endpoint, timeout):
    """Send a JSON-RPC request to one endpoint and return a result dict."""
    name = endpoint.get("name", endpoint["url"])
    url = endpoint["url"]
    method = endpoint.get("method", "eth_blockNumber")
    params = endpoint.get("params", [])
    result_path = endpoint.get("result_path", "result")
    
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode("utf-8")
    
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; rpc-pulse/1.0; +https://github.com/meowrypto/rpc-pulse)",
        },
        method="POST",
    )
    
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            data = json.loads(raw)
            
            if "error" in data and data["error"]:
                return {
                    "name": name, "url": url, "ok": False,
                    "latency_ms": latency_ms, "error": str(data["error"]), "height": None,
                }
                
            raw_height = extract_path(data, result_path)
            height = None
            if isinstance(raw_height, str) and raw_height.startswith("0x"):
                height = int(raw_height, 16)
            elif isinstance(raw_height, (int, float)):
                height = int(raw_height)
                
            return {
                "name": name, "url": url, "ok": True,
                "latency_ms": latency_ms, "error": None, "height": height,
            }
            
    except urllib.error.URLError as e:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "name": name, "url": url, "ok": False,
            "latency_ms": latency_ms, 
            "error": str(e.reason if hasattr(e, "reason") else e), 
            "height": None,
        }
    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "name": name, "url": url, "ok": False,
            "latency_ms": latency_ms, "error": str(e), "height": None,
        }

def evaluate_status(result, endpoint, max_height):
    """Decide OK / WARN / FAIL for one endpoint result."""
    if not result["ok"]:
        return "FAIL", result["error"]

    latency_threshold = endpoint.get("latency_threshold_ms", 1000)
    height_lag_threshold = endpoint.get("height_lag_threshold", 5)
    
    reasons = []
    status = "OK"

    if result["latency_ms"] > latency_threshold:
        status = "WARN"
        reasons.append(f"latency {result['latency_ms']}ms > {latency_threshold}ms")

    if result["height"] is not None and max_height is not None:
        lag = max_height - result["height"]
        if lag > height_lag_threshold:
            status = "WARN" if status == "OK" else status
            reasons.append(f"height behind by {lag} (max seen: {max_height})")

    return status, "; ".join(reasons) if reasons else None

def color_for(status):
    return {"OK": GREEN, "WARN": YELLOW, "FAIL": RED}.get(status, RESET)

def print_report(results_with_status, timestamp):
    print(f"\n{BOLD}[{timestamp}] rpc-pulse check{RESET}")
    print("-" * 64)
    for r, status, reason in results_with_status:
        color = color_for(status)
        latency = f"{r['latency_ms']}ms" if r["latency_ms"] is not None else "n/a"
        height = r["height"] if r["height"] is not None else "n/a"
        
        line = f"{color}[{status:4}]{RESET} {r['name']:<20} latency={latency:<10} height={height}"
        if reason:
            line += f"  {color}({reason}){RESET}"
        print(line)
    print("-" * 64)

def write_log(results_with_status, timestamp, log_path):
    with open(log_path, "a", encoding="utf-8") as f:
        for r, status, reason in results_with_status:
            entry = {
                "timestamp": timestamp,
                "name": r["name"],
                "url": r["url"],
                "status": status,
                "latency_ms": r["latency_ms"],
                "height": r["height"],
                "reason": reason,
            }
            f.write(json.dumps(entry) + "\n")

def _check_wrapper(args):
    """Wrapper function for ThreadPoolExecutor to pass multiple arguments."""
    ep, timeout = args
    return check_endpoint(ep, timeout)

def run_cycle(config, log_path):
    timeout = config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    endpoints = config["endpoints"]
    
    # Execute network requests concurrently to prevent blocking
    args_list = [(ep, timeout) for ep in endpoints]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(endpoints)) as executor:
        raw_results = list(executor.map(_check_wrapper, args_list))

    # Height comparison logic
    group_max_height = {}
    for r, ep in zip(raw_results, endpoints):
        group = ep.get("group", ep["name"] if "name" in ep else r["name"])
        if r["height"] is not None:
            current = group_max_height.get(group)
            group_max_height[group] = r["height"] if current is None else max(current, r["height"])

    results_with_status = []
    for r, ep in zip(raw_results, endpoints):
        group = ep.get("group", ep["name"] if "name" in ep else r["name"])
        status, reason = evaluate_status(r, ep, group_max_height.get(group))
        results_with_status.append((r, status, reason))

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print_report(results_with_status, timestamp)
    write_log(results_with_status, timestamp, log_path)
    
    return any(status == "FAIL" for _, status, _ in results_with_status)

def main():
    parser = argparse.ArgumentParser(
        description="rpc-pulse — lightweight JSON-RPC health & latency monitor"
    )
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH, help="Path to config JSON file"
    )
    parser.add_argument(
        "--interval", type=int, default=None,
        help="Polling interval in seconds (overrides config)"
    )
    parser.add_argument(
        "--once", action="store_true", help="Run a single check cycle and exit"
    )
    parser.add_argument(
        "--log", default=LOG_FILE, help="Path to JSONL log file"
    )
    
    args = parser.parse_args()
    config = load_config(args.config)
    interval = args.interval or config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)
    
    print(f"{BOLD}rpc-pulse{RESET} monitoring {len(config['endpoints'])} endpoint(s)")
    print(f"Interval: {interval}s | Log file: {args.log}")

    if args.once:
        had_failure = run_cycle(config, args.log)
        sys.exit(1 if had_failure else 0)

    try:
        while True:
            run_cycle(config, args.log)
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n{BOLD}Stopped by user.{RESET}")
        sys.exit(0)

if __name__ == "__main__":
    main()