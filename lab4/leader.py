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
    """
    await asyncio.sleep(delay_ms / 1000.0)  # Convert ms to seconds
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{follower_url}/replicate",
                json={"key": key, "value": value},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return {"success": True, "follower": follower_url, "result": result}
                else:
                    return {"success": False, "follower": follower_url, "error": f"Status {response.status}"}
    except asyncio.TimeoutError:
        return {"success": False, "follower": follower_url, "error": "Timeout"}
    except Exception as e:
        return {"success": False, "follower": follower_url, "error": str(e)}


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
        # Quorum includes leader, so we need (WRITE_QUORUM - 1) follower confirmations
        required_follower_confirmations = max(0, WRITE_QUORUM - 1)
        
        # Semi-synchronous replication: return as soon as we have enough confirmations
        if not FOLLOWERS or required_follower_confirmations == 0:
            # Q=1: Only leader confirms, return immediately (no network wait)
            latency = (time.time() - start_time) * 1000
            quorum_met = True
            total_confirmations = 1
            replication_results = []
            
            # Still replicate to followers in background (don't wait)
            if FOLLOWERS:
                delays = [random.randint(MIN_DELAY, MAX_DELAY) for _ in FOLLOWERS]
                # Start replication but don't wait
                for follower, delay in zip(FOLLOWERS, delays):
                    asyncio.create_task(replicate_to_follower(follower, key, value, delay))
        else:
            # Q>=2: Need to wait for follower confirmations
            # Generate random delays for each follower
            delays = [random.randint(MIN_DELAY, MAX_DELAY) for _ in FOLLOWERS]
            
            # Start replication to all followers concurrently
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
            # So the first result is the fastest follower, second is 2nd fastest, etc.
            responses_received = 0
            for coro in asyncio.as_completed(tasks):
                try:
                    result = await coro
                    responses_received += 1
                    replication_results.append(result)
                    if result.get('success', False):
                        successful_count += 1
                    
                    # Check if we have enough confirmations (including leader = 1)
                    # We need (WRITE_QUORUM - 1) successful follower responses
                    if successful_count >= required_follower_confirmations:
                        # Quorum met! Record latency NOW and return
                        latency = (time.time() - start_time) * 1000
                        quorum_met = True
                        total_confirmations = successful_count + 1
                        
                        logger.debug(
                            f"Quorum {WRITE_QUORUM} met: {successful_count} followers + leader = "
                            f"{total_confirmations} total, latency={latency:.2f}ms, "
                            f"responses_received={responses_received}"
                        )
                        
                        # Don't wait for remaining - return immediately
                        # (remaining tasks will complete in background)
                        break
                except Exception as e:
                    responses_received += 1
                    replication_results.append({"success": False, "error": str(e)})
            
            # If we didn't meet quorum (shouldn't happen with enough followers)
            if not quorum_met:
                latency = (time.time() - start_time) * 1000
                total_confirmations = successful_count + 1
                quorum_met = total_confirmations >= WRITE_QUORUM
        
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
