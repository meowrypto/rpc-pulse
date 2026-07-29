# rpc-pulse

[![Support this project](https://img.shields.io/badge/support-donatr.ee-orange?logo=heart&logoColor=white)](https://donatr.ee/meowrypto/)

A lightweight, **zero-dependency** JSON-RPC health & latency monitor for blockchain nodes.

Check the latency, sync status, and block height of one or more RPC endpoints
(Solana, Ethereum/EVM chains, Somnia, or any JSON-RPC-compatible chain) from a
single small Python script — no Grafana, no Prometheus, no Docker stack required.

```
[2026-07-24 10:15:32 UTC] rpc-pulse check
----------------------------------------------------------------
[OK  ] Solana Mainnet       latency=142.3ms   height=301829123
[WARN] Ethereum (public)    latency=1240.1ms  height=20981233  (latency 1240.1ms > 1000ms)
[FAIL] Somnia RPC           latency=n/a       height=n/a       (Connection refused)
----------------------------------------------------------------
```

## Why this exists

If you're staking, validating, or just relying on a public/private RPC endpoint,
it's easy to be flying blind — you don't find out an endpoint is lagging or down
until something else breaks. Full observability stacks (Prometheus + Grafana,
etc.) are overkill if you just want to know: *is this endpoint fast, healthy,
and in sync right now?*

rpc-pulse aims to be the smallest useful tool that answers that question —
readable in one sitting, runs anywhere Python 3.7+ runs, and has no
dependencies to install or maintain.

## Features

- Polls any number of JSON-RPC endpoints on a configurable interval
- Measures round-trip latency per endpoint
- Extracts block height / slot number and flags endpoints falling behind the pack
- Color-coded terminal output (OK / WARN / FAIL)
- Structured JSONL log file for later analysis
- Single-run mode (`--once`) for use in cron jobs or CI health checks
- No third-party dependencies — pure Python standard library

## Requirements

- Python 3.7 or later
- No external packages needed

## Installation

```bash
git clone https://github.com/<your-username>/rpc-pulse.git
cd rpc-pulse
cp config.example.json config.json
```

Edit `config.json` and replace the example endpoints with the RPC URLs you
want to monitor.

## Usage

Run continuously (default interval from config, or override with `--interval`):

```bash
python rpc_pulse.py
```

Run a single check cycle and exit (useful for cron / scheduled tasks):

```bash
python rpc_pulse.py --once
```

Use a custom config file or interval:

```bash
python rpc_pulse.py --config production.json --interval 15
```

Exit code is `1` if any endpoint reports `FAIL` in `--once` mode, so it can be
used directly in health-check scripts or CI pipelines.

## Configuration reference

`config.json` structure:

```json
{
  "interval_seconds": 30,
  "timeout_seconds": 5,
  "endpoints": [
    {
      "name": "My Endpoint",
      "url": "https://your-rpc-url",
      "method": "eth_blockNumber",
      "params": [],
      "result_path": "result",
      "latency_threshold_ms": 1000,
      "height_lag_threshold": 5
    }
  ]
}
```

| Field                  | Description                                                                 |
|------------------------|-------------------------------------------------------------------------------|
| `name`                 | Display name for the endpoint                                                 |
| `url`                  | JSON-RPC endpoint URL                                                         |
| `method`               | JSON-RPC method used to fetch the current height (e.g. `getSlot`, `eth_blockNumber`) |
| `params`               | Params array for the RPC call (usually empty)                                 |
| `result_path`          | Dotted path to the height value in the JSON response (e.g. `result` or `result.value`) |
| `latency_threshold_ms` | Latency above this triggers a `WARN` status                                   |
| `height_lag_threshold` | If an endpoint's height falls this far behind the highest seen **in its group**, triggers `WARN` |
| `group` (optional)     | Endpoints only get compared for height-lag against others in the same group. Defaults to the endpoint's own `name`, so unrelated chains are never compared by default. Set two endpoints to the same `group` (e.g. `"ethereum"`) when you're monitoring multiple providers of the *same* chain and want to catch one falling behind the others. |

This works for any JSON-RPC chain — just change `method` and `result_path` to
match the chain's API (e.g. Solana's `getSlot` returns a plain integer in
`result`; EVM chains' `eth_blockNumber` returns a hex string in `result`, which
rpc-pulse decodes automatically).

## Log output

Every check cycle appends one JSON line per endpoint to `rpc_pulse_log.jsonl`:

```json
{"timestamp": "2026-07-24 10:15:32 UTC", "name": "Solana Mainnet", "url": "...", "status": "OK", "latency_ms": 142.3, "height": 301829123, "reason": null}
```

This makes it easy to feed into a spreadsheet, `jq`, or a plotting script later.

## Contributing

Issues and pull requests are welcome — especially additional chain examples
for `config.example.json`, or small robustness improvements. Please keep the
zero-dependency philosophy: if a feature needs a third-party package, discuss
it in an issue first.

## Support

If rpc-pulse is useful to you, consider supporting its development:

**[https://donatr.ee/meowrypto/](https://donatr.ee/meowrypto/)**

<img src="assets/donate-qr.gif" alt="Donation QR code" width="180" />

## License

MIT — see [LICENSE](LICENSE).

