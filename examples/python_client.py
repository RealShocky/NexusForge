import requests
import json
import time

class NexusAIClient:
    """
    A Python client for the NexusAI Forge API.
    """
    def __init__(self, api_key, base_url="http://localhost:8000/api/v1"):
        """
        Initialize the NexusAI client.
        
        Args:
            api_key (str): Your NexusAI API key
            base_url (str): The base URL of the NexusAI API
        """
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
    
    def list_models(self):
        """
        Get a list of available models.
        
        Returns:
            list: A list of available models and their configurations
        """
        url = f"{self.base_url}/models"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    def generate_text(self, model_id, prompt, max_tokens=50, temperature=0.7):
        """
        Generate text using a specified model.
        
        Args:
            model_id (str): The ID of the model to use
            prompt (str): The prompt to generate text from
            max_tokens (int): Maximum number of tokens to generate
            temperature (float): Sampling temperature (0.0-1.0)
            
        Returns:
            dict: The model's response
        """
        url = f"{self.base_url}/models/{model_id}/generate"
        payload = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        response = requests.post(url, headers=self.headers, json=payload)
        response.raise_for_status()
        return response.json()
    
    def get_usage(self):
        """
        Get usage statistics for your API key.
        
        Returns:
            dict: Usage statistics
        """
        url = f"{self.base_url}/usage"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()


# Example usage
if __name__ == "__main__":
    # Replace with your actual API key
    API_KEY = "your_api_key_here"
    
    # Initialize the client
    client = NexusAIClient(API_KEY)
    
    try:
        # List available models
        print("Available models:")
        models = client.list_models()
        for model in models:
            print(f"- {model['name']} (ID: {model['id']}): {model['description']}")
        
        # Choose the first model from the list
        if models:
            model_id = models[0]["id"]
            
            # Generate text
            print("\nGenerating text...")
            response = client.generate_text(
                model_id=model_id,
                prompt="Write a short poem about artificial intelligence.",
                max_tokens=100
            )
            
            print("\nGenerated text:")
            for choice in response["choices"]:
                print(choice["text"])
            
            print("\nUsage:")
            print(f"Prompt tokens: {response['usage']['prompt_tokens']}")
            print(f"Completion tokens: {response['usage']['completion_tokens']}")
            print(f"Total tokens: {response['usage']['total_tokens']}")
            
            # Get usage statistics
            time.sleep(1)  # Wait a moment for usage to be recorded
            print("\nAPI Key usage statistics:")
            usage = client.get_usage()
            print(json.dumps(usage, indent=2))
            
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        print(f"Error: {str(e)}")
