from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict, List, Optional, Any
import time
import os
import uuid
import logging

from database import get_db, APIKey, Usage, AIModel, UsageRecord, User

router = APIRouter()

async def validate_api_key(x_api_key: str = Header(...), db: Session = Depends(get_db)):
    """
    Validate the API key provided in the request header.
    """
    api_key = db.query(APIKey).filter(APIKey.key == x_api_key, APIKey.is_active == True).first()
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )
    
    # Update last_used timestamp if the column exists
    try:
        api_key.last_used = datetime.utcnow()
        db.commit()
    except:
        # If the column doesn't exist yet, just skip updating it
        db.rollback()
    
    return api_key

@router.get("/api/v1/models")
async def list_models(
    api_key: APIKey = Depends(validate_api_key),
    db: Session = Depends(get_db)
):
    """
    List all available models and their configurations.
    """
    models = db.query(AIModel).filter(AIModel.is_active == True).all()
    
    # If allowed_models is specified for this API key, filter the models
    if api_key.allowed_models and len(api_key.allowed_models) > 0:
        models = [model for model in models if model.id in api_key.allowed_models]
    
    # Track this API call in usage records
    try:
        usage_record = UsageRecord(
            api_key_id=api_key.id,
            user_id=api_key.user_id,
            service="list_models",
            request_count=1,
            cost=0.0  # This endpoint is free
        )
        db.add(usage_record)
        db.commit()
    except:
        # If the table doesn't exist yet, just skip tracking
        db.rollback()
    
    return [
        {
            "id": model.id,
            "name": model.name,
            "description": model.description,
            "model_type": model.model_type,
            "price_per_1k_tokens": model.price_per_1k_tokens
        }
        for model in models
    ]

@router.post("/api/v1/models/{model_id}/generate")
async def generate_text(
    model_id: int,
    request_data: Dict[str, Any],
    api_key: APIKey = Depends(validate_api_key),
    db: Session = Depends(get_db)
):
    """
    Generate text using the specified model.
    """
    # Check if the model exists and is active
    model = db.query(AIModel).filter(AIModel.id == model_id, AIModel.is_active == True).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found or inactive")
    
    # Check if this API key is allowed to use this model
    if api_key.allowed_models and len(api_key.allowed_models) > 0 and model_id not in api_key.allowed_models:
        raise HTTPException(status_code=403, detail="This API key is not authorized to use this model")
    
    # Get parameters from request data
    prompt = request_data.get("prompt", "")
    max_tokens = request_data.get("max_tokens", 50)
    temperature = request_data.get("temperature", 0.7)
    
    # Use the appropriate model service
    try:
        from model_service import get_model_service
        
        start_time = time.time()
        model_service = get_model_service(model_id, db)
        
        # Generate text using the model service
        response = await model_service.generate_text(
            model_name=model.model_name,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            **request_data.get("additional_params", {})
        )
        
        # Calculate response time
        response_time = time.time() - start_time
        
        # Extract metrics from response
        text = response["text"]
        prompt_tokens = response["prompt_tokens"] 
        completion_tokens = response["completion_tokens"]
        total_tokens = response["total_tokens"]
        
        # Calculate cost based on model's price_per_1k_tokens
        cost = (total_tokens / 1000) * model.price_per_1k_tokens
        
        # Record the usage
        try:
            usage = Usage(
                api_key_id=api_key.id,
                model_id=model.id,
                request_type="generate",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                response_time=response_time,
                cost=cost
            )
            db.add(usage)
            
            # Also add to the UsageRecord table
            usage_record = UsageRecord(
                api_key_id=api_key.id,
                user_id=api_key.user_id,
                service=f"generate_{model_id}",
                request_count=1,
                cost=cost
            )
            db.add(usage_record)
            
            db.commit()
        except:
            # If the tables don't exist yet, just skip tracking
            db.rollback()
            
        return {
            "id": str(uuid.uuid4()),
            "model": model.name,
            "text": text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost": cost
        }
    
    except Exception as e:
        # Log the error
        logging.error(f"Error generating text: {str(e)}")
        
        # Return an error response
        raise HTTPException(status_code=500, detail=f"Error generating text: {str(e)}")

@router.get("/api/v1/usage")
async def get_usage(
    api_key: APIKey = Depends(validate_api_key),
    db: Session = Depends(get_db)
):
    """
    Get the usage data for a specific API key.
    """
    try:
        # Get usage from the Usage table
        usage = db.query(Usage).filter(Usage.api_key_id == api_key.id).all()
        
        # If the UsageRecord table exists, get data from there too
        usage_records = db.query(UsageRecord).filter(UsageRecord.api_key_id == api_key.id).all()
        
        # Combine the data
        usage_data = [
            {
                "timestamp": u.timestamp.isoformat(),
                "model_id": u.model_id,
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
                "total_tokens": u.total_tokens,
                "response_time": u.response_time,
                "cost": u.cost
            }
            for u in usage
        ]
        
        # Add usage records data if it exists
        try:
            usage_records_data = [
                {
                    "timestamp": r.timestamp.isoformat(),
                    "service": r.service,
                    "request_count": r.request_count,
                    "cost": r.cost
                }
                for r in usage_records
            ]
            
            # Return both types of usage data
            return {
                "usage": usage_data,
                "records": usage_records_data
            }
        except:
            # If UsageRecord table doesn't exist or has errors, just return Usage data
            return usage_data
    except:
        # If both tables don't exist or have errors, return empty data
        return []
