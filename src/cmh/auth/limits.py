"""Single-replica, replaceable token buckets and bounded failed-auth auditing."""

import math
import threading


class RateLimits:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.credentials = {}
            self.failures = {}

    def credential(self, identity, capacity, now):
        seconds = now.timestamp()
        with self.lock:
            tokens, at = self.credentials.get(identity, (float(capacity), seconds))
            tokens = min(float(capacity), tokens + max(0, seconds - at) * capacity / 60)
            if tokens < 1:
                self.credentials[identity] = (tokens, seconds)
                return max(1, math.ceil((1 - tokens) * 60 / capacity))
            self.credentials[identity] = (tokens - 1, seconds)
        return 0

    def failure(self, ip, now):
        minute = int(now.timestamp()) // 60
        with self.lock:
            old, count, summarized = self.failures.get(ip, (minute, 0, False))
            if old != minute:
                count, summarized = 0, False
            count += 1
            summary = count > 30 and not summarized
            self.failures[ip] = (minute, count, summarized or summary)
            return count <= 30, summary
