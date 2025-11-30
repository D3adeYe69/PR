#!/usr/bin/env python3
"""
Script to run all 5 followers in a single container.
Each follower runs on a different port using separate processes.
"""

import os
import multiprocessing
import uvicorn
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_follower(port: int, follower_id: str):
    """Run a single follower instance in a separate process."""
    # Set environment variables for this process
    os.environ['PORT'] = str(port)
    os.environ['FOLLOWER_ID'] = follower_id
    
    # Import here - each process gets its own module instance
    from follower import app
    
    logger.info(f"Starting follower {follower_id} on port {port}")
    config = uvicorn.Config(app, host='0.0.0.0', port=port, log_level='info')
    server = uvicorn.Server(config)
    server.run()


if __name__ == '__main__':
    # Configuration for 5 followers
    followers_config = [
        (8081, 'follower1'),
        (8082, 'follower2'),
        (8083, 'follower3'),
        (8084, 'follower4'),
        (8085, 'follower5'),
    ]
    
    # Start each follower in a separate process
    processes = []
    for port, follower_id in followers_config:
        p = multiprocessing.Process(target=run_follower, args=(port, follower_id))
        p.start()
        processes.append(p)
        logger.info(f"Started process for {follower_id} on port {port}")
    
    # Wait for all processes
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        logger.info("Shutting down followers...")
        for p in processes:
            p.terminate()
        for p in processes:
            p.join()
        sys.exit(0)

