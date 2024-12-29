# AI API Service

An enterprise-grade AI API service with built-in API key management, rate limiting, usage tracking, and a beautiful dashboard interface.

## Features

- **AI Models**
  - Support for multiple AI models
  - Hugging Face model integration
  - External API model integration
  - Configurable model settings
  - Pay-per-token pricing
  - Support for both local and remote models

- **API Key Management**
  - Secure key generation and storage
  - Customer-specific rate limits
  - Multi-tenant support
  - Easy key activation/deactivation
  - Model-specific access control

- **Dashboard**
  - Real-time usage statistics
  - Cost tracking and billing
  - API key management interface
  - Usage graphs and analytics
  - Per-model usage tracking

- **Rate Limiting**
  - Per-key rate limits
  - Configurable thresholds
  - Protection against abuse
  - Customizable rate limit settings

- **Usage Tracking**
  - Request counting
  - Token consumption
  - Cost calculation
  - Response time monitoring
  - OpenTelemetry integration
  - Per-model cost tracking

## Prerequisites

- Python 3.8+
- pip (Python package manager)
- SQLite3

## Installation


1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables in `.env`:
```env
STRIPE_SECRET_KEY=your_stripe_key
```

## Available Models

The service currently supports two types of models:

1. **Local Models (Hugging Face)**
   - Default: GPT-2
   - Locally hosted and processed
   - Lower latency
   - No external API costs

2. **External API Models**
   - Lawgent-thinking (Legal domain expert)
   - Accessed via external API
   - Pay-per-use pricing
   - Specialized capabilities

## Usage

1. Start the server:
```bash
python main.py
```

2. Create a customer:
```bash
curl -X POST "http://localhost:8000/customers" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Your Company",
    "email": "contact@company.com",
    "company": "Your Company Inc"
  }'
```

3. Create an API key:
```bash
curl -X POST "http://localhost:8000/api/keys" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_email": "contact@company.com",
    "name": "Production Key",
    "allowed_models": [1, 2]  # 1 for GPT-2, 2 for lawgent-thinking
  }'
```

4. Generate text using local model (GPT-2):
```bash
curl -X POST "http://localhost:8000/generate" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "text": "Your prompt here",
    "model_id": 1,
    "max_length": 100
  }'
```

5. Generate text using external API (lawgent-thinking):
```bash
curl -X POST "http://localhost:8000/generate" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "text": "What legal considerations should I keep in mind for my business?",
    "model_id": 2,
    "max_length": 100
  }'
```

6. View the dashboard:
```
http://localhost:8000/dashboard/{customer_id}
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/customers` | POST | Create a new customer |
| `/api/keys` | POST | Create a new API key |
| `/api/keys/{key_id}/toggle` | POST | Toggle API key status |
| `/generate` | POST | Generate text using AI |
| `/dashboard/{customer_id}` | GET | View customer dashboard |

## Response Format

### Create Customer
```json
{
  "id": 1,
  "name": "Your Company",
  "email": "contact@company.com",
  "company": "Your Company Inc",
  "created_at": "2024-01-01T00:00:00"
}
```

### Create API Key
```json
{
  "id": 1,
  "key": "generated_api_key",
  "name": "Production Key",
  "rate_limit": 60,
  "allowed_models": [1, 2]
}
```

### Generate Text
```json
{
  "response": "AI-generated text",
  "tokens_used": 100,
  "cost": 0.001
}
```

## Rate Limiting

- Default rate limit: 60 requests per minute per API key
- Customizable per API key
- Returns HTTP 429 when limit exceeded
- Separate tracking for each model

## Monitoring

The system uses OpenTelemetry for monitoring and includes:
- Request tracking
- Performance metrics
- Error logging
- Usage statistics
- Cost tracking
- Per-model usage analytics

## Security

- API key authentication required for all endpoints
- Secure key storage in SQLite database
- Rate limiting protection
- Input validation and sanitization
- Customer isolation
- Model access control

## Development

### Project Structure
```
.
├── main.py           # FastAPI application and routes
├── database.py       # Database models and operations
├── rate_limiter.py   # Rate limiting implementation
├── billing.py        # Billing and cost tracking
├── model_manager.py  # AI model management and integration
├── requirements.txt  # Python dependencies
├── .env             # Environment variables
└── README.md        # Documentation
```

### Adding New Models

1. Local Models (Hugging Face):
```python
model_config = {
    "model_path": "model_name_or_path",
    "preload": True  # Load model at startup
}
```

2. External API Models:
```python
model_config = {
    "api_url": "https://api.example.com/v1/completions",
    "api_key": "your_api_key",
    "model_name": "model_name",
    "preload": False
}
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Implement your feature
4. Add tests
5. Submit a pull request

## License

MIT License
