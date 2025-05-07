#!/usr/bin/env python3
"""
Test script to verify case-insensitive API key header handling.
This helps ensure that Custom GPT integration works correctly with various header cases.
"""

import requests
import sys

# Base URL for the application
BASE_URL = "https://memory-vault-angelson.replit.app"

def test_header_case_sensitivity(api_key, endpoint):
    """Test that API key headers are case-insensitive."""
    
    # Test cases with different header capitalizations
    header_cases = [
        {"X-API-KEY": api_key},                  # Standard case
        {"x-api-key": api_key},                  # All lowercase
        {"X-Api-Key": api_key},                  # Mixed case
        {"x-API-key": api_key},                  # Another mixed case
    ]
    
    print(f"Testing API key header case-insensitivity on {endpoint}")
    print("-" * 50)
    
    for i, headers in enumerate(header_cases, 1):
        header_str = list(headers.keys())[0]
        print(f"Test case {i}: Using header '{header_str}'")
        
        try:
            response = requests.get(f"{BASE_URL}{endpoint}", headers=headers)
            status = response.status_code
            
            if status == 200:
                print(f"✅ SUCCESS: Status code {status}")
                
                # Show a snippet of the response for verification
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    print(f"  Response contains {len(data)} items")
                else:
                    print(f"  Response: {str(response.text)[:50]}...")
                    
            elif status == 401:
                print(f"❌ FAILED: Status code {status} - Unauthorized")
                print(f"  Response: {response.text}")
            else:
                print(f"⚠️ UNEXPECTED: Status code {status}")
                print(f"  Response: {response.text}")
        except Exception as e:
            print(f"❌ ERROR: {str(e)}")
        
        print()
    
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python api_key_header_test.py YOUR_API_KEY")
        sys.exit(1)
        
    api_key = sys.argv[1]
    
    # Test endpoints that require authentication
    test_header_case_sensitivity(api_key, "/agent/directory/hierarchy")
    test_header_case_sensitivity(api_key, "/sys/health")  # This shouldn't require an API key