# Custom GPT Integration Guide for Memory Hub API

This guide provides examples for integrating the Memory Hub API with your Custom GPT.

## Health Check Endpoint

First, test connectivity with the health check endpoint, which doesn't require authentication:

```http
GET https://memory-vault-angelson.replit.app/sys/health
```

Expected response:
```json
{
  "status": "healthy",
  "time": "2025-05-07T00:47:23Z",
  "components": {
    "database": "up",
    "vector_db": "up",
    "api": "up"
  },
  "version": "1.0.0"
}
```

## Authentication

All other endpoints require API key authentication using the `X-API-KEY` header:

```http
X-API-KEY: your-api-key-here
```

You can get an API key from the Memory Hub web interface.

## Basic Functionality

### 1. Store a memory

```http
POST https://memory-vault-angelson.replit.app/memory/unstructured
X-API-KEY: your-api-key-here
Content-Type: application/json

{
  "content": "This is important information the AI needs to remember about the project."
}
```

Expected response:
```json
{
  "id": "c7e9a141-8f5c-4e0b-9e6d-8b4c2f1f8a7e",
  "pinecone_id": "vec_c7e9a141-8f5c-4e0b-9e6d-8b4c2f1f8a7e",
  "message": "Memory stored successfully"
}
```

### 2. Search for relevant information

```http
POST https://memory-vault-angelson.replit.app/search
X-API-KEY: your-api-key-here
Content-Type: application/json

{
  "query": "What information do we have about the project?"
}
```

Expected response:
```json
{
  "query": "What information do we have about the project?",
  "results": [
    {
      "id": "c7e9a141-8f5c-4e0b-9e6d-8b4c2f1f8a7e",
      "content": "This is important information the AI needs to remember about the project.",
      "pinecone_id": "vec_c7e9a141-8f5c-4e0b-9e6d-8b4c2f1f8a7e",
      "similarity_score": 0.89
    }
  ]
}
```

### 3. Retrieve a specific memory

```http
GET https://memory-vault-angelson.replit.app/memory/unstructured/c7e9a141-8f5c-4e0b-9e6d-8b4c2f1f8a7e
X-API-KEY: your-api-key-here
```

Expected response:
```json
{
  "id": "c7e9a141-8f5c-4e0b-9e6d-8b4c2f1f8a7e",
  "content": "This is important information the AI needs to remember about the project.",
  "pinecone_id": "vec_c7e9a141-8f5c-4e0b-9e6d-8b4c2f1f8a7e"
}
```

## Advanced: Working with Multi-Agent Features

### 1. Get the Agent Directory

```http
GET https://memory-vault-angelson.replit.app/api/directory
X-API-KEY: your-api-key-here
```

### 2. Add a new agent to the directory

```http
POST https://memory-vault-angelson.replit.app/api/directory
X-API-KEY: your-api-key-here
Content-Type: application/json

{
  "name": "Product Manager GPT",
  "role": "Product Manager",
  "description": "Manages product requirements and roadmap",
  "capabilities": ["Requirements analysis", "User story creation", "Roadmap planning"],
  "reports_to": "cto_agent_id",
  "seniority_level": 3,
  "status": "active"
}
```

## Common Error Responses

### 1. Authentication Error (401)

```json
{
  "error": "Unauthorized access",
  "message": "Invalid or missing API key"
}
```

### 2. Bad Request (400)

```json
{
  "error": "Bad request",
  "message": "Missing required fields"
}
```

### 3. Not Found (404)

```json
{
  "error": "Not found",
  "message": "The requested resource could not be found"
}
```

## Integrating in GPT Actions

When setting up a Custom GPT, use the OpenAPI schema at:
`https://memory-vault-angelson.replit.app/openapi.json`

Make sure your GPT is configured to:
1. Pass the API key in the `X-API-KEY` header (all capital letters)
2. Check connectivity using the health endpoint before trying other endpoints
3. Handle error states gracefully

## Debugging Integration Issues

If you encounter issues integrating with the Memory Hub API:

1. Verify your API key is valid and not expired
2. Use the health check endpoint to verify API connectivity
3. Check that you're using the correct case for the `X-API-KEY` header
4. Ensure your JSON payloads match the expected format