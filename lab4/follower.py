#!/usr/bin/env python3
"""
Follower server for key-value store replication.
Followers accept replication requests from the leader.
"""

import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# In-memory key-value store
store = {}

# Configuration
FOLLOWER_ID = os.getenv('FOLLOWER_ID', 'follower1')
PORT = int(os.getenv('PORT', '8080'))

logger.info(f"Follower {FOLLOWER_ID} initialized on port {PORT}")


# Pydantic models
class ReplicateRequest(BaseModel):
    key: str
    value: str


@app.post("/replicate")
async def replicate(request: ReplicateRequest):
    """Replicate endpoint - accepts replication requests from leader."""
    import time
    receive_time = time.time()
    
    try:
        key = request.key
        value = request.value
        
        # Store the replicated key-value pair
        # This is where race conditions can occur - multiple concurrent writes
        store[key] = value
        
        logger.info(
            f"[RACE] Follower {FOLLOWER_ID} replicated key='{key}' "
            f"at t={receive_time:.3f} (current store size: {len(store)})"
        )
        
        return {
            "success": True,
            "key": key,
            "value": value,
            "follower_id": FOLLOWER_ID,
            "timestamp": receive_time
        }
        
    except Exception as e:
        logger.error(f"Error in replicate: {e}")
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
        "role": "follower",
        "follower_id": FOLLOWER_ID,
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
        "message": f"Key-Value Store Follower API ({FOLLOWER_ID})",
        "endpoints": {
            "POST /replicate": "Internal endpoint for replication (called by leader)",
            "GET /read?key=<key>": "Read a value by key",
            "GET /health": "Health check",
            "GET /store": "Get entire store",
            "GET /docs": "FastAPI interactive documentation"
        }
    }


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=PORT)
