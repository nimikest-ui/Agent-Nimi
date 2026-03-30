"""
Background Monitor - Periodic system health checks, live stats, and alerts.
Uses psutil for cross-platform metrics + optional nvidia-smi for GPU.
"""
import threading
import time
import datetime
import subprocess

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False


class SystemMonitor:
    """Background system health monitor with live stats and configurable alerts."""

    def __init__(self, config: dict):
        self.config = config.get("monitoring", {})
        self.alerts_config = self.config.get("alerts", {})
        self.interval = self.config.get("check_interval_seconds", 5)
        self._running = False
        self._thread = None
        self.alert_log: list[dict] = []
        self.alert_callbacks: list = []
        # Live stats cache
        self._stats: dict = {}
        self._stats_lock = threading.Lock()
        # Network delta tracking
        self._net_prev = None
        self._net_prev_time = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def is_running(self) -> bool:
        return self._running

    def on_alert(self, callback):
        self.alert_callbacks.append(callback)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return last collected live stats (collect fresh if not started)."""
        if not self._running:
            try:
                stats = self._collect_stats()
                with self._stats_lock:
                    self._stats = stats
            except Exception:
                pass
        with self._stats_lock:
            return dict(self._stats)

    def get_alerts(self, limit: int = 20) -> list[dict]:
        return self.alert_log[-limit:]

    # ── Loop ──────────────────────────────────────────────────────────────────

    def _monitor_loop(self):
        while self._running:
            try:
                stats = self._collect_stats()
                with self._stats_lock:
                    self._stats = stats
                self._check_thresholds(stats)
            except Exception:
                pass
            time.sleep(self.interval)

    # ── Collection ────────────────────────────────────────────────────────────

    def _collect_stats(self) -> dict:
        stats = {}
        if not _PSUTIL:
            stats["error"] = "psutil not installed"
            return stats

        # CPU
        try:
            stats["cpu"] = f"{psutil.cpu_percent(interval=1):.1f}%"
            stats["cpu_cores"] = str(psutil.cpu_count(logical=True))
        except Exception:
            pass

        # Memory
        try:
            mem = psutil.virtual_memory()
            stats["ram"] = f"{mem.percent:.1f}%  ({_fmt(mem.used)} / {_fmt(mem.total)})"
        except Exception:
            pass

        # Disk
        try:
            disk = psutil.disk_usage("/")
            stats["disk"] = f"{disk.percent:.1f}%  ({_fmt(disk.used)} / {_fmt(disk.total)})"
        except Exception:
            pass

        # Network speed (delta since last call)
        try:
            net = psutil.net_io_counters()
            now = time.time()
            if self._net_prev is not None and self._net_prev_time is not None:
                dt = max(now - self._net_prev_time, 0.001)
                sent_ps = (net.bytes_sent - self._net_prev.bytes_sent) / dt
                recv_ps = (net.bytes_recv - self._net_prev.bytes_recv) / dt
                stats["net_upload"] = f"{_fmt(sent_ps)}/s"
                stats["net_download"] = f"{_fmt(recv_ps)}/s"
            self._net_prev = net
            self._net_prev_time = now
        except Exception:
            pass

        # GPU via nvidia-smi
        try:
            result = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0:
                for i, line in enumerate(result.stdout.strip().splitlines()):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 5:
                        name, util, mem_used, mem_total, temp = parts[:5]
                        p = f"gpu{i}_" if i > 0 else "gpu_"
                        stats[f"{p}name"] = name
                        stats[f"{p}util"] = f"{util}%"
                        stats[f"{p}mem"] = f"{mem_used} MB / {mem_total} MB"
                        stats[f"{p}temp"] = f"{temp}°C"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        except Exception:
            pass

        # Uptime
        try:
            up = time.time() - psutil.boot_time()
            h, m = divmod(int(up // 60), 60)
            d, h = divmod(h, 24)
            stats["uptime"] = f"{d}d {h}h {m}m" if d else f"{h}h {m}m"
        except Exception:
            pass

        return stats

    # ── Threshold alerts ──────────────────────────────────────────────────────

    def _check_thresholds(self, stats: dict):
        def _pct(val: str) -> float:
            try:
                return float(val.split("%")[0].strip())
            except Exception:
                return 0.0

        checks = [
            ("cpu",  "cpu_threshold",    90),
            ("ram",  "memory_threshold", 90),
            ("disk", "disk_threshold",   90),
        ]
        for key, cfg_key, default in checks:
            if key in stats:
                pct = _pct(stats[key])
                threshold = self.alerts_config.get(cfg_key, default)
                if pct > threshold:
                    self._fire_alert(key, f"{key.upper()} at {pct:.1f}% (threshold: {threshold}%)")

    def _fire_alert(self, alert_type: str, message: str):
        # Debounce: don't repeat same alert within 5 min
        cutoff = datetime.datetime.now() - datetime.timedelta(minutes=5)
        for a in reversed(self.alert_log):
            ts = datetime.datetime.fromisoformat(a["timestamp"])
            if a["type"] == alert_type and ts > cutoff:
                return
        alert = {
            "timestamp": datetime.datetime.now().isoformat(),
            "type": alert_type,
            "message": message,
        }
        self.alert_log.append(alert)
        for cb in self.alert_callbacks:
            try:
                cb(alert)
            except Exception:
                pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
