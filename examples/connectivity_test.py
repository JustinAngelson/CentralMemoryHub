#!/usr/bin/env python3
"""
Central Memory Hub API - Connectivity Test Script
=================================================

This script tests connectivity with the Central Memory Hub API
and helps diagnose issues with Custom GPT integration.
"""

import json
import requests
import sys
import time

# Configuration
API_SERVERS = [
    "https://memory-vault-angelson.replit.app",
    "https://a4bcd18d-c239-4cf3-b41c-6f743ef6fa20-00-32na6d6s4kheq.kirk.replit.dev"
]
API_KEY = "your-api-key-here"  # Replace with your actual API key

def test_health_check(base_url):
    """Test the basic health check endpoint."""
    print(f"Testing health check endpoint at {base_url}...")
    try:
        response = requests.get(f"{base_url}/sys/health", timeout=10)
        if response.status_code == 200:
            print("✅ Health check successful")
            print(f"  Status: {response.json().get('status')}")
            print(f"  Time: {response.json().get('time')}")
            print(f"  Components: {json.dumps(response.json().get('components', {}))}")
            return True
        else:
            print(f"❌ Health check failed with status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Health check error: {e}")
        return False

def test_diagnostic_endpoint(base_url):
    """Test the enhanced diagnostic endpoint."""
    print(f"\nTesting diagnostic endpoint at {base_url}...")
    try:
        response = requests.get(f"{base_url}/sys/gpt-diagnostic", timeout=10)
        if response.status_code == 200:
            print("✅ Diagnostic check successful")
            data = response.json()
            print(f"  Status: {data.get('status')}")
            print(f"  Timestamp: {data.get('timestamp')}")
            print(f"  Remote Address: {data.get('request_info', {}).get('remote_addr')}")
            print(f"  CORS Enabled: {data.get('connectivity', {}).get('cors_enabled')}")
            
            # Print troubleshooting steps
            print("\nTroubleshooting Notes:")
            for note in data.get('notes', []):
                print(f"  - {note}")
            
            return True
        else:
            print(f"❌ Diagnostic check failed with status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Diagnostic check error: {e}")
        return False

def test_api_key_auth(base_url, api_key):
    """Test API key authentication."""
    print(f"\nTesting API key authentication at {base_url}...")
    if not api_key or api_key == "your-api-key-here":
        print("⚠️ Please set your API key in the script")
        return False
    
    try:
        # Test with the search endpoint which requires authentication
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key
        }
        data = {"query": "test connectivity"}
        
        response = requests.post(
            f"{base_url}/search",
            headers=headers,
            json=data,
            timeout=10
        )
        
        if response.status_code == 200:
            print("✅ API key authentication successful")
            return True
        elif response.status_code == 401:
            print("❌ API key authentication failed: Invalid or expired API key")
            return False
        else:
            print(f"❌ API request failed with status code: {response.status_code}")
            if response.text:
                print(f"  Response: {response.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ API request error: {e}")
        return False

def test_cors_headers(base_url):
    """Test CORS headers implementation."""
    print(f"\nTesting CORS headers at {base_url}...")
    try:
        # Send an OPTIONS request to check CORS headers
        headers = {
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type, X-API-KEY"
        }
        
        response = requests.options(f"{base_url}/sys/health", headers=headers, timeout=10)
        
        cors_headers = {
            "Access-Control-Allow-Origin": None,
            "Access-Control-Allow-Methods": None,
            "Access-Control-Allow-Headers": None
        }
        
        for header in cors_headers:
            cors_headers[header] = response.headers.get(header)
            if cors_headers[header]:
                print(f"✅ {header}: {cors_headers[header]}")
            else:
                print(f"❌ Missing {header}")
        
        if all(cors_headers.values()):
            print("✅ CORS headers are properly configured")
            return True
        else:
            print("⚠️ Some CORS headers are missing")
            return False
    except Exception as e:
        print(f"❌ CORS test error: {e}")
        return False

def run_all_tests():
    """Run all connectivity tests against all servers."""
    results = {}
    
    for base_url in API_SERVERS:
        print(f"\n{'=' * 60}")
        print(f"Testing server: {base_url}")
        print(f"{'=' * 60}")
        
        results[base_url] = {
            "health_check": test_health_check(base_url),
            "diagnostic": test_diagnostic_endpoint(base_url),
            "cors": test_cors_headers(base_url),
            "api_auth": test_api_key_auth(base_url, API_KEY)
        }
        
        time.sleep(1)  # Pause between server tests
    
    # Print summary
    print(f"\n{'=' * 60}")
    print("CONNECTIVITY TEST SUMMARY")
    print(f"{'=' * 60}")
    
    for base_url, tests in results.items():
        print(f"\nServer: {base_url}")
        total_tests = len(tests)
        passed_tests = sum(1 for result in tests.values() if result)
        
        for test_name, passed in tests.items():
            status = "✅ PASSED" if passed else "❌ FAILED"
            print(f"  {test_name}: {status}")
        
        print(f"  Overall: {passed_tests}/{total_tests} tests passed")
    
    # Overall recommendation
    if any(sum(server_results.values()) == len(server_results) for server_results in results.values()):
        print("\n✅ RECOMMENDATION: API connectivity is working on at least one server.")
        print("   Your Custom GPT should be able to connect to the Memory Hub API.")
    else:
        print("\n⚠️ RECOMMENDATION: API connectivity issues detected.")
        print("   Please review the troubleshooting guide at examples/custom_gpt_connectivity_troubleshooting.md")

if __name__ == "__main__":
    print("Central Memory Hub API - Connectivity Test")
    print("=========================================")
    run_all_tests()