from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from database import AIModel
import torch
from transformers import AutoModel, AutoTokenizer, AutoModelForCausalLM
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ModelManager:
    def __init__(self, session: Session):
        self.loaded_models = {}
        self.session = session
        
    def add_model(self, name: str, description: str, model_type: str, config: Dict[str, Any], price_per_1k_tokens: float) -> Optional[AIModel]:
        """Add a new AI model to the system"""
        try:
            # Check if model already exists
            existing_model = self.session.query(AIModel).filter_by(name=name).first()
            if existing_model:
                logger.info(f"Model {name} already exists")
                return existing_model
            
            # Create new model
            model = AIModel(
                name=name,
                description=description,
                model_type=model_type,
                config=config,
                price_per_1k_tokens=price_per_1k_tokens
            )
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
            
            # Load the model if specified
            if config.get('preload', False):
                self.load_model(model.id, config)
            
            logger.info(f"Successfully added model {name}")
            return model
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error adding model: {str(e)}")
            raise
    
    def load_model(self, model_id: int, config: Dict[str, Any]):
        """Load a model into memory"""
        try:
            if model_id in self.loaded_models:
                logger.info(f"Model {model_id} already loaded")
                return self.loaded_models[model_id]
                
            model_type = config.get('model_type', 'huggingface')
            
            if model_type == 'huggingface':
                model_path = config.get('model_path')
                if not model_path:
                    raise ValueError("Model path not specified in config")
                    
                logger.info(f"Loading model {model_id} from {model_path}")
                model = AutoModelForCausalLM.from_pretrained(model_path)
                tokenizer = AutoTokenizer.from_pretrained(model_path)
                
                self.loaded_models[model_id] = {
                    'model': model,
                    'tokenizer': tokenizer,
                    'config': config
                }
                logger.info(f"Successfully loaded model {model_id}")
            elif model_type == 'external_api':
                logger.info(f"Setting up external API model {model_id}")
                self.loaded_models[model_id] = {
                    'config': config
                }
                logger.info(f"Successfully set up external API model {model_id}")
            else:
                raise ValueError(f"Unsupported model type: {model_type}")
                
            return self.loaded_models[model_id]
        except Exception as e:
            logger.error(f"Error loading model: {str(e)}")
            if model_type == 'external_api':
                # For external API models, we can continue even if loading fails
                self.loaded_models[model_id] = {
                    'config': config
                }
                return self.loaded_models[model_id]
            raise
    
    def list_models(self, active_only: bool = True) -> List[AIModel]:
        """List all available models"""
        try:
            query = self.session.query(AIModel)
            if active_only:
                query = query.filter_by(is_active=True)
            models = query.all()
            logger.info(f"Found {len(models)} models")
            return models
        except Exception as e:
            logger.error(f"Error listing models: {str(e)}")
            raise
    
    def get_model(self, model_id: int) -> Optional[AIModel]:
        """Get model by ID"""
        try:
            model = self.session.query(AIModel).filter_by(id=model_id).first()
            if not model:
                logger.warning(f"Model {model_id} not found")
                return None
            return model
        except Exception as e:
            logger.error(f"Error getting model: {str(e)}")
            raise
            
    def update_model(self, model_id: int, description: Optional[str] = None, price_per_1k_tokens: Optional[float] = None, is_active: Optional[bool] = None) -> Optional[AIModel]:
        """Update model details"""
        try:
            model = self.get_model(model_id)
            if not model:
                raise ValueError("Model not found")
                
            if description is not None:
                model.description = description
            if price_per_1k_tokens is not None:
                model.price_per_1k_tokens = price_per_1k_tokens
            if is_active is not None:
                model.is_active = is_active
                
            self.session.commit()
            logger.info(f"Successfully updated model {model_id}")
            return model
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error updating model: {str(e)}")
            raise
    
    def calculate_tokens(self, text: str, model_id: int) -> int:
        """Calculate the number of tokens in the input text"""
        try:
            model = self.session.query(AIModel).filter_by(id=model_id).first()
            if not model:
                raise ValueError("Model not found")
                
            model_type = model.model_type
            
            if model_type == 'external_api':
                # For external APIs, use a simple approximation
                # Most models use ~4 characters per token on average
                return len(text) // 4
            
            elif model_type == 'huggingface':
                if model_id not in self.loaded_models:
                    self.load_model(model_id, model.config)
                    
                tokenizer = self.loaded_models[model_id]['tokenizer']
                tokens = tokenizer.encode(text)
                return len(tokens)
            else:
                raise ValueError(f"Unsupported model type: {model_type}")
        except Exception as e:
            logger.error(f"Error calculating tokens: {str(e)}")
            raise
    
    def generate_response(self, text: str, model_id: int, max_length: int = 100):
        """Generate response using the specified model"""
        try:
            model = self.session.query(AIModel).filter_by(id=model_id).first()
            if not model:
                raise ValueError(f"Model {model_id} not found")
            
            model_type = model.model_type
            config = model.config
            
            if model_type == 'external_api':
                import requests
                
                api_url = config['api_url']
                api_key = config['api_key']
                
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
                
                data = {
                    'messages': [{'role': 'user', 'content': text}],
                    'model': config['model_name'],
                    'max_tokens': max_length,
                    'temperature': 0.7
                }
                
                logger.info(f"Making request to {api_url}")
                logger.info(f"Headers: {json.dumps(headers, indent=2)}")
                logger.info(f"Data: {json.dumps(data, indent=2)}")
                
                response = requests.post(api_url, headers=headers, json=data)
                logger.info(f"Response status: {response.status_code}")
                logger.info(f"Response headers: {json.dumps(dict(response.headers), indent=2)}")
                logger.info(f"Response text: {response.text}")
                
                if response.status_code == 200:
                    response_json = response.json()
                    if 'response' in response_json:  # Their custom format
                        return response_json['response']['content']
                    elif 'choices' in response_json:  # OpenAI format
                        return response_json['choices'][0]['message']['content']
                    else:
                        raise ValueError(f"Unexpected response format: {response_json}")
                else:
                    raise ValueError(f"API request failed: {response.text}")
            
            elif model_type == 'huggingface':
                if model_id not in self.loaded_models:
                    self.load_model(model_id, config)
                
                model_data = self.loaded_models[model_id]
                model = model_data['model']
                tokenizer = model_data['tokenizer']
                
                inputs = tokenizer(text, return_tensors="pt")
                outputs = model.generate(
                    inputs["input_ids"],
                    max_length=max_length,
                    num_return_sequences=1,
                    no_repeat_ngram_size=2
                )
                response = tokenizer.decode(outputs[0], skip_special_tokens=True)
                return response
            else:
                raise ValueError(f"Unsupported model type: {model_type}")
                
        except Exception as e:
            logger.error(f"Error generating response: {str(e)}")
            raise
