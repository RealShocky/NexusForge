import os
from typing import Dict, Any, Optional

# Environment variables
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-for-development")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///flows.db")

# Model provider configurations
MODEL_PROVIDERS = {
    "openai": {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        "models": ["gpt-3.5-turbo", "gpt-4", "gpt-4-turbo", "text-embedding-ada-002"]
    },
    "anthropic": {
        "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "base_url": os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com"),
        "models": ["claude-2", "claude-instant-1"]
    },
    "local": {
        "base_url": os.getenv("LOCAL_LLM_BASE", "http://localhost:8000"),
        "api_key": os.getenv("LOCAL_LLM_API_KEY", ""),
        "models": []  # Will be populated dynamically
    },
    "huggingface": {
        "api_key": os.getenv("HUGGINGFACE_API_KEY", ""),
        "base_url": os.getenv("HUGGINGFACE_API_BASE", "https://api.huggingface.co"),
        "models": ["gpt2", "bloom", "llama2", "mistral"]
    },
    "ollama": {
        "base_url": os.getenv("OLLAMA_API_BASE", "http://localhost:11434"),
        "models": []  # Will be populated dynamically
    }
}

# Default provider if none specified
DEFAULT_PROVIDER = "openai"

# Rate limiting
RATE_LIMIT_DEFAULT = 60  # requests per minute

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Provider settings getter functions
def get_openai_settings() -> Dict[str, Any]:
    """Get OpenAI settings from environment"""
    return {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        "models": MODEL_PROVIDERS["openai"]["models"]
    }

def get_anthropic_settings() -> Dict[str, Any]:
    """Get Anthropic settings from environment"""
    return {
        "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "base_url": os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com"),
        "models": MODEL_PROVIDERS["anthropic"]["models"]
    }

def get_huggingface_settings() -> Dict[str, Any]:
    """Get HuggingFace settings from environment"""
    return {
        "api_key": os.getenv("HUGGINGFACE_API_KEY", ""),
        "base_url": os.getenv("HUGGINGFACE_API_BASE", "https://api.huggingface.co"),
        "models": MODEL_PROVIDERS["huggingface"]["models"]
    }

def get_local_settings() -> Dict[str, Any]:
    """Get local LLM settings from environment"""
    return {
        "base_url": os.getenv("LOCAL_LLM_BASE", "http://localhost:8000"),
        "api_key": os.getenv("LOCAL_LLM_API_KEY", ""),
        "models": MODEL_PROVIDERS["local"]["models"]
    }

def get_ollama_settings() -> Dict[str, Any]:
    """Get Ollama settings from environment"""
    return {
        "base_url": os.getenv("OLLAMA_API_BASE", "http://localhost:11434"),
        "models": MODEL_PROVIDERS["ollama"]["models"]
    }
