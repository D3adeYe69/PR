#!/usr/bin/env python3
"""
Automated script to test different write quorum values.
This script automatically updates docker-compose.yml and restarts the leader.
"""

import requests
import time
import concurrent.futures
import os
import json
import matplotlib.pyplot as plt
import numpy as np
import subprocess
import sys
import re
from collections import defaultdict

LEADER_URL = os.getenv('LEADER_URL', 'http://localhost:8080')
NUM_WRITES = 100
CONCURRENT_WRITES = 10
NUM_KEYS = 10
DOCKER_COMPOSE_FILE = 'docker-compose.yml'


def wait_for_leader(max_retries=30, delay=1):
    """Wait for leader to become available."""
    for i in range(max_retries):
        try:
            response = requests.get(f"{LEADER_URL}/health", timeout=2)
            if response.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(delay)
    return False


def update_quorum_in_docker_compose(quorum_value):
    """Update WRITE_QUORUM in docker-compose.yml."""
    try:
        with open(DOCKER_COMPOSE_FILE, 'r') as f:
            content = f.read()
        
        # Replace WRITE_QUORUM value
        pattern = r'WRITE_QUORUM=\d+'
        replacement = f'WRITE_QUORUM={quorum_value}'
        new_content = re.sub(pattern, replacement, content)
        
        with open(DOCKER_COMPOSE_FILE, 'w') as f:
            f.write(new_content)
        
        print(f"✓ Updated docker-compose.yml: WRITE_QUORUM={quorum_value}")
        return True
    except Exception as e:
        print(f"✗ Error updating docker-compose.yml: {e}")
        return False


def restart_leader():
    """Recreate the leader container to pick up new environment variables."""
    try:
        print("  Recreating leader container (to pick up new WRITE_QUORUM)...")
        # Stop and remove the container, then recreate it
        result = subprocess.run(
            ['docker-compose', 'up', '-d', '--force-recreate', '--no-deps', 'leader'],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            print("  ✓ Leader recreated")
            # Wait for leader to be ready
            print("  Waiting for leader to be ready...")
            time.sleep(8)  # Give it more time to start
            if wait_for_leader(max_retries=40, delay=1):
                # Verify the quorum value was actually updated
                try:
                    response = requests.get(f"{LEADER_URL}/health", timeout=5)
                    if response.status_code == 200:
                        health_data = response.json()
                        actual_quorum = health_data.get('write_quorum', 'unknown')
                        print(f"  ✓ Leader is ready (WRITE_QUORUM={actual_quorum})")
                        return True
                except:
                    pass
                print("  ✓ Leader is ready")
                return True
            else:
                print("  ✗ Leader not responding after recreate")
                return False
        else:
            print(f"  ✗ Error recreating leader: {result.stderr}")
            if result.stdout:
                print(f"  stdout: {result.stdout}")
            return False
    except Exception as e:
        print(f"  ✗ Error recreating leader: {e}")
        return False


def write_key(key, value):
    """Write a single key-value pair and return latency."""
    try:
        start_time = time.time()
        response = requests.post(
            f"{LEADER_URL}/write",
            json={"key": key, "value": value},
            timeout=30
        )
        latency = (time.time() - start_time) * 1000  # Convert to ms
        
        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "latency_ms": latency,
                "confirmations": data.get("confirmations", 0),
                "quorum_met": data.get("quorum_met", True)
            }
        else:
            return {
                "success": False,
                "latency_ms": latency,
                "error": response.text
            }
    except Exception as e:
        return {
            "success": False,
            "latency_ms": 0,
            "error": str(e)
        }


def run_writes_batch(keys_and_values, concurrent_count):
    """Run writes in batches with specified concurrency."""
    results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_count) as executor:
        futures = [
            executor.submit(write_key, key, value)
            for key, value in keys_and_values
        ]
        
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    
    return results


