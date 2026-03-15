#!/usr/bin/env python3
"""Workload: Network activity — HTTP requests, DNS lookups, API calls."""
import time, random, socket, urllib.request, json

TARGETS = [
    "http://httpbin.org/get",
    "http://httpbin.org/ip",
    "http://httpbin.org/headers",
    "http://httpbin.org/user-agent",
    "http://example.com",
    "http://jsonplaceholder.typicode.com/posts/1",
    "http://jsonplaceholder.typicode.com/users/1",
    "http://jsonplaceholder.typicode.com/todos/1",
    "http://worldtimeapi.org/api/timezone/Etc/UTC",
]

DNS_TARGETS = ["google.com", "github.com", "python.org", "stackoverflow.com", "wikipedia.org", "example.com"]

def run():
    while True:
        action = random.choice(["http_get", "dns_lookup", "socket_connect"])
        try:
            if action == "http_get":
                url = random.choice(TARGETS)
                req = urllib.request.urlopen(url, timeout=10)
                req.read()
                req.close()
            elif action == "dns_lookup":
                host = random.choice(DNS_TARGETS)
                socket.getaddrinfo(host, 443)
            elif action == "socket_connect":
                host = random.choice(DNS_TARGETS)
                s = socket.create_connection((host, 443), timeout=5)
                s.close()
        except Exception:
            pass
        time.sleep(random.uniform(1, 5))

if __name__ == "__main__":
    print("[Workload] network started")
    run()
