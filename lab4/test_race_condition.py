#!/usr/bin/env python3
"""
Test script to demonstrate race conditions in replication.
This script performs concurrent writes to the same key to show race conditions.
"""

import requests
import time
import concurrent.futures
import os
from typing import Dict, List
from collections import defaultdict

LEADER_URL = os.getenv('LEADER_URL', 'http://localhost:8080')
FOLLOWERS = [
    'http://localhost:8081',
    'http://localhost:8082',
    'http://localhost:8083',
    'http://localhost:8084',
    'http://localhost:8085'
]




def write_key(key: str, value: str, write_id: int):
    """Write a key-value pair and return the result."""
    try:
        start_time = time.time()
        response = requests.post(
            f"{LEADER_URL}/write",
            json={"key": key, "value": value},
            timeout=30
        )
        latency = (time.time() - start_time) * 1000
        
        if response.status_code == 200:
            data = response.json()
            return {
                "write_id": write_id,
                "success": True,
                "key": key,
                "value": value,
                "latency_ms": latency,
                "confirmations": data.get("confirmations", 0),
                "quorum_met": data.get("quorum_met", False),
                "timestamp": time.time()
            }
        else:
            return {
                "write_id": write_id,
                "success": False,
                "error": response.text,
                "timestamp": time.time()
            }
    except Exception as e:
        return {
            "write_id": write_id,
            "success": False,
            "error": str(e),
            "timestamp": time.time()
        }


def read_from_all(key: str) -> Dict[str, any]:
    """Read a key from leader and all followers simultaneously."""
    results = {}
    
    # Read from leader
    try:
        response = requests.get(f"{LEADER_URL}/read", params={"key": key}, timeout=2)
        if response.status_code == 200:
            results["leader"] = response.json()["value"]
        else:
            results["leader"] = f"ERROR: {response.status_code}"
    except Exception as e:
        results["leader"] = f"ERROR: {str(e)}"
    
    # Read from all followers concurrently
    def read_follower(follower_url):
        try:
            response = requests.get(f"{follower_url}/read", params={"key": key}, timeout=2)
            if response.status_code == 200:
                return follower_url.split(':')[-1], response.json()["value"]
            else:
                return follower_url.split(':')[-1], f"ERROR: {response.status_code}"
        except Exception as e:
            return follower_url.split(':')[-1], f"ERROR: {str(e)}"
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(FOLLOWERS)) as executor:
        futures = [executor.submit(read_follower, f) for f in FOLLOWERS]
        for future in concurrent.futures.as_completed(futures):
            follower_id, value = future.result()
            results[f"follower_{follower_id}"] = value
    
    return results


def demonstrate_race_condition():
    """Demonstrate race condition with concurrent writes to the same key."""
    print("\n=== Concurrent Write Race Condition Test ===\n")
    
    key = "race_test_key"
    num_concurrent_writes = 5
    
    print(f"Writing to key='{key}' {num_concurrent_writes} times concurrently...")
    start_time = time.time()
    
    write_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_concurrent_writes) as executor:
        futures = [
            executor.submit(write_key, key, f"value_{i}", i)
            for i in range(num_concurrent_writes)
        ]
        
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            write_results.append(result)
    
    # Sort by completion time
    write_results.sort(key=lambda x: x.get("timestamp", 0))
    
    print("\nWrite completion order:")
    for i, result in enumerate(write_results, 1):
        if result["success"]:
            print(f"  {i}. Write #{result['write_id']} (value='{result['value']}') - {result['latency_ms']:.1f}ms")
    
    # Read immediately to catch race condition
    time.sleep(0.5)
    read_results = read_from_all(key)
    
    print("\nValues in each node:")
    print(f"  Leader:     {read_results.get('leader', 'NOT FOUND')}")
    for i in range(1, 6):
        follower_key = f"follower_808{i}"
        print(f"  Follower {i}:  {read_results.get(follower_key, 'NOT FOUND')}")
    
    # Analyze
    all_values = set(read_results.values())
    unique_values = [v for v in all_values if not v.startswith("ERROR") and v != "NOT FOUND"]
    
    print(f"\nRace condition detected: {len(unique_values) > 1}")
    if len(unique_values) > 1:
        print(f"  Found {len(unique_values)} different values: {sorted(unique_values)}")
        print("\n  What this means:")
        print("    - We wrote 5 times to the same key concurrently:")
        for i in range(5):
            print(f"      • Write #{i} → value='value_{i}'")
        print(f"\n    - Different replicas ended up with different values:")
        for val in sorted(unique_values):
            write_id = val.split('_')[1] if '_' in val else '?'
            print(f"      • Some replicas have '{val}' (from Write #{write_id})")
        print("\n  Why this happens:")
        print("    - All writes started at the same time")
        print("    - Each write replicates to all followers")
        print("    - Network delays cause replications to arrive in different orders")
        print("    - Each replica stores the LAST value it receives")
        print("    - Result: Different replicas have different values!")
    else:
        print(f"  All replicas converged to: {unique_values[0] if unique_values else 'NONE'}")
        print("  (Race condition resolved - system reached eventual consistency)")


def demonstrate_replication_order():
    """Demonstrate the order of replication completion."""
    print("\n=== Replication Order Test ===\n")
    
    key = "order_test_key"
    value = "order_test_value"
    
    print(f"Writing key='{key}' with value='{value}'...")
    response = requests.post(
        f"{LEADER_URL}/write",
        json={"key": key, "value": value},
        timeout=30
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"\nWrite result:")
        print(f"  Confirmations: {data.get('confirmations', 0)}")
        print(f"  Latency: {data.get('latency_ms', 0):.2f}ms")
        print(f"  Quorum met: {data.get('quorum_met', False)}")
        print("\nCheck leader logs to see replication order:")
        print("  docker-compose logs -f leader | grep -E '\\[RACE\\]|\\[QUORUM\\]'")
        print("\n  Look for:")
        print("    - [RACE] Starting replication to 808X (all start at same time)")
        print("    - [QUORUM] Confirmation #X/5 (completion order - fastest first)")
    else:
        print(f"Write failed: {response.text}")


if __name__ == '__main__':
    print("Race Condition Test Suite")
    print("=" * 50)
    print("\n1. Replication Order Test")
    print("2. Concurrent Write Race Condition Test")
    print("3. Both tests")
    
    choice = input("\nChoice (1-3): ").strip()
    
    if choice == "1":
        demonstrate_replication_order()
    elif choice == "2":
        demonstrate_race_condition()
    else:
        demonstrate_replication_order()
        demonstrate_race_condition()
    
    print("\n" + "=" * 50)