def test_write_quorum(quorum_value):
    """Test writes with a specific write quorum value."""
    print(f"\n{'='*60}")
    print(f"Testing with WRITE_QUORUM={quorum_value}")
    print(f"{'='*60}")
    
    # Verify the quorum value is actually set correctly
    try:
        response = requests.get(f"{LEADER_URL}/health", timeout=5)
        if response.status_code == 200:
            health_data = response.json()
            actual_quorum = health_data.get('write_quorum', 'unknown')
            if actual_quorum != quorum_value:
                print(f"⚠ WARNING: Expected quorum {quorum_value}, but leader reports {actual_quorum}")
                print("  The test may not be accurate. Try recreating the container.")
            else:
                print(f"✓ Verified: Leader has WRITE_QUORUM={actual_quorum}")
    except Exception as e:
        print(f"⚠ Could not verify quorum value: {e}")
    
    # Generate keys and values
    keys_and_values = []
    for i in range(NUM_WRITES):
        key = f"perf_key_{i % NUM_KEYS}"  # Cycle through 10 keys
        value = f"perf_value_{i}_{quorum_value}_{int(time.time())}"
        keys_and_values.append((key, value))
    
    # Run writes in batches
    all_results = []
    print(f"Running {NUM_WRITES} writes in batches of {CONCURRENT_WRITES}...")
    
    for batch_start in range(0, NUM_WRITES, CONCURRENT_WRITES):
        batch = keys_and_values[batch_start:batch_start + CONCURRENT_WRITES]
        batch_results = run_writes_batch(batch, CONCURRENT_WRITES)
        all_results.extend(batch_results)
        
        successful = sum(1 for r in batch_results if r['success'])
        quorum_met_count = sum(1 for r in batch_results if r.get('quorum_met', False))
        print(f"  Batch {batch_start // CONCURRENT_WRITES + 1}: "
              f"{successful}/{len(batch_results)} successful, "
              f"{quorum_met_count} met quorum")
    
    # Calculate statistics
    successful_results = [r for r in all_results if r['success']]
    latencies = [r['latency_ms'] for r in successful_results]
    quorum_met_results = [r for r in successful_results if r.get('quorum_met', False)]
    quorum_met_latencies = [r['latency_ms'] for r in quorum_met_results]
    
    if latencies:
        avg_latency = np.mean(latencies)
        median_latency = np.median(latencies)
        min_latency = np.min(latencies)
        max_latency = np.max(latencies)
        std_latency = np.std(latencies)
        
        if quorum_met_latencies:
            avg_quorum_latency = np.mean(quorum_met_latencies)
        else:
            avg_quorum_latency = avg_latency
        
        print(f"\nResults for WRITE_QUORUM={quorum_value}:")
        print(f"  Successful writes: {len(successful_results)}/{NUM_WRITES}")
        print(f"  Writes that met quorum: {len(quorum_met_results)}/{NUM_WRITES}")
        print(f"  Average latency (all): {avg_latency:.2f} ms")
        # Calculate percentiles
        p95_latency = np.percentile(quorum_met_latencies if quorum_met_latencies else latencies, 95)
        p99_latency = np.percentile(quorum_met_latencies if quorum_met_latencies else latencies, 99)
        
        print(f"  Average latency (quorum met): {avg_quorum_latency:.2f} ms")
        print(f"  Median latency: {median_latency:.2f} ms")
        print(f"  P95 latency: {p95_latency:.2f} ms (95% of requests faster)")
        print(f"  P99 latency: {p99_latency:.2f} ms (99% of requests faster)")
        print(f"  Min latency: {min_latency:.2f} ms")
        print(f"  Max latency: {max_latency:.2f} ms")
        print(f"  Std deviation: {std_latency:.2f} ms")
        
        # Calculate percentiles
        p95_latency = np.percentile(quorum_met_latencies if quorum_met_latencies else latencies, 95)
        p99_latency = np.percentile(quorum_met_latencies if quorum_met_latencies else latencies, 99)
        
        return {
            "quorum": quorum_value,
            "avg_latency": avg_quorum_latency,  # Use quorum-met latency for comparison
            "median_latency": median_latency,
            "p95_latency": p95_latency,
            "p99_latency": p99_latency,
            "min_latency": min_latency,
            "max_latency": max_latency,
            "std_latency": std_latency,
            "success_rate": len(successful_results) / NUM_WRITES,
            "quorum_met_rate": len(quorum_met_results) / NUM_WRITES,
            "latencies": quorum_met_latencies if quorum_met_latencies else latencies
        }
    else:
        print(f"  No successful writes!")
        return None


