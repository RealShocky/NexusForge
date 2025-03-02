import os
import json
import logging
import httpx
import asyncio
from typing import Dict, List, Any, Optional, Union
from sqlalchemy.orm import Session

from database import AIModel, get_db
from settings import MODEL_PROVIDERS

logger = logging.getLogger(__name__)

class ModelServiceException(Exception):
    """Exception raised for errors in the model service."""
    pass

class ModelService:
    """Base class for model service providers"""
    
    def __init__(self, provider: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.provider = provider
        self.api_key = api_key or MODEL_PROVIDERS.get(provider, {}).get("api_key", "")
        self.base_url = base_url or MODEL_PROVIDERS.get(provider, {}).get("base_url", "")
        
        if not self.api_key and provider not in ["local", "ollama"]:
            logger.warning(f"No API key configured for provider: {provider}")
            
        if not self.base_url:
            logger.warning(f"No base URL configured for provider: {provider}")
    
    async def generate_text(self, model_name: str, prompt: str, max_tokens: int = 100, 
                           temperature: float = 0.7, **kwargs) -> Dict[str, Any]:
        """Generate text using the specified model - to be implemented by subclasses"""
        raise NotImplementedError("Subclasses must implement generate_text method")
    
    async def get_embeddings(self, model_name: str, text: str) -> List[float]:
        """Get embeddings for the specified text - to be implemented by subclasses"""
        raise NotImplementedError("Subclasses must implement get_embeddings method")
    
    def count_tokens(self, text: str, model_name: str) -> int:
        """Count tokens in the text - to be implemented by subclasses"""
        raise NotImplementedError("Subclasses must implement count_tokens method")
    
    @staticmethod
    def get_service_for_model(model: AIModel) -> 'ModelService':
        """Get the appropriate service for a model"""
        # Check if model has specific overrides
        api_key = model.api_key or MODEL_PROVIDERS.get(model.provider, {}).get("api_key", "")
        base_url = model.base_url or MODEL_PROVIDERS.get(model.provider, {}).get("base_url", "")
        
        if model.provider == "openai":
            return OpenAIService(api_key=api_key, base_url=base_url)
        elif model.provider == "anthropic":
            return AnthropicService(api_key=api_key, base_url=base_url)
        elif model.provider == "huggingface":
            return HuggingFaceService(api_key=api_key, base_url=base_url)
        elif model.provider == "ollama":
            return OllamaService(base_url=base_url)
        elif model.provider == "local":
            return LocalService(api_key=api_key, base_url=base_url)
        else:
            raise ModelServiceException(f"Unsupported model provider: {model.provider}")


class OpenAIService(ModelService):
    """Service for OpenAI models"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__("openai", api_key, base_url)
    
    async def generate_text(self, model_name: str, prompt: str, max_tokens: int = 100, 
                           temperature: float = 0.7, **kwargs) -> Dict[str, Any]:
        """Generate text using OpenAI API"""
        try:
            if not self.api_key:
                raise ModelServiceException("OpenAI API key not configured")
            
            async with httpx.AsyncClient() as client:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }
                
                data = {
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    **kwargs
                }
                
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=60.0
                )
                
                if response.status_code != 200:
                    raise ModelServiceException(f"OpenAI API error: {response.text}")
                
                result = response.json()
                
                return {
                    "text": result["choices"][0]["message"]["content"],
                    "model": model_name,
                    "prompt_tokens": result["usage"]["prompt_tokens"],
                    "completion_tokens": result["usage"]["completion_tokens"],
                    "total_tokens": result["usage"]["total_tokens"]
                }
                
        except httpx.RequestError as e:
            raise ModelServiceException(f"Error calling OpenAI API: {str(e)}")
        except Exception as e:
            raise ModelServiceException(f"Error in OpenAI service: {str(e)}")
    
    async def get_embeddings(self, model_name: str, text: str) -> List[float]:
        """Get embeddings using OpenAI API"""
        try:
            if not self.api_key:
                raise ModelServiceException("OpenAI API key not configured")
            
            async with httpx.AsyncClient() as client:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }
                
                data = {
                    "model": model_name,
                    "input": text
                }
                
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    headers=headers,
                    json=data,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    raise ModelServiceException(f"OpenAI API error: {response.text}")
                
                result = response.json()
                
                return result["data"][0]["embedding"]
                
        except httpx.RequestError as e:
            raise ModelServiceException(f"Error calling OpenAI API: {str(e)}")
        except Exception as e:
            raise ModelServiceException(f"Error in OpenAI service: {str(e)}")
    
    def count_tokens(self, text: str, model_name: str) -> int:
        """Estimate token count for OpenAI models"""
        # Simple approximation - about 4 chars per token for English
        return len(text) // 4


class AnthropicService(ModelService):
    """Service for Anthropic models"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__("anthropic", api_key, base_url)
    
    async def generate_text(self, model_name: str, prompt: str, max_tokens: int = 100, 
                           temperature: float = 0.7, **kwargs) -> Dict[str, Any]:
        """Generate text using Anthropic API"""
        try:
            if not self.api_key:
                raise ModelServiceException("Anthropic API key not configured")
            
            async with httpx.AsyncClient() as client:
                headers = {
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01"
                }
                
                data = {
                    "model": model_name,
                    "prompt": f"\\n\\nHuman: {prompt}\\n\\nAssistant:",
                    "max_tokens_to_sample": max_tokens,
                    "temperature": temperature,
                    **kwargs
                }
                
                response = await client.post(
                    f"{self.base_url}/v1/complete",
                    headers=headers,
                    json=data,
                    timeout=60.0
                )
                
                if response.status_code != 200:
                    raise ModelServiceException(f"Anthropic API error: {response.text}")
                
                result = response.json()
                
                # Anthropic doesn't return token counts directly, so we estimate
                prompt_tokens = self.count_tokens(prompt, model_name)
                completion_tokens = self.count_tokens(result["completion"], model_name)
                
                return {
                    "text": result["completion"],
                    "model": model_name,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens
                }
                
        except httpx.RequestError as e:
            raise ModelServiceException(f"Error calling Anthropic API: {str(e)}")
        except Exception as e:
            raise ModelServiceException(f"Error in Anthropic service: {str(e)}")
    
    def count_tokens(self, text: str, model_name: str) -> int:
        """Estimate token count for Anthropic models"""
        # Simple approximation - about 4 chars per token for English
        return len(text) // 4


class HuggingFaceService(ModelService):
    """Service for Hugging Face models"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__("huggingface", api_key, base_url)
    
    async def generate_text(self, model_name: str, prompt: str, max_tokens: int = 100, 
                           temperature: float = 0.7, **kwargs) -> Dict[str, Any]:
        """Generate text using Hugging Face API"""
        try:
            if not self.api_key:
                raise ModelServiceException("Hugging Face API key not configured")
            
            async with httpx.AsyncClient() as client:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }
                
                data = {
                    "inputs": prompt,
                    "parameters": {
                        "max_new_tokens": max_tokens,
                        "temperature": temperature,
                        **kwargs
                    }
                }
                
                response = await client.post(
                    f"{self.base_url}/models/{model_name}",
                    headers=headers,
                    json=data,
                    timeout=60.0
                )
                
                if response.status_code != 200:
                    raise ModelServiceException(f"Hugging Face API error: {response.text}")
                
                result = response.json()
                
                # HF doesn't return token counts, so we estimate
                generated_text = result[0]["generated_text"][len(prompt):]
                prompt_tokens = self.count_tokens(prompt, model_name)
                completion_tokens = self.count_tokens(generated_text, model_name)
                
                return {
                    "text": generated_text,
                    "model": model_name,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens
                }
                
        except httpx.RequestError as e:
            raise ModelServiceException(f"Error calling Hugging Face API: {str(e)}")
        except Exception as e:
            raise ModelServiceException(f"Error in Hugging Face service: {str(e)}")
    
    def count_tokens(self, text: str, model_name: str) -> int:
        """Estimate token count for Hugging Face models"""
        # Simple approximation - about 4 chars per token for English
        return len(text) // 4


class OllamaService(ModelService):
    """Service for Ollama models"""
    
    def __init__(self, base_url: Optional[str] = None):
        super().__init__("ollama", None, base_url)
    
    async def generate_text(self, model_name: str, prompt: str, max_tokens: int = 100, 
                           temperature: float = 0.7, **kwargs) -> Dict[str, Any]:
        """Generate text using Ollama API"""
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    "Content-Type": "application/json"
                }
                
                data = {
                    "model": model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                        **kwargs
                    }
                }
                
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    headers=headers,
                    json=data,
                    timeout=60.0
                )
                
                if response.status_code != 200:
                    raise ModelServiceException(f"Ollama API error: {response.text}")
                
                result = response.json()
                
                # Get token counts if available, otherwise estimate
                prompt_tokens = result.get("prompt_eval_count", self.count_tokens(prompt, model_name))
                completion_tokens = result.get("eval_count", self.count_tokens(result["response"], model_name))
                
                return {
                    "text": result["response"],
                    "model": model_name,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens
                }
                
        except httpx.RequestError as e:
            raise ModelServiceException(f"Error calling Ollama API: {str(e)}")
        except Exception as e:
            raise ModelServiceException(f"Error in Ollama service: {str(e)}")
    
    def count_tokens(self, text: str, model_name: str) -> int:
        """Estimate token count for Ollama models"""
        # Simple approximation - about 4 chars per token for English
        return len(text) // 4
    
    async def list_models(self) -> List[Dict[str, Any]]:
        """List available models from Ollama"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/tags",
                    timeout=10.0
                )
                
                if response.status_code != 200:
                    raise ModelServiceException(f"Ollama API error: {response.text}")
                
                result = response.json()
                
                return result["models"]
                
        except httpx.RequestError as e:
            raise ModelServiceException(f"Error calling Ollama API: {str(e)}")
        except Exception as e:
            raise ModelServiceException(f"Error in Ollama service: {str(e)}")


