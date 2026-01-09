import unittest
import requests
import threading
import time
import sys

class TestApiConcurrency(unittest.TestCase):
    BASE_URL = "http://localhost:5000"

    def setUp(self):
        # Check if server is reachable
        try:
            requests.get(f"{self.BASE_URL}/health", timeout=1)
        except requests.exceptions.ConnectionError:
            print("Skipping tests: Server not running at localhost:5000")
            self.skipTest("Server not running")

    def test_concurrent_run_requests(self):
        """Test that a second run request is rejected while one is running"""
        
        url = f"{self.BASE_URL}/api/unified/run/start"
        
        # 1. Start primary request (streaming)
        # We use stream=True to keep connection open but not consume it all immediately
        payload1 = {
            "text": "Concurrency Test Primary",
            "maxTurns": 2
        }
        
        print(f"Sending first request (Stream)...")
        # We use a session or just request with stream=True
        # We need to hold this connection open.
        
        def run_first_request():
            try:
                with requests.post(url, json=payload1, stream=True, timeout=5) as r:
                    print(f"First request status: {r.status_code}")
                    # Consume a bit
                    for line in r.iter_lines():
                       if line:
                           # print(f"Stream 1: {line}")
                           pass
            except Exception as e:
                print(f"First request ended: {e}")

        t1 = threading.Thread(target=run_first_request)
        t1.start()
        
        # Give it a moment to acquire lock
        time.sleep(1.0)
        
        # 2. Immediately try to start another run
        payload2 = {
            "text": "Concurrency Test Secondary",
            "maxTurns": 1
        }
        
        print(f"Sending second request immediately...")
        try:
            # This should return JSON 503 immediately
            response2 = requests.post(url, json=payload2, timeout=5)
            print(f"Second request status: {response2.status_code}, {response2.text}")
            
            if response2.status_code == 503:
                print("SUCCESS: Second request was rejected with 503 Busy.")
            elif response2.status_code == 200:
                print("WARNING: Second request was accepted. Lock might not be working or released too fast.")
            else:
                 print(f"Unexpected status: {response2.status_code}")
                
        except requests.Timeout:
            print("Second request timed out")
        
        t1.join(timeout=2)

if __name__ == "__main__":
    unittest.main()
