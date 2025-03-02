# NexusAI Forge API Examples

This directory contains example clients for interacting with the NexusAI Forge API. These examples demonstrate how to authenticate with API keys, generate text with AI models, and retrieve usage statistics.

## Available Examples

### Python Client (`python_client.py`)

A Python client that demonstrates:
- Authenticating with an API key
- Listing available models
- Generating text with a model
- Retrieving usage statistics

**Requirements:**
- Python 3.6+
- `requests` library

**Usage:**
```bash
# Install requirements
pip install requests

# Run the example (update API key first)
python python_client.py
```

### JavaScript Client (`javascript_client.js`)

A JavaScript client that can be used in both Node.js and browser environments:
- Demonstrates the same functionality as the Python client
- Uses modern JavaScript features (async/await)
- Exports the client class for integration in other projects

**Requirements for Node.js:**
- Node.js v18+ (for built-in fetch support)
- For older Node.js versions, install the `node-fetch` package

**Usage with Node.js:**
```bash
# For Node.js v18+
node javascript_client.js

# For older Node.js versions
npm install node-fetch
# Then uncomment the fetch import line in the file
node javascript_client.js
```

**Usage in Browser:**
```html
<script src="javascript_client.js"></script>
<script>
  const client = new NexusAIClient('your_api_key_here');
  // Use client methods...
</script>
```

## API Endpoints

These examples interact with the following API endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/models` | GET | List available models |
| `/api/v1/models/{model_id}/generate` | POST | Generate text using a model |
| `/api/v1/usage` | GET | Get usage statistics for your API key |

## Authentication

All examples use API key authentication via the `X-API-Key` header. You need to:

1. Create an API key in the NexusAI Forge dashboard
2. Replace `your_api_key_here` in the examples with your actual API key

## Security Notes

- Never expose your API key in client-side code in production
- For browser usage, implement a backend proxy to make API calls with your key
- Store API keys in environment variables or secure configuration storage
- Follow best practices for API key management as outlined in the NexusAI documentation