def demonstrate_race_condition_in_quorum_test():
    """Demonstrate race condition by writing to same key concurrently."""
    print("\nTesting race condition: 5 concurrent writes to the SAME key...")
    
    key = "race_demo_key"
    num_writes = 5
    
    # Perform concurrent writes to the SAME key
    def write_same_key(write_id):
        try:
            response = requests.post(
                f"{LEADER_URL}/write",
                json={"key": key, "value": f"value_{write_id}"},
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "write_id": write_id,
                    "success": True,
                    "value": f"value_{write_id}",
                    "latency_ms": data.get("latency_ms", 0),
                    "timestamp": time.time()
                }
            return {"write_id": write_id, "success": False}
        except Exception as e:
            return {"write_id": write_id, "success": False, "error": str(e)}
    
    # Start all writes concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_writes) as executor:
        futures = [executor.submit(write_same_key, i) for i in range(num_writes)]
        write_results = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    write_results.sort(key=lambda x: x.get("timestamp", 0))
    
    print(f"\nWrite completion order:")
    for i, result in enumerate(write_results, 1):
        if result["success"]:
            print(f"  {i}. Write #{result['write_id']} (value='{result['value']}') - {result['latency_ms']:.1f}ms")
    
    # Read immediately from all nodes (before all replications complete)
    print("\nReading from all nodes IMMEDIATELY (to catch race condition)...")
    time.sleep(0.3)  # Small delay to let some replications happen
    
    def read_node(url, node_name):
        try:
            response = requests.get(f"{url}/read", params={"key": key}, timeout=2)
            if response.status_code == 200:
                return node_name, response.json()["value"]
            return node_name, "NOT_FOUND"
        except:
            return node_name, "ERROR"
    
    followers = [
        ('http://localhost:8081', 'Follower1'),
        ('http://localhost:8082', 'Follower2'),
        ('http://localhost:8083', 'Follower3'),
        ('http://localhost:8084', 'Follower4'),
        ('http://localhost:8085', 'Follower5')
    ]
    
    # Read from leader
    leader_value = read_node(LEADER_URL, 'Leader')[1]
    
    # Read from all followers concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(followers)) as executor:
        futures = [executor.submit(read_node, url, name) for url, name in followers]
        follower_values = dict(f.result() for f in concurrent.futures.as_completed(futures))
    
    print("\nValues found in each node:")
    print(f"  Leader:    {leader_value}")
    for name in ['Follower1', 'Follower2', 'Follower3', 'Follower4', 'Follower5']:
        print(f"  {name}:  {follower_values.get(name, 'ERROR')}")
    
    # Check for race condition
    all_values = {leader_value} | set(follower_values.values())
    unique_values = [v for v in all_values if v not in ["NOT_FOUND", "ERROR"]]
    
    print(f"\nRace condition detected: {len(unique_values) > 1}")
    if len(unique_values) > 1:
        print(f"  ✓ Found {len(unique_values)} different values: {sorted(unique_values)}")
        print("\n  What this means:")
        print("    - We wrote 5 times to the same key concurrently:")
        print("      • Write #0 → value='value_0'")
        print("      • Write #1 → value='value_1'")
        print("      • Write #2 → value='value_2'")
        print("      • Write #3 → value='value_3'")
        print("      • Write #4 → value='value_4'")
        print(f"\n    - Different replicas ended up with different values:")
        for val in sorted(unique_values):
            write_id = val.split('_')[1] if '_' in val else '?'
            print(f"      • Some replicas have '{val}' (from Write #{write_id})")
        print("\n  Why this happens:")
        print("    - All 5 writes started at the same time")
        print("    - Each write replicates to all 5 followers (15 total replications)")
        print("    - Each follower receives ALL 5 writes, but in DIFFERENT orders")
        print("    - Network delays (0-1000ms) cause different arrival orders")
        print("    - Each replica stores the LAST value it receives (overwrites previous)")
        print("    - Example: Follower1 might get #2→#0→#4→#1→#3 (stores value_3)")
        print("              Follower2 might get #1→#4→#0→#3→#2 (stores value_2)")
        print("    - Result: Different replicas have different final values!")
    else:
        print(f"  All replicas converged to: {unique_values[0] if unique_values else 'NONE'}")
        print("  (Race condition resolved - try reading faster or increase delays)")


