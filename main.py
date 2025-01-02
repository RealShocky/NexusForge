import os
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import secrets
from sqlalchemy.orm import Session
from sqlalchemy import func
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from dotenv import load_dotenv
from contextlib import asynccontextmanager
import time
import httpx
import stripe

from fastapi import FastAPI, Request, Depends, Body, HTTPException, Header
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict
from database import get_db, Customer, APIKey, Usage, AIModel, init_db, engine, SessionLocal, Base
from rate_limiter import RateLimiter
from model_manager import ModelManager
from billing_service import BillingService
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up templates
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize database
Base.metadata.create_all(bind=engine)
init_db()  # Initialize default data if needed

# Initialize services
rate_limiter = RateLimiter()
billing_service = BillingService(os.getenv("STRIPE_SECRET_KEY"))

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Initialize OpenTelemetry
tracer_provider = TracerProvider()
otlp_exporter = OTLPSpanExporter(endpoint="http://localhost:4317")
span_processor = BatchSpanProcessor(otlp_exporter)
tracer_provider.add_span_processor(span_processor)
trace.set_tracer_provider(tracer_provider)
FastAPIInstrumentor.instrument_app(app)

# Security middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://js.stripe.com https://cdn.jsdelivr.net https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://js.stripe.com; "
        "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com https://js.stripe.com data: *; "
        "img-src 'self' data: https:; "
        "frame-src 'self' https://js.stripe.com; "
        "connect-src 'self' https://api.stripe.com https://merchant-ui-api.stripe.com;"
    )
    return response

# Request models
class CreateAPIKeyRequest(BaseModel):
    customer_id: int
    name: str
    model_config = ConfigDict(from_attributes=True)

class CreateCustomerRequest(BaseModel):
    name: str
    email: str
    company: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class ModelRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str
    provider: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    api_version: Optional[str] = None
    max_tokens: Optional[int] = 2000
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.9
    top_k: Optional[int] = 50

class Query(BaseModel):
    text: str
    max_length: Optional[int] = 100

class Document(BaseModel):
    text: str
    metadata: Optional[dict] = None

class GenerateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: int
    prompt: str
    max_length: Optional[int] = 100
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.9
    top_k: Optional[int] = 50

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Root route - redirect to dashboard
@app.get("/")
async def root(db: Session = Depends(get_db)):
    # Get the first customer (test customer) for demo
    customer = db.query(Customer).first()
    if customer:
        return RedirectResponse(url=f"/dashboard/{customer.id}")
    return {"status": "No customers found"}

# API key management
@app.post("/api-key")
async def create_api_key(request: CreateAPIKeyRequest, db: Session = Depends(get_db)):
    """Create a new API key for a customer"""
    logger.info(f"Creating API key for customer {request.customer_id}")
    try:
        # Check if customer exists
        customer = db.query(Customer).filter_by(id=request.customer_id).first()
        if not customer:
            logger.error(f"Customer {request.customer_id} not found")
            return JSONResponse(
                status_code=404,
                content={"error": "Customer not found"}
            )
        
        logger.info(f"Found customer {customer.id} ({customer.name})")
        
        # Create API key
        api_key = APIKey(
            key=secrets.token_urlsafe(32),
            name=request.name,
            customer_id=request.customer_id,
            rate_limit=60,
            allowed_models=[],
            is_active=True
        )
        
        db.add(api_key)
        try:
            db.commit()
            db.refresh(api_key)
            logger.info(f"Created API key {api_key.id} for customer {customer.id}")
        except Exception as e:
            db.rollback()
            logger.error(f"Database error creating API key: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": "Database error creating API key"}
            )
        
        return JSONResponse(
            status_code=200,
            content={
                "id": api_key.id,
                "key": api_key.key,
                "name": api_key.name,
                "customer_id": api_key.customer_id,
                "rate_limit": api_key.rate_limit
            }
        )
    except Exception as e:
        logger.error(f"Error creating API key: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/api-key/{key_id}/toggle")
