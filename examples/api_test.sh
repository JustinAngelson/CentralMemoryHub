#!/bin/bash
# Memory Hub API Test Script
# --------------------------
# This script demonstrates how to interact with the Memory Hub API
# using curl. It's helpful for testing and debugging API interactions.

# Base URL
API_URL="https://memory-vault-angelson.replit.app"

# Replace this with your actual API key
API_KEY="your-api-key-here"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Memory Hub API Test Script${NC}"
echo "======================================="
echo ""

# Function to make API calls
call_api() {
    local method=$1
    local endpoint=$2
    local data=$3
    local auth=$4
    
    echo -e "${BLUE}Making $method request to $endpoint${NC}"
    
    local headers="-H 'Content-Type: application/json'"
    if [ "$auth" = "true" ]; then
        headers="$headers -H 'X-API-KEY: $API_KEY'"
    fi
    
    local curl_cmd="curl -s -X $method $headers"
    if [ ! -z "$data" ]; then
        curl_cmd="$curl_cmd -d '$data'"
    fi
    
    curl_cmd="$curl_cmd ${API_URL}${endpoint}"
    
    echo "Command: $curl_cmd"
    echo ""
    
    eval $curl_cmd | jq .
    
    echo ""
    echo "--------------------------------------"
    echo ""
}

# 1. Test health endpoint (no auth required)
echo -e "${GREEN}1. Testing health endpoint (no auth required)${NC}"
call_api "GET" "/sys/health" "" "false"

# 2. Create a memory
echo -e "${GREEN}2. Creating a memory${NC}"
memory_data='{"content": "This is a test memory created at '"$(date)"'"}'
response=$(call_api "POST" "/memory/unstructured" "$memory_data" "true")
memory_id=$(echo $response | jq -r '.id')

echo "Created memory with ID: $memory_id"

# 3. Retrieve the memory
if [ ! -z "$memory_id" ] && [ "$memory_id" != "null" ]; then
    echo -e "${GREEN}3. Retrieving the memory${NC}"
    call_api "GET" "/memory/unstructured/$memory_id" "" "true"
else
    echo -e "${RED}Skipping memory retrieval as no valid ID was returned${NC}"
fi

# 4. Search for memories
echo -e "${GREEN}4. Searching for memories${NC}"
search_data='{"query": "test memory"}'
call_api "POST" "/search" "$search_data" "true"

# 5. Get agent directory
echo -e "${GREEN}5. Getting agent directory${NC}"
call_api "GET" "/api/directory" "" "true"

echo -e "${GREEN}Tests completed${NC}"
echo "To use this script with your actual API key, edit the API_KEY variable at the top."