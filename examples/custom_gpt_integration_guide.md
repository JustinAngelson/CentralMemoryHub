# Custom GPT Integration Guide

This guide provides step-by-step instructions for integrating the Central Memory Hub with OpenAI's Custom GPTs.

## Prerequisites

1. You need an API key from the Memory Hub. Visit the API Keys page at https://memory-vault-angelson.replit.app/api-keys to create one.

2. Access to Custom GPT creation in ChatGPT Plus or Enterprise.

## Integration Steps

### 1. Create a New Custom GPT

1. Go to https://chat.openai.com/
2. Click on "Explore" or "Create" in the sidebar
3. Select "Create a GPT"
4. Fill in the basic information like name, description, and instructions

### 2. Configure the API Integration

1. In the GPT creation interface, click on "Configure"
2. Navigate to the "Actions" tab
3. Click "Add action"
4. Fill in the following details:
   - **Authentication**: API Key
   - **Auth Type**: Custom Header
   - **Secret Name**: Your API key will be stored as a variable with this name
   - **Custom Header Name**: `X-API-KEY` (case doesn't matter, can be `x-api-key` as well)

5. For the Schema URL, enter: `https://memory-vault-angelson.replit.app/openapi.json`

### 3. Important Notes About API Endpoints

The Memory Hub provides two distinct sets of endpoints:

1. `/api/...` endpoints - These are for UI usage and don't require authentication
2. `/agent/...` endpoints - These are for Custom GPT integration and require API key authentication

**Always use the `/agent/...` endpoints in your Custom GPT.** For example:
- Use `/agent/directory/hierarchy` (not `/api/directory/hierarchy`)
- Use `/agent/messages` (not `/api/messages`)

### 4. Testing the Integration

1. After setting up your Custom GPT, test the integration with simple commands:
   - "Search my memory for [topic]"
   - "Store this information in my memory: [content]"
   - "Show me all the agents in the directory"

2. If you encounter authentication errors:
   - Verify your API key is correct
   - Ensure the X-API-KEY header is being passed
   - Check that you're using the `/agent/...` endpoints, not the `/api/...` endpoints

3. Diagnostic Endpoints:
   - `/sys/health` - Check if the API is reachable and functioning
   - `/sys/gpt-diagnostic` - Get detailed connectivity information

### 5. Example Schema Configurations

```yaml
# Example of accessing the agent hierarchy
/agent/directory/hierarchy:
  get:
    description: Get agent hierarchy
    operationId: getAgentHierarchy
    security:
      - ApiKeyAuth: []
    responses:
      200:
        description: Successfully retrieved agent hierarchy
```

## Troubleshooting

### Common Issues and Solutions

1. **401 Unauthorized Error**
   - Ensure your API key is valid
   - Check that the X-API-KEY header is properly configured
   - Remember that header name is case-insensitive (X-API-KEY, x-api-key, etc. all work)

2. **Endpoint Not Found Error**
   - Verify you're using the correct endpoint path
   - Always use `/agent/...` endpoints, not `/api/...` endpoints

3. **Rate Limiting Issues**
   - Each API key has a rate limit (default is 100 requests per minute)
   - If you exceed this limit, you'll receive a 429 Too Many Requests error

4. **Schema Loading Failures**
   - Try refreshing the schema in the Custom GPT editor
   - Check if the schema URL is accessible from your network

## Advanced Integration

### OpenAI Function Calling Best Practices

When defining Custom GPT instructions for API interactions:

1. Always specify the correct operation ID when calling functions
2. Include all required parameters
3. Handle errors gracefully by checking response status codes
4. Use the correct endpoint path for each operation

### Maintaining Context Across Conversations

To maintain memory context across multiple conversations:

1. Store critical information using the memory endpoints
2. Use the search endpoint to retrieve relevant context
3. Leverage agent sessions to organize related conversations
4. Create and manage memory links to form knowledge graphs

By following these guidelines, your Custom GPT will successfully integrate with the Central Memory Hub and leverage its powerful memory and agent management capabilities.