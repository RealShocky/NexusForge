from fastapi import FastAPI, HTTPException, Depends, Request, Header, Body
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import secrets
from datetime import datetime, timedelta
import os
from sqlalchemy import func
from sqlalchemy.orm import Session
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from dotenv import load_dotenv

from database import get_db, Customer, APIKey, Usage, AIModel, init_db, engine, SessionLocal
from rate_limiter import RateLimiter
from billing import BillingService
from model_manager import ModelManager

# Load environment variables
load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize services
rate_limiter = RateLimiter()
billing_service = BillingService(os.getenv("STRIPE_SECRET_KEY"))

# Initialize model manager with a new session
db = SessionLocal()
model_manager = ModelManager(db)

# Request models
class CreateCustomerRequest(BaseModel):
    name: str
    email: str
    company: str

class CreateAPIKeyRequest(BaseModel):
    customer_email: str
    name: str
    allowed_models: List[int] = []

class ModelRequest(BaseModel):
    name: str
    description: str
    model_type: str
    config: dict
    price_per_1k_tokens: float

class Query(BaseModel):
    text: str
    max_length: Optional[int] = 100

class Document(BaseModel):
    text: str
    metadata: Optional[dict] = None

class GenerateRequest(BaseModel):
    text: str
    model_id: int
    max_length: Optional[int] = 100

# Customer management
@app.post("/customers")
async def create_customer(request: CreateCustomerRequest, db: Session = Depends(get_db)):
    """Create a new customer"""
    try:
        customer = await billing_service.create_customer(
            db,
            request.name,
            request.email,
            request.company
        )
        return JSONResponse(
            status_code=200,
            content={
                "id": customer.id,
                "name": customer.name,
                "email": customer.email,
                "company": customer.company,
                "created_at": str(customer.created_at)
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# API key management
@app.post("/api/keys")
async def create_api_key(request: CreateAPIKeyRequest, db: Session = Depends(get_db)):
    """Create a new API key for a customer"""
    try:
        # Get customer by email
        customer = db.query(Customer).filter_by(email=request.customer_email).first()
        if not customer:
            return JSONResponse(
                status_code=404,
                content={"error": "Customer not found"}
            )
            
        # Generate API key
        api_key = secrets.token_urlsafe(32)
        
        # Create new API key
        new_key = APIKey(
            key=api_key,
            customer_id=customer.id,
            name=request.name,
            rate_limit=60,
            allowed_models=request.allowed_models
        )
        db.add(new_key)
        db.commit()
        db.refresh(new_key)
        
        return JSONResponse(
            status_code=200,
            content={
                "id": new_key.id,
                "key": api_key,
                "name": new_key.name,
                "rate_limit": new_key.rate_limit,
                "allowed_models": new_key.allowed_models
            }
        )
    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/api/keys/{key_id}/toggle")
async def toggle_api_key(key_id: int, db: Session = Depends(get_db)):
    """Toggle an API key's active status"""
    try:
        key = db.query(APIKey).filter_by(id=key_id).first()
        if not key:
            return JSONResponse(
                status_code=404,
                content={"error": "API key not found"}
            )
        
        key.is_active = not key.is_active
        db.commit()
        return JSONResponse(
            status_code=200,
            content={
                "id": key.id,
                "is_active": key.is_active
            }
        )
    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# Model management
@app.post("/models")
async def add_model(request: ModelRequest, db: Session = Depends(get_db)):
    """Add a new AI model to the system"""
    try:
        model = model_manager.add_model(
            request.name,
            request.description,
            request.model_type,
            request.config,
            request.price_per_1k_tokens
        )
        if model:
            return JSONResponse(
                status_code=200,
                content={
                    "id": model.id,
                    "name": model.name,
                    "description": model.description,
                    "model_type": model.model_type,
                    "price_per_1k_tokens": model.price_per_1k_tokens
                }
            )
        else:
            return JSONResponse(
                status_code=500,
                content={"error": "Failed to create model"}
            )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/models")
async def list_models(db: Session = Depends(get_db)):
    """List all available models"""
    try:
        models = model_manager.list_models(db)
        return JSONResponse(
            status_code=200,
            content=[{
                "id": model.id,
                "name": model.name,
                "description": model.description,
                "model_type": model.model_type,
                "price_per_1k_tokens": model.price_per_1k_tokens,
                "is_active": model.is_active
            } for model in models]
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# Dashboard routes
@app.get("/dashboard/{customer_id}", response_class=HTMLResponse)
async def dashboard(request: Request, customer_id: int, db: Session = Depends(get_db)):
    """Render the dashboard for a customer"""
    try:
        customer = db.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "Customer not found"
            }, status_code=404)
        
        # Get API keys
        api_keys = db.query(APIKey).filter_by(customer_id=customer_id).all()
        
        # Calculate usage statistics
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        usage_query = db.query(Usage)\
            .join(Usage.api_key)\
            .filter(
                Usage.api_key.has(customer_id=customer_id),
                Usage.timestamp >= thirty_days_ago
            )
            
        total_cost = sum([usage.cost for usage in usage_query.all()])
        total_requests = usage_query.count()
        
        usage_stats = {
            "total_cost": total_cost,
            "total_requests": total_requests
        }
        
        # Get recent usage
        recent_usage = db.query(Usage)\
            .join(Usage.api_key)\
            .filter(Usage.api_key.has(customer_id=customer_id))\
            .order_by(Usage.timestamp.desc())\
            .limit(10)\
            .all()
        
        # Calculate usage over time
        usage_by_day = db.query(
            func.date(Usage.timestamp).label('date'),
            func.count(Usage.id).label('count')
        ).join(Usage.api_key)\
        .filter(
            Usage.api_key.has(customer_id=customer_id),
            Usage.timestamp >= thirty_days_ago
        ).group_by(func.date(Usage.timestamp))\
        .order_by('date')\
        .all()
        
        usage_dates = [str(day.date) for day in usage_by_day]
        usage_counts = [day.count for day in usage_by_day]
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "customer": customer,
            "api_keys": api_keys,
            "recent_usage": recent_usage,
            "usage_dates": usage_dates,
            "usage_counts": usage_counts,
            "current_month_cost": total_cost,
            "total_requests": total_requests
        })
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": str(e)
        }, status_code=500)