async def toggle_api_key(key_id: int, db: Session = Depends(get_db)):
    """Toggle an API key's active status"""
    logger.info(f"Toggling API key {key_id}")
    try:
        key = db.query(APIKey).filter_by(id=key_id).first()
        if not key:
            logger.error(f"API key {key_id} not found")
            return JSONResponse(
                status_code=404,
                content={"error": "API key not found"}
            )
        
        key.is_active = not key.is_active
        db.commit()
        logger.info(f"Toggled API key {key_id} to {key.is_active}")
        return JSONResponse(
            status_code=200,
            content={
                "id": key.id,
                "is_active": key.is_active
            }
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error toggling API key: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

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

# Debug endpoints
@app.get("/debug/routes")
async def debug_routes():
    """List all registered routes"""
    routes = []
    for route in app.routes:
        routes.append({
            "path": route.path,
            "name": route.name,
            "methods": route.methods
        })
    return {"routes": routes}

# Model management
@app.post("/models")
async def add_model(request: ModelRequest, db: Session = Depends(get_db)):
    """Add a new AI model to the system"""
    try:
        model = ModelManager().add_model(
            request.name,
            request.provider,
            request.model_config,
            request.api_base,
            request.api_key,
            request.api_version,
            request.max_tokens,
            request.temperature,
            request.top_p,
            request.top_k
        )
        if model:
            return JSONResponse(
                status_code=200,
                content={
                    "id": model.id,
                    "name": model.name,
                    "description": model.description,
                    "provider": model.provider,
                    "api_base": model.api_base,
                    "api_key": model.api_key,
                    "api_version": model.api_version,
                    "max_tokens": model.max_tokens,
                    "temperature": model.temperature,
                    "top_p": model.top_p,
                    "top_k": model.top_k
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
        models = ModelManager().list_models(db)
        return JSONResponse(
            status_code=200,
            content=[{
                "id": model.id,
                "name": model.name,
                "description": model.description,
                "provider": model.provider,
                "api_base": model.api_base,
                "api_key": model.api_key,
                "api_version": model.api_version,
                "max_tokens": model.max_tokens,
                "temperature": model.temperature,
                "top_p": model.top_p,
                "top_k": model.top_k,
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
    """Dashboard page"""
    try:
        logger.info(f"Accessing dashboard for customer {customer_id}")
        
        # Get customer
        customer = db.query(Customer).filter_by(id=customer_id).first()
        logger.info(f"Found customer: {customer}")
        
        if not customer:
            logger.warning(f"Customer {customer_id} not found")
            return RedirectResponse(url="/")

        # Get API keys
        api_keys = db.query(APIKey).filter_by(customer_id=customer_id).all()
        logger.info(f"Found {len(api_keys)} API keys")
        
        # Calculate current month usage and cost
        start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        usage_stats = db.query(
            func.count(Usage.id).label('request_count'),
            func.coalesce(func.sum(Usage.cost), 0.0).label('total_cost'),
            func.coalesce(func.sum(Usage.tokens_used), 0).label('total_tokens')
        ).join(APIKey).filter(
            APIKey.customer_id == customer_id,
            Usage.timestamp >= start_of_month
        ).first()
        
        logger.info(f"Usage stats: {usage_stats}")
        
        # Get usage data
        try:
            billing_service = BillingService(os.getenv("STRIPE_SECRET_KEY"))
            usage_summary = await billing_service.get_customer_usage_summary(db, customer_id)
            logger.info(f"Got usage summary: {usage_summary}")
        except Exception as e:
            logger.error(f"Error getting usage summary: {str(e)}")
            usage_summary = {}
        
        # Format usage data for chart
        today = datetime.utcnow()
        last_30_days = [(today - timedelta(days=x)).strftime('%Y-%m-%d') for x in range(30)]
        usage_data = [0] * 30  # Initialize with zeros
        
        # Convert usage summary to chart data
        if usage_summary:
            for i, date in enumerate(last_30_days):
                usage_data[i] = usage_summary.get(date, 0)
        
        # Prepare template data
        template_data = {
            "request": request,
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "email": customer.email,
                "company": customer.company
            },
            "api_keys": [{
                "id": key.id,
                "name": key.name,
                "key": key.key,
                "rate_limit": key.rate_limit,
                "is_active": key.is_active,
                "created_at": key.created_at.strftime("%Y-%m-%d %H:%M:%S") if key.created_at else None
            } for key in api_keys],
            "usage_labels": last_30_days,
            "usage_data": usage_data,
            "stripe_public_key": os.getenv("STRIPE_PUBLIC_KEY", ""),
            "stripe_secret_key": os.getenv("STRIPE_SECRET_KEY", ""),
            "current_month_cost": float(usage_stats.total_cost if usage_stats and usage_stats.total_cost is not None else 0.0),
            "total_requests": int(usage_stats.request_count if usage_stats and usage_stats.request_count is not None else 0),
            "total_tokens": int(usage_stats.total_tokens if usage_stats and usage_stats.total_tokens is not None else 0)
        }
        
        logger.info(f"Template data: {template_data}")
        return templates.TemplateResponse("dashboard.html", template_data)
        
    except Exception as e:
        logger.exception(f"Error in dashboard: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Internal server error: {str(e)}"}
        )

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
        model = ModelManager().get_model(request.model_id)
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
        response = ModelManager().generate_response(
            request.prompt, 
            request.model_id,
            max_length=request.max_length,
            temperature=request.temperature,
            top_p=request.top_p,
            top_k=request.top_k
        )
        response_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Calculate cost
        tokens_used = ModelManager().calculate_tokens(request.prompt, request.model_id)
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

# Payment management routes
@app.post("/setup-intent/{customer_id}")
async def create_setup_intent(customer_id: int, db: Session = Depends(get_db)):
    """Create a setup intent for adding a payment method"""
    try:
        # Get customer
        customer = db.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            return JSONResponse(
                status_code=404,
                content={"error": "Customer not found"}
            )

        if not customer.stripe_customer_id:
            return JSONResponse(
                status_code=400,
                content={"error": "Customer does not have a Stripe account"}
            )

        try:
            # Create setup intent in Stripe
            setup_intent = stripe.SetupIntent.create(
                customer=customer.stripe_customer_id,
                payment_method_types=['card'],
            )
            
            return JSONResponse(
                status_code=200,
                content={"client_secret": setup_intent.client_secret}
            )
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating setup intent: {str(e)}")
            return JSONResponse(
                status_code=400,
                content={"error": str(e)}
            )
            
    except Exception as e:
        logger.error(f"Error creating setup intent: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"}
        )

@app.get("/payment-methods/{customer_id}")
async def get_payment_methods(customer_id: int, db: Session = Depends(get_db)):
    """Get all payment methods for a customer"""
    try:
        customer = db.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            return JSONResponse(
                status_code=404,
                content={"error": "Customer not found"}
            )
        
        # Initialize billing service
        billing_service = BillingService(os.getenv("STRIPE_SECRET_KEY"))
        
        # Get payment methods from Stripe
        methods = await billing_service.get_payment_methods(db, customer_id)
        
        # Return empty list if no methods found
        if not methods or not hasattr(methods, 'data'):
            return JSONResponse(
                status_code=200,
                content=[]
            )
            
        return JSONResponse(
            status_code=200,
            content=methods.data
        )
    except Exception as e:
        logger.error(f"Error getting payment methods: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/attach-payment-method/{customer_id}")
async def attach_payment_method(
    customer_id: int,
    payment_method_id: str = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    """Attach a payment method to a customer"""
    try:
        # Get customer
        customer = db.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            return JSONResponse(
                status_code=404,
                content={"error": "Customer not found"}
            )

        if not customer.stripe_customer_id:
            return JSONResponse(
                status_code=400,
                content={"error": "Customer does not have a Stripe account"}
            )

        try:
            # Attach payment method in Stripe
            payment_method = stripe.PaymentMethod.attach(
                payment_method_id,
                customer=customer.stripe_customer_id,
            )
            
            return JSONResponse(
                status_code=200,
                content={"payment_method": payment_method.id}
            )
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error attaching payment method: {str(e)}")
            return JSONResponse(
                status_code=400,
                content={"error": str(e)}
            )
            
    except Exception as e:
        logger.error(f"Error attaching payment method: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"}
        )

@app.get("/payment-history/{customer_id}")
async def get_payment_history(customer_id: int, db: Session = Depends(get_db)):
    """Get payment history for a customer"""
    try:
        billing_service = BillingService(os.getenv("STRIPE_SECRET_KEY"))
        history = await billing_service.get_payment_history(db, customer_id)
        return JSONResponse(status_code=200, content={"payments": history.data})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/setup-automatic-payments/{customer_id}")
async def setup_automatic_payments(customer_id: int, payment_method_id: str = Body(..., embed=True), db: Session = Depends(get_db)):
    """Set up automatic payments for a customer"""
    try:
        billing_service = BillingService(os.getenv("STRIPE_SECRET_KEY"))
        await billing_service.setup_automatic_payments(db, customer_id, payment_method_id)
        return JSONResponse(status_code=200, content={"message": "Automatic payments configured successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
