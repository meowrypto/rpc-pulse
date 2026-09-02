# ⚡ rpc-pulse

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.7+-blue.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python Version" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge" alt="License" /></a>
  <a href="https://github.com/meowrypto/rpc-pulse"><img src="https://img.shields.io/badge/dependencies-zero%20mandatory-brightgreen.svg?style=for-the-badge" alt="Dependencies" /></a>
  <a href="https://donatr.ee/meowrypto/"><img src="https://img.shields.io/badge/support-donatr.ee-orange?style=for-the-badge&logo=heart&logoColor=white" alt="Support" /></a>
</p>

<p align="center">
  <b>A lightweight, production-grade JSON-RPC health monitor, smart proxy, and alerting system for blockchain nodes.</b><br>
  <i>Monitor latency, sync status, and block height across EVM, Solana, and custom chains — without Grafana, Prometheus, or heavy Docker stacks.</i>
</p>

---

## 🖥️ Live Terminal Interface (TUI Mode)

Launch `rpc-pulse` with the `--tui` flag for a real-time, interactive dashboard in your terminal:

| ENDPOINT | STATUS | LATENCY | SPARKLINE | HEIGHT | LAG | SUCCESS |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Solana Mainnet** | ` OK ` | 124.2ms | ▂▃▄▅█ | 301829123 | 0 | 99.8% |
| **Ethereum PublicNode** | ` OK ` | 85.4ms | ▂▂▃▄▅ | 20658421 | 0 | 100.0% |
| **Ethereum Cloudflare** | `WARN` | 1020.1ms | ▄▅▆▇█ | 20658418 | 3 | 98.2% |

---

## 🚀 Key Features

* **🔄 Smart Local RPC Proxy**: Built-in HTTP proxy (`http://127.0.0.1:8545`) that routes JSON-RPC requests to the healthiest and lowest-latency node with instant, transparent failover.
* **📊 Live Terminal UI (TUI)**: Interactive dashboard featuring real-time latency sparklines, block height tracking, and success rates.
* **🚨 Webhook Alerting**: Instant Discord & Telegram notifications for node downtime, recovery, height lag, and latency spikes with cooldown spam prevention.
* **📦 Zero Mandatory Dependencies**: Operates 100% on Python 3.7+ standard library. Optional integration support for `rich` (enhanced UI) and `websockets` (WSS testing).
* **💾 Log Rotation & Metrics**: Automatically limits log file sizes (`log_max_mb`) to prevent disk overload, saving structured `.jsonl` data.

---

## 🏗️ Architecture & Proxy Flow

```text
                  +-------------------------+
                  | Web3 App / Bot / Wallet |
                  +------------+------------+
                               | Sends Requests
                               v
                  +-------------------------+
                  |  rpc-pulse Smart Proxy  |
                  |     (localhost:8545)    |
                  +------------+------------+
                               |
         +---------------------+---------------------+
         | (Best Latency)      | (Fallback 1)        | (Fallback 2)
         v                     v                     v
  +--------------+      +--------------+      +--------------+
  | RPC Node #1  |      | RPC Node #2  |      | RPC Node #3  |
  | Status: OK   |      | Status: WARN |      | Status: FAIL |
  +--------------+      +--------------+      +--------------+
```
---

## ⚡ Quick Start

### 1. Clone & Setup

```bash
git clone [https://github.com/meowrypto/rpc-pulse.git](https://github.com/meowrypto/rpc-pulse.git)cd rpc-pulse
cp config.example.json config.json

```

### 2. Optional Enhancements (Recommended)

`rpc-pulse` works out-of-the-box with zero third-party packages. Install these only if you want enhanced features:

```bash
# For rich interactive TUI sparklines and formatted tables
pip install rich

# For testing WebSocket (ws:// / wss://) endpoints
pip install websockets

```

---

## 💻 Usage Examples

> [!TIP]
> **Running in Production?** Use `--tui` for monitoring sessions or `--once` for automated Cron / CI health checks!

| Command | Description |
| --- | --- |
| `python rpc_pulse.py` | Continuous background monitoring with JSONL logging |
| `python rpc_pulse.py --tui` | Interactive live terminal dashboard |
| `python rpc_pulse.py --once` | Executes a single check cycle and exits with status codes (0 = OK, 1 = FAIL) |
| `python rpc_pulse.py --config my_config.json` | Runs using a custom configuration file |

---

## 🌐 Smart Proxy Integration

> [!NOTE]
> Point your local tools to `http://127.0.0.1:8545` to automatically execute transactions and RPC calls through the fastest available node in your pool.

1. Enable the proxy in your `config.json` (`"proxy": { "enabled": true, "port": 8545 }`).
2. Update your Web3 tools / scripts:
* **MetaMask**: Custom RPC URL -> `http://127.0.0.1:8545`
* **Web3.py / Ethers.js**: Set HTTP Provider -> `http://127.0.0.1:8545`
* **Foundry / Hardhat**: `--rpc-url http://127.0.0.1:8545`



---

## ⚙️ Configuration Guide (`config.json`)

```json
{
  "interval_seconds": 10,
  "timeout_seconds": 5,
  "log_max_mb": 5,
  "proxy": {
    "enabled": true,
    "port": 8545
  },
  "alerts": {
    "discord_webhook_url": "[https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_TOKEN](https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_TOKEN)",
    "telegram_bot_token": "YOUR_BOT_TOKEN",
    "telegram_chat_id": "YOUR_CHAT_ID",
    "cooldown_minutes": 10
  },
  "endpoints": [
    {
      "name": "Ethereum PublicNode",
      "url": "[https://ethereum-rpc.publicnode.com](https://ethereum-rpc.publicnode.com)",
      "method": "eth_blockNumber",
      "params": [],
      "result_path": "result",
      "latency_threshold_ms": 1000,
      "height_lag_threshold": 3,
      "group": "ethereum"
    }
  ]
}

```

### Parameter Reference

| Parameter | Type | Description |
| --- | --- | --- |
| `interval_seconds` | `int` | Frequency of node health checks (in seconds). |
| `timeout_seconds` | `int` | Maximum response timeout before marking requests as `FAIL`. |
| `log_max_mb` | `int` | Size limit before `.jsonl` log file rotation occurs. |
| `proxy.enabled` | `bool` | Enables the smart local load balancing proxy. |
| `alerts.cooldown_minutes` | `int` | Minimum time between identical alert notifications to avoid spam. |
| `endpoints[].group` | `string` | Categorizes nodes by chain to measure relative block height lag. |

---

## 📝 Log Format

Logs are stored in machine-readable JSON-Lines (`.jsonl`) format:

```json
{"timestamp": "2026-09-02 10:15:32 UTC", "name": "Solana Mainnet", "url": "[https://api.mainnet-beta.solana.com](https://api.mainnet-beta.solana.com)", "status": "OK", "latency_ms": 142.3, "height": 301829123, "lag": 0, "success_rate": 99.8}

```

---

## 🤝 Contributing

Issues and pull requests are highly welcome! Feel free to open an issue or submit improvements for performance and new chain configurations.

---

## ☕ Support

If `rpc-pulse` helps optimize your Web3 infrastructure, feel free to support the project:

👉 **[donatr.ee/meowrypto](https://www.google.com/url?sa=E&source=gmail&q=https://donatr.ee/meowrypto/)**

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for details.

```

```