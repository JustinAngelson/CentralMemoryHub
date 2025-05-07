import requests
import time

def check_url(url):
    try:
        print(f"Attempting to connect to {url}...")
        start = time.time()
        response = requests.get(url, timeout=10)
        end = time.time()
        
        print(f"Status Code: {response.status_code}")
        print(f"Response Time: {end - start:.2f} seconds")
        print(f"Headers: {dict(response.headers)}")
        print(f"Response Body: {response.text[:200]}...")  # Just show the first 200 chars
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to {url}: {e}")
        return False

# URLs to check
urls = [
    "https://memory-vault-angelson.replit.app/sys/health",
    "https://a4bcd18d-c239-4cf3-b41c-6f743ef6fa20-00-32na6d6s4kheq.kirk.replit.dev/sys/health"
]

# Check each URL
print("=== Testing URLs ===")
for url in urls:
    print(f"\nChecking {url}")
    success = check_url(url)
    print(f"Success: {success}")

print("\n=== Summary of findings ===")
print("If the domain resolves but HTTP requests fail, the issue could be:")
print("1. Firewall blocking connections")
print("2. Server not running on that domain")
print("3. Custom GPT environment restrictions")
print("\nPossible solutions:")
print("1. Deploy the application for a stable domain")
print("2. Use a tunneling service like ngrok")
print("3. Check if the production URL is accessible from other environments")