# Antigravity Quota Monitor (v3.0 Enterprise Edition)

A high-resilience, modular system tray gauge and compact visual dashboard for Linux (`Openbox`/`Tint2` and freedesktop system trays) built according to the **gutterDesk** and **Banyan** systems engineering protocols ([AGENTS.md](AGENTS.md)).

Tracks **both 5-Hour and Weekly token limits** for Google Antigravity across local and remote SSH cluster nodes (`aim-stream`, `aim-home`, `aim-book`) via Connect-RPC.

---

## Architecture Overview

Built upon a strict 3-tier SOLID architecture without third-party runtime package dependencies beyond native system `PyGObject` (`gi.repository.Gtk`, `cairo`):

```text
antigravity-quota-monitor/
├── AGENTS.md                           # Mandatory cluster engineering protocol
├── README.md                           # Architecture & operational runbook
├── install.sh                          # Idempotent dual-mode installer
├── bin/
│   └── antigravity-indicator           # Executable launcher (~/.local/bin or /usr/local/bin)
├── systemd/
│   └── antigravity-quota-monitor.service # Managed systemd user unit (Restart=on-failure)
├── antigravity_monitor/
│   ├── domain/
│   │   ├── models.py                   # Immutable dataclasses (QuotaBucket, PoolQuota, HostQuotaSnapshot)
│   │   └── policy.py                   # Pure business logic (Proto3 parser, quartile colors, 2-ring builder)
│   ├── infrastructure/
│   │   ├── probe_agent.py              # Pure stdlib /proc + Connect-RPC probe (local or streamed over SSH)
│   │   ├── probe_service.py            # Local/Remote probe coordinator with stale ControlMaster recovery
│   │   ├── ssh_discovery.py            # ~/.ssh/config parser & local interface resolution
│   │   ├── settings_repository.py      # Atomic JSON persistence (write-temp-and-rename)
│   │   └── ipc_server.py               # UNIX domain socket singleton & CLI command forwarder
│   └── presentation/
│       ├── cairo_gauge.py              # Pure Cairo 2-ring vector gauge & linear progress bar painter
│       ├── popup_window.py             # Deterministic Tint2-docked GTK3 dashboard window
│       ├── context_menu.py             # Right-click native GTK3 context menu
│       └── tray_daemon.py              # DI orchestrator, StatusIcon embedding watchdog, GLib timer loop
└── tests/
    └── test_domain_and_probe.py        # Automated unit test suite
```

---

## Visual Design & Concentric Ring Mapping

### 1. System Tray Icon (2 Bold Concentric Rings)
Rendered at 2× supersampling (`48×48` $\rightarrow$ `24×24`) with bold strokes (`5.6px` outer, `5.2px` inner) dynamically prioritizing your active model pool from `~/.gemini/antigravity/antigravity_state.pbtxt`:

- **Outer Ring**: **Active Pool — 5-Hour Limit** (e.g. `Gemini 5h` when using `Gemini 3.8 Flash`)
- **Inner Ring**: **Active Pool — Weekly Limit** (e.g. `Gemini Wk`)

#### Color Thresholds (Quartile Health Scale)
| Remaining Quota | Color | Hex | Health Meaning |
| :--- | :--- | :--- | :--- |
| **$> 75\%$** | Sage / Emerald Green | `#62c98b` | Full headroom |
| **$50\% - 75\%$** | Amber / Gold | `#facc15` | Normal working draw |
| **$25\% - 50\%$** | Warning Orange | `#fb923c` | Approaching burst governor |
| **$\le 25\%$** | Critical Crimson | `#f87171` | Burst cap imminent |

---

## Single-Instance UNIX Socket IPC

Running secondary CLI invocations communicates with the running singleton daemon over `$XDG_RUNTIME_DIR/antigravity-quota-monitor.sock` rather than spawning duplicate tray icons:

```bash
# Toggle the visual dashboard panel
antigravity-indicator --show

# Force an immediate live cloud quota refresh
antigravity-indicator --refresh

# Pin running daemon to a specific cluster node
antigravity-indicator --host aim-stream
antigravity-indicator --host aim-home

# Dump normalized JSON quota snapshot to stdout and exit
antigravity-indicator --dump-json
```

---

## Lifecycle Management (`systemd --user`)

The daemon is managed by systemd user session management, providing automatic crash recovery (`Restart=on-failure`, `RestartSec=3`) and integrated logging:

```bash
# Check daemon status
systemctl --user status antigravity-quota-monitor.service

# View live daemon logs
journalctl --user -u antigravity-quota-monitor.service -f

# Restart daemon
systemctl --user restart antigravity-quota-monitor.service
```

---

## Automated Unit Testing

Run the automated test suite directly via Python's standard `unittest`:

```bash
python3 -m unittest discover -s tests -v
```

Verifies:
1. Go Proto3 zero-omission fraction parsing (`remainingFraction` omitted when `0.0`).
2. Quartile color band thresholds (`#62c98b`, `#facc15`, `#fb923c`, `#f87171`).
3. Model-to-pool classification (`Gemini 4 Argon`, `Gemini 3.8 Flash`, `Claude Opus/Sonnet 5.5`).
4. Two-ring concentric gauge generation (`Outer = 5h`, `Inner = Weekly`).
5. Local vs. remote SSH target resolution.

---

## Installation & Deployment

```bash
# Idempotent dual-mode install (user-space ~/.local/ without sudo)
./install.sh

# Or install system-wide to /usr/local/
sudo ./install.sh
```

---

## License

This project is licensed under the [MIT License](LICENSE).
