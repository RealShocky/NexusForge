import requests
import json
import logging
from datetime import datetime
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"

def generate_unique_email():
    """Generate a unique email for testing"""
    unique_id = str(uuid.uuid4())[:8]
    return f"test_{unique_id}@example.com"

def test_create_customer():
    """Test customer creation"""
    url = f"{BASE_URL}/customers"
    data = {
        "name": "John Doe",
        "email": generate_unique_email(),
        "company": "Test Corp"
    }
    response = requests.post(url, json=data)
    logger.info(f"Create customer response: {response.status_code}")
    assert response.status_code == 200, f"Failed to create customer: {response.text}"
    return response.json()

def test_create_api_key(customer_email):
    """Test API key creation"""
    url = f"{BASE_URL}/api/keys"  # Fixed endpoint
    data = {
        "customer_email": customer_email,
        "name": "Test Key",
        "allowed_models": [1, 2]  # Allow both GPT-2 and LawGENT
    }
    response = requests.post(url, json=data)
    logger.info(f"Create API key response: {response.status_code}")
    assert response.status_code == 200, f"Failed to create API key: {response.text}"
    return response.json()

def test_list_models(api_key):
    """Test model listing"""
    url = f"{BASE_URL}/models"
    headers = {"X-API-Key": api_key}
    response = requests.get(url, headers=headers)
    logger.info(f"List models response: {response.status_code}")
    assert response.status_code == 200, f"Failed to list models: {response.text}"
    return response.json()

def test_generate_text(api_key):
    """Test text generation"""
    url = f"{BASE_URL}/generate"
    headers = {"X-API-Key": api_key}
    data = {
        "text": "Write a test message",
        "model_id": 1,  # Using GPT-2
        "max_length": 50
    }
    response = requests.post(url, json=data, headers=headers)
    logger.info(f"Generate text response: {response.status_code}")
    assert response.status_code == 200, f"Failed to generate text: {response.text}"
    return response.json()

def test_query(api_key):
    """Test query endpoint"""
    url = f"{BASE_URL}/query"
    headers = {"X-API-Key": api_key}
    data = {
        "text": "Test query",
        "max_length": 50
    }
    response = requests.post(url, json=data, headers=headers)
    logger.info(f"Query response: {response.status_code}")
    assert response.status_code == 200, f"Failed to query: {response.text}"
    return response.json()

def run_all_tests():
    """Run all API tests"""
    try:
        logger.info("Starting API tests...")
        
        # Test 1: Create customers
        customer1 = test_create_customer()
        logger.info(f"Created customer 1: {customer1}")
        
        # Create another customer with different data
        global BASE_URL
        BASE_URL = "http://localhost:8000"  # Reset URL
        data = {
            "name": "Jane Smith",
            "email": generate_unique_email(),
            "company": "Tech Corp"
        }
        response = requests.post(f"{BASE_URL}/customers", json=data)
        customer2 = response.json()
        logger.info(f"Created customer 2: {customer2}")
        
        # Test 2: Create API keys for both customers
        api_key1 = test_create_api_key(customer1["email"])
        logger.info(f"Created API key 1: {api_key1}")
        
        api_key2 = test_create_api_key(customer2["email"])
        logger.info(f"Created API key 2: {api_key2}")
        
        # Test 3: List models with first API key
        models = test_list_models(api_key1["key"])
        logger.info(f"Listed models: {models}")
        
        # Test 4: Generate text with both API keys
        gen1 = test_generate_text(api_key1["key"])
        logger.info(f"Generated text 1: {gen1}")
        
        gen2 = test_generate_text(api_key2["key"])
        logger.info(f"Generated text 2: {gen2}")
        
        # Test 5: Query with both API keys
        query1 = test_query(api_key1["key"])
        logger.info(f"Query 1: {query1}")
        
        query2 = test_query(api_key2["key"])
        logger.info(f"Query 2: {query2}")
        
        logger.info("All tests completed successfully!")
        
    except Exception as e:
        logger.error(f"Test failed: {str(e)}")
        raise

if __name__ == "__main__":
    run_all_tests()
