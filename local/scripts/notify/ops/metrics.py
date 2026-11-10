"""Prometheus metrics exporter."""

import logging
import os
import threading
from wsgiref.simple_server import make_server

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY,
)

log = logging.getLogger("metrics")

# Counters
messages_received = Counter("bot_messages_received_total", "Messages received", ["channel_id"])
claude_timeout = Counter("claude_timeout_total", "Claude subprocess timeouts")
cache_hit = Counter("cache_hit_total", "Cache hits")
cache_miss = Counter("cache_miss_total", "Cache misses")
rate_limit_rejected = Counter("rate_limit_rejected_total", "Rate limit rejections", ["user_id"])
content_blocked = Counter("content_filter_blocked_total", "Content filter blocks", ["rule_id"])
injection_detected = Counter(
    "injection_detected_total", "Prompt-injection signals on untrusted input", ["source", "verdict"]
)
budget_exceeded = Counter("budget_exceeded_total", "Monthly per-user budget cap hits", ["user_id"])
permission_denied = Counter("permission_denied_total", "Permission denials", ["reason"])
two_factor_challenge = Counter("two_factor_challenge_total", "2FA challenges")
two_factor_success = Counter("two_factor_success_total", "2FA successes")
tts_plays = Counter("tts_play_total", "TTS plays")
anomaly_detected = Counter("anomaly_detected_total", "Anomalies detected")
user_requests = Counter("bot_user_requests_total", "Requests per user", ["user_id", "channel_id"])
agent_requests = Counter("bot_agent_requests_total", "Requests handled per BMAD agent", ["agent"])

# Histograms
subprocess_duration = Histogram(
    "claude_subprocess_duration_seconds",
    "Subprocess duration",
    buckets=[5, 15, 30, 60, 120, 240, 360, 600],
)
subprocess_cost = Histogram(
    "claude_subprocess_cost_usd",
    "Subprocess cost USD",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)
anomaly_score = Histogram(
    "anomaly_score", "Anomaly score distribution", buckets=[0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 1.0]
)

# Gauges
pool_size = Gauge("claude_pool_size", "Pool total size")
pool_in_use = Gauge("claude_pool_in_use", "Pool processes in use")
threads_active = Gauge("bot_threads_active", "Active bot threads")
bot_uptime = Gauge("bot_uptime_seconds", "Bot uptime in seconds")
queue_depth = Gauge("queue_depth_total", "Global queue depth")
host_disk_total = Gauge("host_disk_total_bytes", "Host root filesystem total bytes")
host_disk_used = Gauge("host_disk_used_bytes", "Host root filesystem used bytes")
host_disk_used_percent = Gauge("host_disk_used_percent", "Host root filesystem used percent")


def start_exporter(port: int = 9090) -> None:
    def app(environ, start_response):
        output = generate_latest(REGISTRY)
        status = "200 OK"
        headers = [("Content-Type", CONTENT_TYPE_LATEST)]
        start_response(status, headers)
        return [output]

    server = make_server("0.0.0.0", port, app)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    log.info("Prometheus metrics at :%d/metrics", port)
