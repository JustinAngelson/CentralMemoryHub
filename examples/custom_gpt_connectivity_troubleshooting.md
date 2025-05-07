# Custom GPT Integration Troubleshooting Guide

This guide provides solutions for resolving connectivity issues when integrating your Custom GPT with the Central Memory Hub API.

## Common Connectivity Issues

When developing Custom GPTs that interact with external APIs, you may encounter DNS resolution failures or connectivity issues. This is often due to:

1. OpenAI's network environment restrictions
2. DNS propagation delays
3. API configuration issues
4. Authentication problems

## Enhanced Diagnostic Endpoints

We've added special endpoints to help diagnose and troubleshoot connectivity issues:

### Basic Health Check

```
GET /sys/health
```

This endpoint doesn't require authentication and returns basic information about the API's health status.

**Response Example:**
```json
{
  "status": "healthy",
  "time": "2025-05-07T01:15:31.456789",
  "components": {
    "api": "up",
    "database": "up",
    "vector_db": "up"
  },
  "version": "1.0.0"
}
```

### Enhanced Diagnostic Check

```
GET /sys/gpt-diagnostic
```

This endpoint provides detailed diagnostic information about the request, server, and connectivity status.

**Response Example:**
```json
{
  "status": "connected",
  "timestamp": "2025-05-07T01:16:42.123456",
  "request_info": {
    "method": "GET",
    "path": "/sys/gpt-diagnostic",
    "remote_addr": "123.45.67.89",
    "user_agent": "Custom GPT/1.0",
    "headers": {
      "Host": "memory-vault-angelson.replit.app",
      "User-Agent": "Custom GPT/1.0",
      "Accept": "application/json"
    }
  },
  "server_info": {
    "hostname": "replit-container-123",
    "platform": "Linux-5.15.0-x86_64",
    "python_version": "3.11.5",
    "local_ip": "10.0.0.1"
  },
  "connectivity": {
    "pinecone_connection": "up",
    "cors_enabled": true,
    "api_version": "1.0.0"
  },
  "notes": [
    "If you can see this response, your Custom GPT can reach this API.",
    "Check the request headers to ensure the X-API-KEY header is being sent correctly.",
    "For persistent connectivity issues, consider using a different domain or a proxy service."
  ],
  "troubleshooting_steps": [
    "Verify the API base URL is correctly configured in the Custom GPT actions section",
    "Ensure your API key is valid and properly formatted in the Custom GPT",
    "Try using webhooks or a stable public domain if direct connections continue to fail"
  ]
}
```

## Solutions for Connectivity Issues

### 1. Use the Proper API URL

Always use the production URL in your Custom GPT configuration:
```
https://memory-vault-angelson.replit.app
```

### 2. Include Proper API Key Authentication

All API requests (except health checks) require an API key in the `X-API-KEY` header:

```
X-API-KEY: your-api-key-here
```

Note: The header name is case-sensitive and must be `X-API-KEY` (all caps).

### 3. Use CORS-Compatible Requests

Our API has been updated with comprehensive CORS support. Make sure your Custom GPT:

- Specifies `Content-Type: application/json` in requests
- Handles preflight OPTIONS requests automatically
- Sets the correct `X-API-KEY` header case

### 4. Implement Retry Logic

For increased reliability, you can implement retry logic in your Custom GPT:

```javascript
// Example retry logic (conceptual, not actual code)
async function fetchWithRetry(url, options, maxRetries = 3) {
  let lastError;
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await fetch(url, options);
    } catch (error) {
      lastError = error;
      // Wait before retrying (exponential backoff)
      await new Promise(r => setTimeout(r, Math.pow(2, i) * 1000));
    }
  }
  throw lastError;
}
```

### 5. Fallback Mechanisms

If direct API calls consistently fail, consider implementing fallback mechanisms:

1. **Webhook Integration**: Create a webhook service that acts as an intermediary between your Custom GPT and the Memory Hub.

2. **Alternative Domains**: Configure alternative domains or a proxy service if the primary domain is consistently unreachable.

3. **Offline Mode**: Implement offline mode functionality that gracefully handles API unavailability.

## Testing Your Integration

1. Start with the basic health check endpoint:
   ```
   GET /sys/health
   ```

2. Use the enhanced diagnostic endpoint to see detailed information:
   ```
   GET /sys/gpt-diagnostic
   ```

3. Check connectivity using a simple search:
   ```
   POST /search
   ```
   With body:
   ```json
   {
     "query": "test connectivity"
   }
   ```

4. If all of these tests fail, contact the API administrator for further assistance.

## Best Practices

1. **Log Failures**: Implement logging within your Custom GPT to track API connectivity issues.

2. **Graceful Degradation**: Design your Custom GPT to provide partial functionality even when API calls fail.

3. **Clear Error Messages**: Display clear, actionable error messages to users when API connectivity issues occur.

4. **Regular Testing**: Regularly test your integration to catch and address connectivity issues promptly.

---

For further assistance, please contact the API administrator.