class LocalService(ModelService):
    """Service for local API models"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__("local", api_key, base_url)
    
    async def generate_text(self, model_name: str, prompt: str, max_tokens: int = 100, 
                           temperature: float = 0.7, **kwargs) -> Dict[str, Any]:
        """Generate text using local API"""
        try:
            async with httpx.AsyncClient() as client:
                headers = {}
                
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                
                data = {
                    "model": model_name,
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    **kwargs
                }
                
                response = await client.post(
                    f"{self.base_url}/generate",
                    headers=headers,
                    json=data,
                    timeout=60.0
                )
                
                if response.status_code != 200:
                    raise ModelServiceException(f"Local API error: {response.text}")
                
                result = response.json()
                
                # Handle various response formats
                text = result.get("text", result.get("completion", result.get("response", "")))
                
                # Get token counts if available, otherwise estimate
                prompt_tokens = result.get("prompt_tokens", self.count_tokens(prompt, model_name))
                completion_tokens = result.get("completion_tokens", self.count_tokens(text, model_name))
                total_tokens = result.get("total_tokens", prompt_tokens + completion_tokens)
                
                return {
                    "text": text,
                    "model": model_name,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens
                }
                
        except httpx.RequestError as e:
            raise ModelServiceException(f"Error calling local API: {str(e)}")
        except Exception as e:
            raise ModelServiceException(f"Error in local service: {str(e)}")
    
    def count_tokens(self, text: str, model_name: str) -> int:
        """Estimate token count for local models"""
        # Simple approximation - about 4 chars per token for English
        return len(text) // 4

# Model service factory
def get_model_service(model_id: int, db: Session) -> ModelService:
    """Get the appropriate model service for a model ID"""
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    
    if not model:
        raise ModelServiceException(f"Model with ID {model_id} not found")
    
    return ModelService.get_service_for_model(model)
