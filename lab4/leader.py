#!/usr/bin/env python3
"""
Leader server for key-value store with semi-synchronous replication.
Only the leader accepts writes and replicates them to followers.
"""

import os
import time
import random
import asyncio
import aiohttp
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# In-memory key-value store
store = {}

# Configuration from environment variables
FOLLOWERS = os.getenv('FOLLOWERS', '').split(',')
FOLLOWERS = [f.strip() for f in FOLLOWERS if f.strip()]
WRITE_QUORUM = int(os.getenv('WRITE_QUORUM', '3'))
MIN_DELAY = int(os.getenv('MIN_DELAY', '0'))
MAX_DELAY = int(os.getenv('MAX_DELAY', '1000'))

logger.info(f"Leader initialized with {len(FOLLOWERS)} followers: {FOLLOWERS}")
logger.info(f"Write quorum: {WRITE_QUORUM}, Delay range: [{MIN_DELAY}, {MAX_DELAY}]ms")


# Pydantic models for request/response
class WriteRequest(BaseModel):
    key: str
    value: str


class WriteResponse(BaseModel):
    success: bool
    key: str
    value: str
    confirmations: int
    quorum_met: bool
    latency_ms: float
    replication_results: list


async def replicate_to_follower(follower_url: str, key: str, value: str, delay_ms: int) -> Dict[str, Any]:
    """Replicate a key-value pair to a single follower with delay.
    
    Returns a coroutine that, when awaited, returns a dict with replication result.
    The delay simulates network latency and processing time.
    """
    start_time = time.time()
    follower_id = follower_url.split(':')[-1] if ':' in follower_url else follower_url
    
    # Log when replication starts (shows race condition - all start concurrently)
    logger.info(f"[RACE] Starting replication to {follower_id} for key='{key}' with delay={delay_ms}ms")
    
    # Apply delay BEFORE network call to simulate network latency
    # This creates visible race conditions as different followers respond at different times
    await asyncio.sleep(delay_ms / 1000.0)  # Convert ms to seconds
    
    elapsed_before_network = (time.time() - start_time) * 1000
    
    try:
        async with aiohttp.ClientSession() as session:
            network_start = time.time()
            async with session.post(
                f"{follower_url}/replicate",
                json={"key": key, "value": value},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                network_time = (time.time() - network_start) * 1000
                total_time = (time.time() - start_time) * 1000
                
                if response.status == 200:
                    result = await response.json()
                    logger.info(
                        f"[RACE] ✓ {follower_id} confirmed key='{key}' "
                        f"(delay={delay_ms}ms, network={network_time:.1f}ms, total={total_time:.1f}ms)"
                    )
                    return {
                        "success": True,
                        "follower": follower_url,
                        "follower_id": follower_id,
                        "result": result,
                        "delay_ms": delay_ms,
                        "total_time_ms": total_time,
                        "timestamp": time.time()
                    }
                else:
                    logger.warning(f"[RACE] ✗ {follower_id} failed for key='{key}': Status {response.status}")
                    return {"success": False, "follower": follower_url, "follower_id": follower_id, "error": f"Status {response.status}"}
    except asyncio.TimeoutError:
        total_time = (time.time() - start_time) * 1000
        logger.warning(f"[RACE] ✗ {follower_id} timeout for key='{key}' after {total_time:.1f}ms")
        return {"success": False, "follower": follower_url, "follower_id": follower_id, "error": "Timeout"}
    except Exception as e:
        total_time = (time.time() - start_time) * 1000
        logger.error(f"[RACE] ✗ {follower_id} error for key='{key}': {e}")
        return {"success": False, "follower": follower_url, "follower_id": follower_id, "error": str(e)}


@app.post("/write", response_model=WriteResponse)
async def write(request: WriteRequest):
    """Write endpoint - only leader accepts writes."""
    try:
        key = request.key
        value = request.value
        
        start_time = time.time()
        
        # Write to local store (leader always writes locally first)
        store[key] = value
        
        # Calculate how many follower confirmations we need
        # WRITE_QUORUM represents the number of follower confirmations needed
        # Total confirmations = WRITE_QUORUM followers + 1 leader
        # For example: WRITE_QUORUM=5 means 5 followers + 1 leader = 6 total
        required_follower_confirmations = WRITE_QUORUM
        
        # Check if we have enough followers
        if not FOLLOWERS:
            # No followers available, only leader confirms
            latency = (time.time() - start_time) * 1000
            quorum_met = (WRITE_QUORUM == 0)  # Only met if quorum is 0
            total_confirmations = 1
            replication_results = []
        elif required_follower_confirmations == 0:
            # Q=0: Only leader confirms, return immediately (no network wait)
            latency = (time.time() - start_time) * 1000
            quorum_met = True
            total_confirmations = 1
            replication_results = []
            
            # Still replicate to followers in background (don't wait)
            delays = [random.randint(MIN_DELAY, MAX_DELAY) for _ in FOLLOWERS]
            for follower, delay in zip(FOLLOWERS, delays):
                asyncio.create_task(replicate_to_follower(follower, key, value, delay))
        elif required_follower_confirmations > len(FOLLOWERS):
            # Can't meet quorum - not enough followers
            logger.warning(
                f"[QUORUM] Cannot meet quorum {WRITE_QUORUM}: only {len(FOLLOWERS)} followers available"
            )
            latency = (time.time() - start_time) * 1000
            quorum_met = False
            total_confirmations = 1  # Only leader
            replication_results = []
            
            # Still try to replicate to all followers
            delays = [random.randint(MIN_DELAY, MAX_DELAY) for _ in FOLLOWERS]
            tasks = [
                asyncio.create_task(replicate_to_follower(follower, key, value, delay))
                for follower, delay in zip(FOLLOWERS, delays)
            ]
            # Wait for all (but quorum won't be met)
            for coro in asyncio.as_completed(tasks):
                try:
                    result = await coro
                    replication_results.append(result)
                except Exception as e:
                    replication_results.append({"success": False, "error": str(e)})
        else:
            # Q>=1: Need to wait for follower confirmations
            # Generate random delays for each follower (this creates race conditions)
            delays = [random.randint(MIN_DELAY, MAX_DELAY) for _ in FOLLOWERS]
            
            logger.info(
                f"[QUORUM] Write key='{key}': Need {required_follower_confirmations} follower confirmations "
                f"(quorum={WRITE_QUORUM} followers + 1 leader = {required_follower_confirmations + 1} total). "
                f"Delays: {dict(zip([f.split(':')[-1] for f in FOLLOWERS], delays))}"
            )
            
            # Start replication to all followers concurrently
            # This creates a race condition - all followers start at the same time
            # but finish at different times based on their delays
            tasks = [
                asyncio.create_task(replicate_to_follower(follower, key, value, delay))
                for follower, delay in zip(FOLLOWERS, delays)
            ]
            
            # Wait for enough confirmations (semi-synchronous)
            replication_results = []
            successful_count = 0
            quorum_met = False
            
            # Process results as they complete
            # asyncio.as_completed returns tasks in order of completion (fastest first)
            # This shows the race condition - fastest followers respond first
            responses_received = 0
            completion_order = []
            
            for coro in asyncio.as_completed(tasks):
                try:
                    result = await coro
                    responses_received += 1
                    replication_results.append(result)
                    
                    if result.get('success', False):
                        successful_count += 1
                        follower_id = result.get('follower_id', 'unknown')
                        completion_order.append(follower_id)
                        logger.info(
                            f"[QUORUM] Confirmation #{successful_count}/{required_follower_confirmations} "
                            f"from {follower_id} (order: {completion_order})"
                        )
                    
                    # Check if we have enough confirmations
                    # We need WRITE_QUORUM successful follower responses (leader already counted)
                    if successful_count >= required_follower_confirmations:
                        # Quorum met! Record latency NOW and return
                        latency = (time.time() - start_time) * 1000
                        quorum_met = True
                        total_confirmations = successful_count + 1  # +1 for leader
                        
                        logger.info(
                            f"[QUORUM] ✓ Quorum MET: {successful_count} followers + 1 leader = "
                            f"{total_confirmations} total confirmations (required: {WRITE_QUORUM} followers + 1 leader). "
                            f"Latency={latency:.2f}ms. "
                            f"Completion order: {completion_order} "
                            f"({responses_received}/{len(FOLLOWERS)} responses received)"
                        )
                        
                        # Don't wait for remaining - return immediately
                        # (remaining tasks will complete in background, showing race condition)
                        break
                except Exception as e:
                    responses_received += 1
                    replication_results.append({"success": False, "error": str(e)})
                    logger.error(f"[QUORUM] Error processing replication result: {e}")
            
            # If we didn't meet quorum (shouldn't happen with enough followers)
            if not quorum_met:
                latency = (time.time() - start_time) * 1000
                total_confirmations = successful_count + 1  # +1 for leader
                quorum_met = successful_count >= required_follower_confirmations
                logger.warning(
                    f"[QUORUM] ✗ Quorum NOT met: got {successful_count} follower confirmations "
                    f"(needed {required_follower_confirmations}) + 1 leader = {total_confirmations} total"
                )
        
        if quorum_met:
            return WriteResponse(
                success=True,
                key=key,
                value=value,
                confirmations=total_confirmations,
                quorum_met=True,
                latency_ms=latency,
                replication_results=replication_results
            )
        else:
            # Write succeeded locally but didn't get enough confirmations for quorum
            # In strict semi-synchronous replication, we might wait longer or fail,
            # but for this lab we'll return success but indicate quorum wasn't met
            logger.warning(
                f"Write quorum not met: got {total_confirmations} confirmations, "
                f"needed {WRITE_QUORUM}"
            )
            return WriteResponse(
                success=True,  # Still return success as write is in leader
                key=key,
                value=value,
                confirmations=total_confirmations,
                quorum_met=False,
                latency_ms=latency,
                replication_results=replication_results
            )
            
    except Exception as e:
        logger.error(f"Error in write: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/read")
async def read(key: Optional[str] = None):
    """Read endpoint - reads from local store."""
    if key is None:
        raise HTTPException(status_code=400, detail="key parameter is required")
    
    if key in store:
        return {"key": key, "value": store[key]}
    else:
        raise HTTPException(status_code=404, detail="key not found")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "role": "leader",
        "followers": FOLLOWERS,
        "write_quorum": WRITE_QUORUM,
        "store_size": len(store)
    }


@app.get("/store")
async def get_store():
    """Get entire store (for testing/verification)."""
    return store


@app.get("/")
async def root():
    """Root endpoint - shows available endpoints."""
    return {
        "message": "Key-Value Store Leader API",
        "endpoints": {
            "POST /write": "Write a key-value pair. Body: {\"key\": \"string\", \"value\": \"string\"}",
            "GET /read?key=<key>": "Read a value by key",
            "GET /health": "Health check",
            "GET /store": "Get entire store",
            "GET /docs": "FastAPI interactive documentation",
            "GET /openapi.json": "OpenAPI schema"
        }
    }


if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv('PORT', '8080'))
    uvicorn.run(app, host='0.0.0.0', port=port)
