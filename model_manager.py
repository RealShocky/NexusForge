from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from database import AIModel, SessionLocal
import torch
from transformers import AutoModel, AutoTokenizer, AutoModelForCausalLM
import logging
import json
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ModelManager:
    def __init__(self):
        self.models = {}
        self.tokenizers = {}
        self.logger = logging.getLogger(__name__)

    async def load_models(self):
        """Load all models from the database"""
        db = SessionLocal()
        try:
            # Create default model if no models exist
            models = db.query(AIModel).all()
            if not models:
                default_model = AIModel(
                    name="GPT-2 Small",
                    model_type="huggingface",
                    model_name="gpt2",
                    price_per_1k_tokens=0.01
                )
                db.add(default_model)
                db.commit()
                db.refresh(default_model)
                models = [default_model]

            # Load all models
            for model in models:
                try:
                    await self.load_model(model.id)
                except Exception as e:
                    self.logger.error(f"Failed to load model {model.id}: {e}")
        finally:
            db.close()

    async def load_model(self, model_id: int):
        """Load a specific model"""
        db = SessionLocal()
        try:
            model = db.query(AIModel).filter_by(id=model_id).first()
            if not model:
                raise ValueError(f"Model {model_id} not found")

            self.logger.info(f"Loading model {model_id} from {model.model_type}")
            
            if model.model_type == "huggingface":
                from transformers import AutoModelForCausalLM, AutoTokenizer
                
                self.logger.info(f"Loading model {model.model_name}")
                tokenizer = AutoTokenizer.from_pretrained(model.model_name)
                model_instance = AutoModelForCausalLM.from_pretrained(model.model_name)
                
                self.models[model_id] = model_instance
                self.tokenizers[model_id] = tokenizer
                
                self.logger.info(f"Successfully loaded model {model_id}")
            elif model.model_type == "custom":
                # For custom models, we'll just store the config
                self.logger.info(f"Setting up custom model {model.name}")
                self.models[model_id] = model.config
                
                # Use a basic tokenizer for custom models
                from transformers import AutoTokenizer
                self.tokenizers[model_id] = AutoTokenizer.from_pretrained("gpt2")
                
                self.logger.info(f"Successfully set up custom model {model_id}")
            else:
                raise ValueError(f"Unsupported model type: {model.model_type}")

        except Exception as e:
            self.logger.error(f"Error loading model {model_id}: {str(e)}")
            raise
        finally:
            db.close()

    async def unload_models(self):
        """Unload all models"""
        self.models.clear()
        self.tokenizers.clear()

    def add_model(self, model_name: str, model_type: str, price_per_1k_tokens: float) -> AIModel:
        """Add a new model to the database"""
        db = SessionLocal()
        try:
            model = AIModel(
                name=model_name,
                model_type=model_type,
                price_per_1k_tokens=price_per_1k_tokens
            )
            db.add(model)
            db.commit()
            db.refresh(model)
            return model
        finally:
            db.close()

    def get_model(self, model_id: int) -> Optional[AIModel]:
        """Get a model by ID"""
        db = SessionLocal()
        try:
            return db.query(AIModel).filter_by(id=model_id).first()
        finally:
            db.close()

    def list_models(self, db: Session) -> List[AIModel]:
        """List all available models"""
        return db.query(AIModel).all()

    def generate_response(self, prompt: str, model_id: int, max_length: int = 100,
                         temperature: float = 0.7, top_p: float = 0.9, top_k: int = 50) -> str:
        """Generate a response using the specified model"""
        if model_id not in self.models:
            raise ValueError(f"Model {model_id} not loaded")

        model = self.models[model_id]
        tokenizer = self.tokenizers[model_id]

        if isinstance(model, dict):  # Custom model
            # Handle custom model generation
            # This is a placeholder - implement your custom model logic here
            return f"Response from custom model: {prompt}"
        else:  # Huggingface model
            inputs = tokenizer(prompt, return_tensors="pt", padding=True, truncation=True)
            
            outputs = model.generate(
                inputs["input_ids"],
                max_length=max_length,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                pad_token_id=tokenizer.eos_token_id
            )
            
            response = tokenizer.decode(outputs[0], skip_special_tokens=True)
            return response[len(prompt):].strip()

    def calculate_tokens(self, text: str, model_id: int) -> int:
        """Calculate the number of tokens in the text"""
        if model_id not in self.tokenizers:
            raise ValueError(f"Tokenizer for model {model_id} not loaded")

        tokenizer = self.tokenizers[model_id]
        tokens = tokenizer(text)["input_ids"]
        return len(tokens)

async def main():
    model_manager = ModelManager()
    await model_manager.load_models()

if __name__ == "__main__":
    asyncio.run(main())
