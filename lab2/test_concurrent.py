import requests
import threading
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed


def make_request(url: str, delay: float = 0) -> tuple[str, float, int]:
    """Make a single request and return (url, response_time, status_code)"""
    start_time = time.time()
    try:
        response = requests.get(url, timeout=10)
        end_time = time.time()
        return url, end_time - start_time, response.status_code
    except Exception as e:
        end_time = time.time()
        return url, end_time - start_time, 0


def test_concurrent_requests(base_url: str, num_requests: int = 10, delay: float = 0):
    """Test concurrent requests and measure total time"""
    print(f"Making {num_requests} concurrent requests to {base_url}")
    if delay > 0:
        print(f"With {delay}s delay between request starts")
    
    start_time = time.time()
    results = []
    
    with ThreadPoolExecutor(max_workers=num_requests) as executor:
        # Submit all requests
        futures = []
        for i in range(num_requests):
            if delay > 0:
                time.sleep(delay)
            future = executor.submit(make_request, base_url)
            futures.append(future)
        
        # Collect results
        for future in as_completed(futures):
            url, response_time, status_code = future.result()
            results.append((url, response_time, status_code))
    
    end_time = time.time()
    total_time = end_time - start_time
    
    # Print results
    print(f"\nResults:")
    print(f"Total time: {total_time:.2f}s")
    print(f"Requests per second: {num_requests / total_time:.2f}")
    print(f"Successful requests: {sum(1 for _, _, status in results if status == 200)}")
    print(f"Failed requests: {sum(1 for _, _, status in results if status != 200)}")
    
    print(f"\nIndividual response times:")
    for url, response_time, status_code in results:
        print(f"  {url}: {response_time:.2f}s (status: {status_code})")
    
    return total_time, results


def test_rate_limiting(base_url: str, requests_per_second: float = 6, duration: int = 10):
    """Test rate limiting by making requests at specified rate"""
    print(f"\nTesting rate limiting at {requests_per_second} requests/second for {duration}s")
    
    interval = 1.0 / requests_per_second
    start_time = time.time()
    results = []
    
    while time.time() - start_time < duration:
        request_start = time.time()
        url, response_time, status_code = make_request(base_url)
        results.append((url, response_time, status_code))
        
        # Wait for next request
        elapsed = time.time() - request_start
        sleep_time = interval - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    # Analyze results
    successful = [r for r in results if r[2] == 200]
    rate_limited = [r for r in results if r[2] == 429]
    
    print(f"\nRate limiting test results:")
    print(f"Total requests: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Rate limited (429): {len(rate_limited)}")
    print(f"Actual rate: {len(successful) / duration:.2f} successful requests/second")
    
    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_concurrent.py <base_url> [num_requests] [delay] [--rate-test]", file=sys.stderr)
        print("Examples:")
        print("  python test_concurrent.py http://localhost:8080/ 10")
        print("  python test_concurrent.py http://localhost:8080/ 10 0.1")
        print("  python test_concurrent.py http://localhost:8080/ 60 0 --rate-test")
        print("  python test_concurrent.py http://localhost:8080/ 30 0.33 --rate-test")
        sys.exit(1)
    
    base_url = sys.argv[1]
    num_requests = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    delay = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "--rate-test" else 0
    rate_test = "--rate-test" in sys.argv
    
    if rate_test:
        # Calculate requests per second based on delay
        requests_per_second = 1.0 / delay if delay > 0 else 6
        test_rate_limiting(base_url, requests_per_second=requests_per_second, duration=10)
    else:
        test_concurrent_requests(base_url, num_requests, delay)


if __name__ == "__main__":
    main()
