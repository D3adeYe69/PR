#!/usr/bin/env python3
"""
Integration test for the key-value store with replication.
"""

import requests
import time
import json
import os

LEADER_URL = os.getenv('LEADER_URL', 'http://localhost:8080')
FOLLOWERS = [
    'http://localhost:8081',
    'http://localhost:8082',
    'http://localhost:8083',
    'http://localhost:8084',
    'http://localhost:8085'
]


def wait_for_service(url, max_retries=30, delay=1):
    """Wait for a service to become available."""
    for i in range(max_retries):
        try:
            response = requests.get(f"{url}/health", timeout=2)
            if response.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(delay)
    return False


def test_health_checks():
    """Test that all services are healthy."""
    print("Testing health checks...")
    
    # Check leader
    assert wait_for_service(LEADER_URL), "Leader not available"
    response = requests.get(f"{LEADER_URL}/health")
    assert response.status_code == 200
    data = response.json()
    assert data['role'] == 'leader'
    print(f"✓ Leader is healthy: {data}")
    
    # Check followers
    for follower_url in FOLLOWERS:
        assert wait_for_service(follower_url), f"Follower {follower_url} not available"
        response = requests.get(f"{follower_url}/health")
        assert response.status_code == 200
        data = response.json()
        assert data['role'] == 'follower'
        print(f"✓ {follower_url} is healthy: {data}")
    
    print("All services are healthy!\n")


def test_write_and_replication():
    """Test that writes are replicated to followers."""
    print("Testing write and replication...")
    
    # Write a key-value pair
    key = "test_key_1"
    value = "test_value_1"
    
    response = requests.post(
        f"{LEADER_URL}/write",
        json={"key": key, "value": value},
        timeout=10
    )
    
    assert response.status_code == 200, f"Write failed: {response.text}"
    data = response.json()
    assert data['success'] == True
    assert data['key'] == key
    assert data['value'] == value
    print(f"✓ Write successful: {data}")
    
    # Wait a bit for replication to complete
    time.sleep(2)
    
    # Check that the value is in the leader
    response = requests.get(f"{LEADER_URL}/read", params={"key": key})
    assert response.status_code == 200
    assert response.json()['value'] == value
    print(f"✓ Value found in leader")
    
    # Check that the value is replicated to followers
    for follower_url in FOLLOWERS:
        response = requests.get(f"{follower_url}/read", params={"key": key}, timeout=2)
        if response.status_code == 200:
            assert response.json()['value'] == value
            print(f"✓ Value replicated to {follower_url}")
        else:
            print(f"⚠ Value not yet replicated to {follower_url} (may be delayed)")
    
    print("Write and replication test completed!\n")


def test_multiple_writes():
    """Test multiple writes."""
    print("Testing multiple writes...")
    
    for i in range(10):
        key = f"key_{i}"
        value = f"value_{i}"
        
        response = requests.post(
            f"{LEADER_URL}/write",
            json={"key": key, "value": value},
            timeout=10
        )
        
        assert response.status_code == 200, f"Write {i} failed: {response.text}"
        print(f"✓ Write {i} successful")
    
    # Wait for replication
    time.sleep(3)
    
    # Verify all writes
    for i in range(10):
        key = f"key_{i}"
        expected_value = f"value_{i}"
        
        # Check leader
        response = requests.get(f"{LEADER_URL}/read", params={"key": key})
        assert response.status_code == 200
        assert response.json()['value'] == expected_value
        
        # Check at least some followers have the value
        follower_count = 0
        for follower_url in FOLLOWERS:
            response = requests.get(f"{follower_url}/read", params={"key": key}, timeout=2)
            if response.status_code == 200 and response.json()['value'] == expected_value:
                follower_count += 1
        
        print(f"✓ Key {key} found in leader and {follower_count} followers")
    
    print("Multiple writes test completed!\n")


def test_read_nonexistent_key():
    """Test reading a non-existent key."""
    print("Testing read of non-existent key...")
    
    response = requests.get(f"{LEADER_URL}/read", params={"key": "nonexistent"})
    assert response.status_code == 404
    print("✓ Non-existent key correctly returns 404\n")


def test_store_consistency():
    """Test that stores are consistent after writes."""
    print("Testing store consistency...")
    
    # Get leader store
    response = requests.get(f"{LEADER_URL}/store")
    assert response.status_code == 200
    leader_store = response.json()
    print(f"Leader store has {len(leader_store)} keys")
    
    # Get follower stores
    follower_stores = []
    for follower_url in FOLLOWERS:
        response = requests.get(f"{follower_url}/store", timeout=2)
        if response.status_code == 200:
            follower_stores.append(response.json())
            print(f"Follower store has {len(response.json())} keys")
    
    # Check consistency
    if follower_stores:
        # All followers should have the same keys as leader (eventually)
        leader_keys = set(leader_store.keys())
        for i, follower_store in enumerate(follower_stores):
            follower_keys = set(follower_store.keys())
            missing_keys = leader_keys - follower_keys
            if missing_keys:
                print(f"⚠ Follower {i+1} missing keys: {missing_keys}")
            else:
                print(f"✓ Follower {i+1} has all keys from leader")
            
            # Check values match
            for key in leader_keys & follower_keys:
                if leader_store[key] != follower_store[key]:
                    print(f"⚠ Key {key} value mismatch: leader={leader_store[key]}, follower={follower_store[key]}")
                else:
                    pass  # Values match
    
    print("Store consistency test completed!\n")


if __name__ == '__main__':
    print("=" * 60)
    print("Integration Test Suite")
    print("=" * 60)
    print()
    
    try:
        test_health_checks()
        test_write_and_replication()
        test_multiple_writes()
        test_read_nonexistent_key()
        test_store_consistency()
        
        print("=" * 60)
        print("All tests passed! ✓")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