def check_data_consistency():
    """Check if data in all replicas matches the leader after all writes."""
    print("\n" + "=" * 60)
    print("Checking Data Consistency (Replication Verification)")
    print("=" * 60)
    
    # Get leader store
    try:
        response = requests.get(f"{LEADER_URL}/store", timeout=10)
        if response.status_code == 200:
            leader_store = response.json()
            print(f"Leader store has {len(leader_store)} keys")
        else:
            print(f"✗ Failed to get leader store: {response.status_code}")
            return None
    except Exception as e:
        print(f"✗ Error getting leader store: {e}")
        return None
    
    # Filter to only check keys from our performance tests
    # We only care about keys that start with "perf_key_"
    test_keys = {k: v for k, v in leader_store.items() if k.startswith("perf_key_")}
    if not test_keys:
        print("⚠ No test keys found in leader store")
        return None
    
    print(f"Found {len(test_keys)} test keys to verify")
    
    # Get follower stores
    followers = [
        'http://localhost:8081',
        'http://localhost:8082',
        'http://localhost:8083',
        'http://localhost:8084',
        'http://localhost:8085'
    ]
    
    follower_stores = []
    for follower_url in followers:
        try:
            response = requests.get(f"{follower_url}/store", timeout=5)
            if response.status_code == 200:
                follower_stores.append((follower_url, response.json()))
            else:
                print(f"⚠ Could not get store from {follower_url}: {response.status_code}")
        except Exception as e:
            print(f"⚠ Error getting {follower_url} store: {e}")
    
    if not follower_stores:
        print("✗ No follower stores available for comparison")
        return None
    
    # Compare stores - only check test keys
    leader_keys = set(test_keys.keys())
    print(f"\nChecking {len(leader_keys)} test keys across {len(follower_stores)} followers...\n")
    
    consistency_summary = {
        "total_keys": len(leader_keys),
        "followers_checked": len(follower_stores),
        "fully_consistent": 0,
        "missing_keys_total": 0,
        "value_mismatches_total": 0,
        "follower_details": []
    }
    
    all_consistent = True
    
    for follower_url, follower_store in follower_stores:
        follower_keys = set(follower_store.keys())
        missing_keys = leader_keys - follower_keys
        extra_keys = follower_keys - leader_keys
        
        # Check value consistency - only for test keys
        test_keys_in_follower = {k: v for k, v in follower_store.items() if k.startswith("perf_key_")}
        common_keys = leader_keys & set(test_keys_in_follower.keys())
        mismatches = []
        for key in common_keys:
            if test_keys[key] != test_keys_in_follower[key]:
                mismatches.append(key)
        
        follower_id = follower_url.split(':')[-1]  # Extract port number
        # Only check test keys - ignore extra non-test keys
        test_extra_keys = {k for k in extra_keys if k.startswith("perf_key_")}
        is_consistent = len(missing_keys) == 0 and len(mismatches) == 0 and len(test_extra_keys) == 0
        
        if is_consistent:
            consistency_summary["fully_consistent"] += 1
            print(f"✓ Follower {follower_id}: Fully consistent ({len(common_keys)} keys match)")
        else:
            all_consistent = False
            consistency_summary["missing_keys_total"] += len(missing_keys)
            consistency_summary["value_mismatches_total"] += len(mismatches)
            print(f"✗ Follower {follower_id}: Issues found")
            if missing_keys:
                print(f"  - Missing {len(missing_keys)} keys: {list(missing_keys)[:5]}{'...' if len(missing_keys) > 5 else ''}")
            if mismatches:
                print(f"  - {len(mismatches)} value mismatches: {mismatches[:3]}{'...' if len(mismatches) > 3 else ''}")
            test_extra_keys = {k for k in extra_keys if k.startswith("perf_key_")}
            if test_extra_keys:
                print(f"  - {len(test_extra_keys)} extra test keys (unexpected): {list(test_extra_keys)[:3]}{'...' if len(test_extra_keys) > 3 else ''}")
        
        consistency_summary["follower_details"].append({
            "follower": follower_id,
            "keys": len(follower_keys),
            "missing": len(missing_keys),
            "mismatches": len(mismatches),
            "consistent": is_consistent
        })
    
    # Print summary
    print("\n" + "-" * 60)
    print("Replication Summary")
    print("-" * 60)
    print(f"Total keys written: {consistency_summary['total_keys']}")
    print(f"Fully consistent followers: {consistency_summary['fully_consistent']}/{consistency_summary['followers_checked']}")
    
    if consistency_summary['missing_keys_total'] > 0:
        print(f"⚠ Total missing keys across followers: {consistency_summary['missing_keys_total']}")
    if consistency_summary['value_mismatches_total'] > 0:
        print(f"⚠ Total value mismatches: {consistency_summary['value_mismatches_total']}")
    
    if all_consistent:
        print("\n✓ All followers have successfully replicated all data from the leader!")
        print("  Note: In a real distributed system with concurrent writes, race conditions")
        print("  and replication conflicts are expected and demonstrate eventual consistency.")
    else:
        print("\n⚠ Some followers are missing data or have mismatches.")
        print("  This is EXPECTED and demonstrates:")
        print("  - Race conditions in concurrent replication")
        print("  - Replication conflicts (as described in the book)")
        print("  - Eventual consistency (data will eventually become consistent)")
        print("  - The challenges of maintaining consistency in distributed systems")
    
    return consistency_summary


