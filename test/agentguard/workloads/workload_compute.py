#!/usr/bin/env python3
"""Workload: CPU-heavy tasks — compression, hashing, sorting, math."""
import time, random, hashlib, zlib, json, math

def run():
    while True:
        action = random.choice(["hash", "compress", "sort", "prime", "matrix"])
        try:
            if action == "hash":
                data = os.urandom(random.randint(1024, 1048576))
                for _ in range(random.randint(1, 10)):
                    hashlib.sha512(data).hexdigest()
            elif action == "compress":
                data = b"A" * random.randint(10000, 500000)
                zlib.compress(data, level=random.randint(1, 9))
            elif action == "sort":
                arr = [random.random() for _ in range(random.randint(10000, 100000))]
                sorted(arr)
            elif action == "prime":
                n = random.randint(100000, 500000)
                sieve = [True] * n
                for i in range(2, int(math.sqrt(n)) + 1):
                    if sieve[i]:
                        for j in range(i*i, n, i):
                            sieve[j] = False
            elif action == "matrix":
                size = random.randint(50, 200)
                a = [[random.random() for _ in range(size)] for _ in range(size)]
                b = [[random.random() for _ in range(size)] for _ in range(size)]
                # naive multiply (intentionally slow)
                for i in range(min(size, 50)):
                    for j in range(min(size, 50)):
                        sum(a[i][k] * b[k][j] for k in range(min(size, 50)))
        except Exception:
            pass
        time.sleep(random.uniform(1, 8))

import os
if __name__ == "__main__":
    print("[Workload] compute started")
    run()
