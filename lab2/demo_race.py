import requests
import threading
import time


def test_race_condition():
    """Test race condition by making many requests to the same file"""
    print("Testing race condition with VERY aggressive delays...")
    print("Making 20 requests to the same file simultaneously...")
    print("Watch the server logs to see thread interlacing!")
    print("Expected: Counter should show LESS than 20 due to race condition!")
    
    def make_request():
        try:
            response = requests.get("http://server-race-demo:8080/books/Lab2_CS.pdf", timeout=30)
            return response.status_code
        except Exception as e:
            return 0
    
    # Create 20 threads all hitting the same file
    threads = []
    for i in range(20):
        t = threading.Thread(target=make_request)
        threads.append(t)
    
    # Start all threads at once
    for t in threads:
        t.start()
    
    # Wait for all to complete
    for t in threads:
        t.join()
    
    print("Done! Now check the directory listing at http://localhost:8082/books/")
    print("Refresh the page multiple times - you should see inconsistent counter values!")
    print("Expected: Should show less than 20 due to race condition!")


if __name__ == "__main__":
    test_race_condition()