def plot_results(results):
    """Plot write quorum vs latency metrics (mean, median, p95, p99)."""
    if not results:
        print("No results to plot")
        return
    
    valid_results = [r for r in results if r is not None]
    if not valid_results:
        print("No valid results to plot")
        return
    
    quorums = [r['quorum'] for r in valid_results]
    mean_latencies = [r['avg_latency'] / 1000.0 for r in valid_results]  # Convert to seconds
    median_latencies = [r['median_latency'] / 1000.0 for r in valid_results]
    p95_latencies = [r['p95_latency'] / 1000.0 for r in valid_results]
    p99_latencies = [r['p99_latency'] / 1000.0 for r in valid_results]
    
    plt.figure(figsize=(12, 8))
    
    # Main plot with all metrics
    plt.plot(quorums, mean_latencies, 'o-', linewidth=2, markersize=8, color='#2E86AB', label='mean')
    plt.plot(quorums, median_latencies, 's-', linewidth=2, markersize=8, color='#FF6B35', label='median')
    plt.plot(quorums, p95_latencies, '^-', linewidth=2, markersize=8, color='#4ECDC4', label='p95')
    plt.plot(quorums, p99_latencies, 'd-', linewidth=2, markersize=8, color='#FFE66D', label='p99')
    
    plt.xlabel('Quorum value', fontsize=12)
    plt.ylabel('Latency (s)', fontsize=12)
    plt.title('Quorum vs. Latency, random delay in range [0, 1000ms]', fontsize=14, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.xticks(quorums, labels=[f'Q={q}' for q in quorums])
    plt.legend(loc='upper left', fontsize=10)
    plt.ylim(bottom=0)
    
    plt.tight_layout()
    plt.savefig('write_quorum_vs_latency.png', dpi=300, bbox_inches='tight')
    print(f"\nPlot saved to write_quorum_vs_latency.png")
    plt.close()


def main():
    """Main function to run performance analysis for all quorum values."""
    print("=" * 60)
    print("Automated Performance Analysis - Testing Write Quorum Values 1-5")
    print("=" * 60)
    print(f"Total writes per quorum value: {NUM_WRITES}")
    print(f"Concurrent writes per batch: {CONCURRENT_WRITES}")
    print(f"Number of keys: {NUM_KEYS}")
    print()
    print("This script will:")
    print("  1. Update WRITE_QUORUM in docker-compose.yml")
    print("  2. Restart the leader container")
    print("  3. Run performance tests")
    print("  4. Repeat for each quorum value (1-5)")
    print()
    
    # Check if docker-compose is available
    try:
        subprocess.run(['docker-compose', '--version'], capture_output=True, check=True)
    except:
        print("Error: docker-compose not found. Please install docker-compose.")
        return
    
    # Wait for initial leader
    if not wait_for_leader():
        print("Error: Leader not available. Make sure docker-compose is running.")
        print("Run: docker-compose up -d")
        return
    
    print("Initial leader check: ✓\n")
    
    all_results = []
    quorum_values = [1, 2, 3, 4, 5]
    
    for quorum in quorum_values:
        print(f"\n{'='*60}")
        print(f"Testing quorum value: {quorum}")
        print(f"{'='*60}")
        
        # Update docker-compose.yml
        if not update_quorum_in_docker_compose(quorum):
            print(f"Failed to update docker-compose.yml for quorum {quorum}, skipping...")
            continue
        
        # Restart leader
        if not restart_leader():
            print(f"Failed to restart leader for quorum {quorum}, skipping...")
            continue
        
        # Run test
        result = test_write_quorum(quorum)
        if result:
            all_results.append(result)
        
        # Wait a bit between tests
        time.sleep(2)
    
    # Plot results
    if all_results:
        plot_results(all_results)
        
        # Print summary
        print("\n" + "=" * 60)
        print("Performance Summary")
        print("=" * 60)
        for result in all_results:
            print(f"Quorum {result['quorum']}: "
                  f"Mean = {result['avg_latency']:.2f}ms, "
                  f"Median = {result['median_latency']:.2f}ms, "
                  f"P95 = {result['p95_latency']:.2f}ms, "
                  f"P99 = {result['p99_latency']:.2f}ms")
    
    # Check data consistency after all tests
    print("\nWaiting for final replications to complete...")
    time.sleep(10)  # Give more time for background replications (especially from Q=1)
    
    consistency = check_data_consistency()
    
    # Demonstrate race condition with concurrent writes to same key
    print("\n" + "=" * 60)
    print("Race Condition Demonstration")
    print("=" * 60)
    demonstrate_race_condition_in_quorum_test()
    
    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
    


if __name__ == '__main__':
    main()

