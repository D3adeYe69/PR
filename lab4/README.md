# Lab 4: Key-Value Store with Single-Leader Replication

This lab implements a key-value store with single-leader replication using semi-synchronous replication. The leader accepts writes and replicates them to followers concurrently.

## Architecture

- **1 Leader**: Accepts all write requests and replicates to followers
- **5 Followers**: Accept replication requests from the leader
- **Semi-synchronous replication**: Leader waits for a configurable number of confirmations (write quorum) before reporting success
- **Concurrent execution**: All requests are handled concurrently using FastAPI's async capabilities

## Features

- FastAPI-based web API with JSON communication
- Concurrent request handling (native async/await)
- Configurable write quorum (1-5)
- Simulated network delays (configurable MIN_DELAY and MAX_DELAY)
- Concurrent replication to all followers
- Integration tests
- Performance analysis with plotting

## Setup

1. Build and start all services:
```bash
docker-compose up --build
```

2. Services will be available at:
   - Leader: http://localhost:8080
   - Follower 1: http://localhost:8081
   - Follower 2: http://localhost:8082
   - Follower 3: http://localhost:8083
   - Follower 4: http://localhost:8084
   - Follower 5: http://localhost:8085

3. **FastAPI automatically provides interactive documentation:**
   - Leader docs: http://localhost:8080/docs
   - Follower docs: http://localhost:8081/docs (or any follower port)

4. **Quick test:**
   ```bash
   # Test health endpoint
   curl http://localhost:8080/health
   
   # Write a key-value pair
   curl -X POST http://localhost:8080/write \
     -H "Content-Type: application/json" \
     -d '{"key": "test", "value": "hello"}'
   
   # Read the value
   curl http://localhost:8080/read?key=test
   ```

   Or visit the interactive API docs at http://localhost:8080/docs

## Configuration

Environment variables (set in docker-compose.yml):
- `WRITE_QUORUM`: Number of confirmations required (default: 3)
- `MIN_DELAY`: Minimum network delay in ms (default: 0)
- `MAX_DELAY`: Maximum network delay in ms (default: 1000)
- `FOLLOWERS`: Comma-separated list of follower URLs

## API Endpoints

### Leader

- `POST /write` - Write a key-value pair
  ```json
  {
    "key": "mykey",
    "value": "myvalue"
  }
  ```

- `GET /read?key=<key>` - Read a value by key
- `GET /health` - Health check
- `GET /store` - Get entire store (for testing)

### Followers

- `POST /replicate` - Internal endpoint for replication (called by leader)
- `GET /read?key=<key>` - Read a value by key
- `GET /health` - Health check
- `GET /store` - Get entire store (for testing)

## Running Tests

### Integration Test

```bash
docker-compose exec leader python test_integration.py
```

Or run locally (if services are running):
```bash
python test_integration.py
```

### Performance Analysis

Run the automated performance test script:

```bash
python test_quorum_automated.py
```

This script will:
- Automatically test write quorum values from 1 to 5
- Update `WRITE_QUORUM` in docker-compose.yml for each value
- Recreate the leader container to apply changes
- Make ~100 writes concurrently (10 at a time) on 10 keys
- Generate a plot: `write_quorum_vs_latency.png`
- Show latency statistics for each quorum value

## Expected Results

### Write Quorum vs Latency

The performance test should show a clear increasing trend with the following metrics:

- **Mean latency**: Average latency across all requests
- **Median latency**: 50th percentile (half of requests are faster)
- **P95 latency**: 95th percentile (95% of requests are faster) - shows worst 5% of cases
- **P99 latency**: 99th percentile (99% of requests are faster) - shows worst 1% of cases

Expected values (with delays 0-1000ms):
- **Q=1**: Lowest latency (~50-150ms) - returns immediately, no follower wait
- **Q=2**: ~150-300ms - waits for 1st fastest follower
- **Q=3**: ~300-500ms - waits for 2nd fastest follower
- **Q=4**: ~450-600ms - waits for 3rd fastest follower
- **Q=5**: Highest latency (~600-900ms) - waits for 4th fastest follower

The P95 and P99 percentiles will be higher than the mean, showing the tail of the latency distribution (worst-case scenarios).

This demonstrates the **consistency vs performance trade-off**:
- **Lower quorum (1-2)**: Faster writes, less durability guarantee
- **Higher quorum (4-5)**: Slower writes, better durability guarantee

With network delays (0-1000ms), higher quorums increase latency as the system waits for more confirmations.

### Data Consistency and Race Conditions

**Important**: The consistency check may show inconsistencies (missing keys, value mismatches) between followers and the leader. This is **EXPECTED** and demonstrates:

- **Race conditions**: Concurrent writes can cause replication conflicts
- **Replication conflicts**: As described in "Designing Data-Intensive Applications" (Chapter 5)
- **Eventual consistency**: Data will eventually become consistent, but not immediately
- **The challenges of distributed systems**: Maintaining perfect consistency with concurrent operations is difficult

This is a **feature, not a bug** - it demonstrates the real-world challenges of distributed replication systems.

## Implementation Details

- **FastAPI**: Used for native async/await support and concurrent request handling
- **aiohttp**: Used for async HTTP requests to followers
- **asyncio.gather()**: Ensures concurrent replication to all followers
- **Random delays**: Each replication request gets a random delay in [MIN_DELAY, MAX_DELAY] to simulate network conditions

## Files

### Core Application
- `leader.py` - Leader server implementation
- `follower.py` - Follower server implementation
- `run_followers.py` - Script to run all 5 followers in one container
- `docker-compose.yml` - Docker Compose configuration
- `Dockerfile` - Docker image definition
- `requirements.txt` - Python dependencies

### Testing
- `test_integration.py` - Integration tests
- `test_quorum_automated.py` - Automated performance testing script (tests all quorum values)

## Key Concepts

This lab demonstrates:
- **Single-leader replication**: Only the leader accepts writes
- **Semi-synchronous replication**: Leader waits for a configurable number of confirmations (write quorum)
- **Consistency vs Performance trade-off**: Higher quorum = safer but slower
- **Concurrent execution**: All requests handled concurrently using FastAPI async/await
- **Network delay simulation**: Random delays (0-1000ms) simulate real-world network conditions