# API endpoints for model usage
@app.post("/generate")
async def generate_text(
    request: GenerateRequest = Body(...),
    api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db)
):
    """Generate text using a specific model"""
    try:
        # Validate API key and rate limit
        key_data = db.query(APIKey).filter_by(key=api_key).first()
        if not key_data or not key_data.is_active:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or inactive API key"}
            )
        
        # Check if model is allowed
        if request.model_id not in key_data.allowed_models and key_data.allowed_models:
            return JSONResponse(
                status_code=403,
                content={"error": "Model not allowed for this API key"}
            )
        
        if not rate_limiter.is_allowed(api_key, key_data.rate_limit):
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded"}
            )
        
        # Get model
        model = model_manager.get_model(request.model_id)
        if not model:
            return JSONResponse(
                status_code=404,
                content={"error": "Model not found"}
            )
            
        if not model.is_active:
            return JSONResponse(
                status_code=400,
                content={"error": "Model is not active"}
            )
        
        # Generate response
        start_time = datetime.utcnow()
        response = model_manager.generate_response(
            request.text, 
            request.model_id,
            max_length=request.max_length
        )
        response_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Calculate cost
        tokens_used = model_manager.calculate_tokens(request.text, request.model_id)
        cost = (tokens_used / 1000) * model.price_per_1k_tokens
        
        # Record usage
        usage = Usage(
            api_key_id=key_data.id,
            model_id=request.model_id,
            request_type="generate",
            tokens_used=tokens_used,
            response_time=response_time,
            cost=cost
        )
        db.add(usage)
        db.commit()
        
        return JSONResponse(
            status_code=200,
            content={
                "response": response,
                "tokens_used": tokens_used,
                "cost": cost
            }
        )
    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/query")
async def query(request: Query, api_key: str = Header(..., alias="X-API-Key"), db: Session = Depends(get_db)):
    try:
        # Validate API key and rate limit
        key_data = db.query(APIKey).filter_by(key=api_key).first()
        if not key_data or not key_data.is_active:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or inactive API key"}
            )
        
        if not rate_limiter.is_allowed(api_key, key_data.rate_limit):
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded"}
            )
        
        # Forward request to OpenWeb API
        headers = {
            "Authorization": f"Bearer {key_data.openweb_key}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{key_data.base_url}/query",
                headers=headers,
                json={"text": request.text}
            )
            
            if response.status_code != 200:
                return JSONResponse(
                    status_code=response.status_code,
                    content={"error": "Error from OpenWeb API"}
                )

        # Track usage
        usage = Usage(
            api_key=api_key,
            request_type="query",
            tokens_used=len(request.text.split()),  # Approximate
            response_time=response.elapsed.total_seconds()
        )
        db.add(usage)
        db.commit()

        return JSONResponse(
            status_code=200,
            content=response.json()
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/add-knowledge")
async def add_knowledge(
    documents: List[Document],
    request: Request,
    api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db)
):
    """Add documents to the knowledge base"""
    try:
        start_time = time.time()
        
        with tracer.start_as_current_span("add_knowledge") as span:
            global vector_store
            texts = [doc.text for doc in documents]
            metadatas = [doc.metadata for doc in documents]
            
            if vector_store is None:
                vector_store = Chroma.from_texts(
                    texts=texts,
                    embedding=embeddings,
                    metadatas=metadatas
                )
            else:
                vector_store.add_texts(texts=texts, metadatas=metadatas)
            
            # Record usage
            response_time = time.time() - start_time
            usage = Usage(
                api_key=api_key,
                endpoint="/add-knowledge",
                tokens_used=sum(len(text.split()) for text in texts),
                response_time=response_time
            )
            db.add(usage)
            db.commit()
            
            span.set_attribute("documents_added", len(texts))
            span.set_attribute("response_time", response_time)
        
        return JSONResponse(
            status_code=200,
            content={"status": "success", "message": f"Added {len(texts)} documents"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# Initialize OpenTelemetry
trace.set_tracer_provider(TracerProvider())
otlp_exporter = OTLPSpanExporter(endpoint="localhost:4317")
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))
tracer = trace.get_tracer(__name__)

# Initialize app
@app.on_event("startup")
async def startup():
    """Initialize the application"""
    try:
        # Initialize database
        init_db()
        
        # Create default model if it doesn't exist
        db = SessionLocal()
        try:
            # Check if default model exists
            default_model = db.query(AIModel).filter_by(name="GPT-2 Small").first()
            if not default_model:
                # Create default model
                default_model = AIModel(
                    name="GPT-2 Small",
                    description="OpenAI GPT-2 small model for text generation",
                    model_type="huggingface",
                    config={
                        "model_path": "gpt2",
                        "model_type": "huggingface",
                        "preload": True
                    },
                    price_per_1k_tokens=0.01
                )
                db.add(default_model)
                db.commit()
                db.refresh(default_model)
            
            # Load model
            model_manager.load_model(default_model.id, default_model.config)
            
        except Exception as e:
            print(f"Error initializing model: {str(e)}")
            raise
        finally:
            db.close()
            
    except Exception as e:
        print(f"Error during startup: {str(e)}")
        raise

# Initialize OpenTelemetry instrumentation
FastAPIInstrumentor.instrument_app(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
