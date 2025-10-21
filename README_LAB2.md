# Lab 2: Multithreaded HTTP Server


## 📋 Overview

Lab 2 introduces:

1. **Multithreading** - ThreadPoolExecutor-based concurrent request handling
2. **Request Counting** - Thread-safe counters with race condition comparison
3. **Rate Limiting** - Per-IP sliding window rate limiter (5 req/s)

![alt text](/screen/image13.png)

## 🗂️ Project Structure

```
project/
├── lab2/
│   ├── server_lab2.py          # Multithreaded + thread-safe
│   ├── server_race_demo.py     # Multithreaded + race conditions
│   ├── test_concurrent.py      # Concurrent testing tool
│   ├── demo_race.py            # Race condition demo script
│   ├── Dockerfile.lab2         # Docker image
│   └── docker-compose.lab2.yml # Multi-service orchestration
├── server.py                    # Lab 1: Single-threaded
└── site/                        # Shared content directory
    ├── index.html
    ├── image.png
    └── books/
```

## 🚀 Quick Start

### Start All Servers

```cmd
# From repository root
cd .\lab2

# Start all three servers simultaneously
docker compose -f docker-compose.lab2.yml up --build
```

**Access points:**
- Lab 1 (single-threaded): http://localhost:8083/
- Lab 2 (multithreaded): http://localhost:8081/
- Race demo: http://localhost:8082/

### Start Individual Servers

```bash
# Lab 2 server only
docker compose -f docker-compose.lab2.yml up --build server-lab2

# Race condition demo only
docker compose -f docker-compose.lab2.yml up --build server-race-demo

# Lab 1 server only
docker compose -f docker-compose.lab2.yml up --build server-lab1
```

## 🧪 Testing

### 1. Performance Comparison

Compare single-threaded vs multithreaded performance:

```bash
# Test Lab 1 (single-threaded) - expect ~4+ seconds
docker compose -f docker-compose.lab2.yml run --rm tester http://server-lab1:8080/ 10
```
![Lab1](/screen/image8.png)
```bash
# Test Lab 2 (multithreaded) - expect ~0.1-0.2 seconds
docker compose -f docker-compose.lab2.yml run --rm tester http://server-lab2:8080/ 10
```
![Lab2](/screen/image9.png)

### 2. Race Condition Demo

Demonstrate unsafe counter behavior:

```bash
# Start race demo server
docker compose -f docker-compose.lab2.yml up --build server-race-demo

# Run concurrent requests to expose race condition
docker compose -f docker-compose.lab2.yml run --rm race-demo
```
![alt text](/screen/image10.png)

Visit http://localhost:8082/ and refresh to see inconsistent counter values.

### 3. Rate Limiting

Test the 5 requests/second limit:

```bash
# Above limit (6 req/s) - expect many 429 responses
docker compose -f docker-compose.lab2.yml run --rm tester http://server-lab2:8080/ 60 0 
```
![alt text](/screen/image11.png)

```bash
# Below limit (3 req/s) - expect all 200 responses
docker compose -f docker-compose.lab2.yml run --rm tester http://server-lab2:8080/ 30 0.33
```
![alt text](/screen/image12.png)

## 💻 Command Line Usage

### Lab 2 Server

```bash
python server_lab2.py <content_dir> [port] [max_threads] [--simulate-work]
```

**Examples:**
```bash
# Default configuration
python server_lab2.py /app/site 8080

# Custom thread pool + work simulation
python server_lab2.py /app/site 8080 20 --simulate-work
```

### Race Demo Server

```bash
python server_race_demo.py <content_dir> [port] [max_threads] [--simulate-work]
```

### Concurrent Tester

```bash
python test_concurrent.py <base_url> [num_requests] [delay] [--rate-test]
```

**Examples:**
```bash
# 10 concurrent requests
python test_concurrent.py http://localhost:8081/ 10

# Staggered requests (0.1s delay)
python test_concurrent.py http://localhost:8081/ 10 0.1

# Rate limit testing
python test_concurrent.py http://localhost:8081/ 60 0 --rate-test
```

## 🔧 Implementation Details

### Multithreading Architecture
- **Thread Pool:** `ThreadPoolExecutor` with configurable workers (default: 10)
- **Concurrency:** Each request handled in separate thread
- **Work Simulation:** Optional 1-second delay for performance testing

### Request Counter System

| Implementation | Thread Safety|
|---------------|---------------|
| `server_lab2.py` | ✅ Uses `threading.Lock()` | 
| `server_race_demo.py` | ❌ No synchronization |



### Rate Limiter
- **Algorithm:** Sliding window
- **Limit:** 5 requests per second per IP
- **Response:** HTTP 429 "Too Many Requests"
- **Thread Safety:** Protected with locks

## 📊 Performance Benchmarks

| Server Type | 10 Concurrent Requests | Processing |
|-------------|----------------------|------------|
| Lab 1 (Single-threaded) | ~4+ seconds | Sequential |
| Lab 2 (Multithreaded) | ~0.1-0.5 seconds | Concurrent |
| Race Demo | ~0.1-0.2 seconds | Concurrent (unsafe) |

## 🧹 Cleanup

```bash
# Stop and remove all containers
docker compose -f docker-compose.lab2.yml down -v

# Alternative cleanup
docker compose down -v
```

