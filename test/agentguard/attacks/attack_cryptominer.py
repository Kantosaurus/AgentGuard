#!/usr/bin/env python3
"""Attack: Cryptominer simulation — CPU-intensive work disguised as computation."""
import time, random, hashlib, os, multiprocessing

def mine_block(difficulty=5):
    """Simulate mining: find hash with N leading zeros."""
    prefix = "0" * difficulty
    nonce = 0
    while True:
        h = hashlib.sha256(f"block-{nonce}".encode()).hexdigest()
        if h.startswith(prefix):
            return nonce, h
        nonce += 1
        if nonce > 500000:
            return nonce, h

def run_miner_burst():
    """Short burst of high CPU — harder to detect than sustained load."""
    duration = random.uniform(10, 60)
    end = time.time() + duration
    while time.time() < end:
        mine_block(difficulty=random.randint(4, 6))

def run_miner_sustained():
    """Sustained low-level mining on one core."""
    mine_block(difficulty=7)

def run():
    print("[Attack] Cryptominer started")
    while True:
        mode = random.choice(["burst", "sustained"])
        if mode == "burst":
            run_miner_burst()
            time.sleep(random.uniform(30, 120))  # cool down
        else:
            run_miner_sustained()
            time.sleep(random.uniform(5, 30))

if __name__ == "__main__":
    run()
