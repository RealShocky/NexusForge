from fastapi import FastAPI, Request, Response, status, HTTPException, Depends, Form, Cookie, Body, Header
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, ConfigDict
import stripe
import logging
import os
import sys
import warnings
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm, SecurityScopes
from datetime import datetime, timedelta
from sqlalchemy import func

from database import get_db, Customer, User, init_db, AIModel, APIKey, Usage
from auth import (
    get_current_user, 
    get_current_active_user, 
    get_token,
    get_token_from_cookie,
    get_current_user_from_cookie
)
import admin
from admin import router as admin_router
import admin_routes
import auth_routes
import api_routes
from customers import router as customer_router
from payment_routes import router as payment_router
from account_routes import router as account_router

# Set up logging
logging.basicConfig(level=logging.INFO)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Suppress warnings
warnings.filterwarnings("ignore")

# Load environment variables (if .env file exists)
from dotenv import load_dotenv
load_dotenv()

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Initialize FastAPI app
app = FastAPI(
    title="NexusAI Forge",
    description="Enterprise AI API service with key management, rate limiting, and usage tracking",
    version="1.0.0",
    debug=True
)

# Explicitly initialize the database
init_db()

# Configure templates and static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Add custom filters for templates
def format_datetime(value, format="%Y-%m-%d"):
    """Format a datetime object to a string"""
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            pass
    return value.strftime(format)

def format_currency(value):
    """Format a currency value to 2 decimal places"""
    if value is None:
        return "0.00"
    try:
        # Convert cents to dollars
        if isinstance(value, int) and value > 100:
            value = value / 100.0
        return "{:.2f}".format(float(value))
    except (ValueError, TypeError):
        return "0.00"

templates.env.filters["format_datetime"] = format_datetime
templates.env.filters["format_currency"] = format_currency

# Middleware for security headers
class AddSecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
            
        async def send_wrapper(response):
            if response.get("type") == "http.response.start":
                headers = dict(response.get("headers", []))
                headers[b"X-Content-Type-Options"] = b"nosniff"
                headers[b"X-Frame-Options"] = b"DENY"
                headers[b"X-XSS-Protection"] = b"1; mode=block"
                headers[b"Strict-Transport-Security"] = b"max-age=31536000; includeSubDomains"
                # Updated CSP to allow all necessary external resources
                csp = (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline' https://js.stripe.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://cdn.tailwindcss.com; "
                    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://fonts.gstatic.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
                    "font-src 'self' 'unsafe-inline' data: https://fonts.gstatic.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://*.stripe.com; "
                    "img-src 'self' data: https:; "
                    "connect-src 'self' https://api.stripe.com; "
                    "frame-src 'self' https://js.stripe.com https://*.stripe.com https://*.stripe.network; "
                    "child-src 'self' https://js.stripe.com https://*.stripe.com https://*.stripe.network;"
                )
                headers[b"Content-Security-Policy"] = csp.encode()
                response["headers"] = [(k, v) for k, v in headers.items()]
            await send(response)
            
        return await self.app(scope, receive, send_wrapper)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add security headers middleware
app.add_middleware(AddSecurityHeadersMiddleware)

# Include routers from other modules
app.include_router(admin_router)
app.include_router(admin_routes.router)
app.include_router(auth_routes.router)
app.include_router(api_routes.router)
app.include_router(customer_router)
app.include_router(payment_router)
app.include_router(account_router)

# Import admin routes
from admin import (
    admin_dashboard,
    create_customer,
    sync_customer,
    view_customer,
    create_api_key,
    api_key_form,
    add_model_form,
    add_model,
    setup_routes as setup_admin_routes
)

# Setup admin routes
setup_admin_routes(app)

# Mount admin routes
app.get("/admin", response_class=HTMLResponse)(admin_dashboard)
app.post("/admin/customer/create")(create_customer)
app.post("/admin/customer/{customer_id}/sync")(sync_customer)
app.get("/admin/customer/{customer_id}")(view_customer)
app.get("/admin/api-key/create")(api_key_form)
app.post("/admin/api-key/create")(create_api_key)
app.get("/admin/model/add")(add_model_form)
app.post("/admin/model/add")(add_model)

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

# Landing page route
@app.get("/landing", response_class=HTMLResponse)
async def landing_page(request: Request):
    try:
        # Get all active Stripe products with their prices
        products = stripe.Product.list(limit=3, active=True)
        
        # Process products to format them for display
        formatted_products = []
        for product in products.get("data", []):
            # Get prices for this product
            prices = stripe.Price.list(product=product["id"], active=True, limit=1)
            price_data = prices.get("data", [])
            
            # Extract features from metadata or description
            features = []
            if "metadata" in product and "features" in product["metadata"]:
                # Try to get features from metadata if available
                features = product["metadata"]["features"].split(",")
            elif product.get("description"):
                # Otherwise parse from description
                features = [line.strip() for line in product.get("description", "").split("\n") if line.strip()]
            
            # Default features if none found
            if not features and product.get("name", "").lower() == "starter":
                features = [
                    "Up to 5 API keys",
                    "1M tokens per month",
                    "Basic analytics",
                    "Email support"
                ]
            elif not features and product.get("name", "").lower() == "professional":
                features = [
                    "Up to 20 API keys",
                    "10M tokens per month",
                    "Advanced analytics",
                    "Priority support",
                    "Custom rate limiting"
                ]
            elif not features and product.get("name", "").lower() == "enterprise":
                features = [
                    "Unlimited API keys",
                    "Custom token limits",
                    "Custom analytics",
                    "Dedicated support",
                    "SSO integration",
                    "On-premises deployment"
                ]
                
            # Format price display
            price_display = "Custom"
            price_interval = ""
            if price_data:
                price = price_data[0]
                if price.get("unit_amount"):
                    amount = price.get("unit_amount") / 100
                    price_display = f"${amount}"
                    
                if price.get("recurring") and price.get("recurring").get("interval"):
                    price_interval = f"/{price.get('recurring').get('interval')}"
            
            formatted_products.append({
                "id": product["id"],
                "name": product.get("name", "Unknown"),
                "price_display": price_display,
                "price_interval": price_interval,
                "features": features,
                "is_enterprise": product.get("name", "").lower() == "enterprise"
            })
        
        # Sort products by price (custom/enterprise last)
        formatted_products.sort(key=lambda p: 999999 if p["price_display"] == "Custom" else float(p["price_display"].replace("$", "")))
        
        return templates.TemplateResponse(
            "landing.html", 
            {
                "request": request,
                "products": formatted_products
            }
        )
    except Exception as e:
        # If there's an error, fall back to default hardcoded pricing
        logging.error(f"Error fetching Stripe products: {str(e)}")
        return templates.TemplateResponse("landing.html", {"request": request})

# Root route - no longer redirects to dashboard directly
@app.get("/")
async def root():
    return RedirectResponse(url="/landing")

# Customer-specific dashboard is now at /customer-dashboard/{customer_id}
@app.get("/customer-dashboard/{customer_id}", response_class=HTMLResponse)
async def customer_dashboard(
    request: Request, 
    customer_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Check if user is authenticated
    if not current_user:
        return RedirectResponse(url="/login")
        
    # Check if user has access to this customer
    if current_user.role != "admin" and (not current_user.customer_id or current_user.customer_id != customer_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this dashboard")
    
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Get API keys for this customer
    api_keys = db.query(APIKey).filter(APIKey.customer_id == customer_id).all()
    
    # Get available AI models
    models = db.query(AIModel).filter(AIModel.is_active == True).all()
    
    # Get usage data
    usage_data = {}
    
    # Calculate total tokens used in the last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    total_tokens = db.query(func.sum(Usage.tokens_used)).join(APIKey).filter(
        APIKey.customer_id == customer_id,
        Usage.timestamp >= thirty_days_ago
    ).scalar() or 0
    
    # Get usage by model
    model_usage = db.query(
        AIModel.name, 
        func.sum(Usage.tokens_used).label('tokens_used'),
        func.sum(Usage.cost).label('total_cost')
    ).join(
        Usage, Usage.model_id == AIModel.id
    ).join(
        APIKey, Usage.api_key_id == APIKey.id
    ).filter(
        APIKey.customer_id == customer_id,
        Usage.timestamp >= thirty_days_ago
    ).group_by(
        AIModel.name
    ).all()
    
    model_usage_data = [{"name": name, "tokens": tokens, "cost": cost} for name, tokens, cost in model_usage]
    
    # Get usage by day for the past 30 days
    daily_usage = []
    for i in range(30):
        day = datetime.utcnow() - timedelta(days=i)
        day_start = datetime(day.year, day.month, day.day, 0, 0, 0)
        day_end = datetime(day.year, day.month, day.day, 23, 59, 59)
        
        day_tokens = db.query(func.sum(Usage.tokens_used)).join(APIKey).filter(
            APIKey.customer_id == customer_id,
            Usage.timestamp >= day_start,
            Usage.timestamp <= day_end
        ).scalar() or 0
        
        daily_usage.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "tokens": day_tokens
        })
    
    # Reverse to show oldest to newest
    daily_usage.reverse()
    
    # Get API key usage
    key_usage = db.query(
        APIKey.name,
        func.sum(Usage.tokens_used).label('tokens_used')
    ).outerjoin(
        Usage, Usage.api_key_id == APIKey.id
    ).filter(
        APIKey.customer_id == customer_id,
        Usage.timestamp >= thirty_days_ago if Usage else True
    ).group_by(
        APIKey.id
    ).all()
    
    key_usage_data = [{"name": name, "tokens": tokens} for name, tokens in key_usage]
    
    # Prepare usage data for the template
    usage_data = {
        "total_tokens": total_tokens,
        "model_usage": model_usage_data,
        "daily_usage": daily_usage,
        "key_usage": key_usage_data
    }
    
    return templates.TemplateResponse(
        "dashboard.html", 
        {
            "request": request,
            "customer": customer,
            "api_keys": api_keys,
            "models": models,
            "usage_data": usage_data
        }
    )

# API key management
@app.post("/api-key")
async def create_api_key(request: CreateAPIKeyRequest, db: Session = Depends(get_db)):
    """Create a new API key for a customer"""
    logging.info(f"Creating API key for customer {request.customer_id}")
    try:
        # Check if customer exists
        customer = db.query(Customer).filter_by(id=request.customer_id).first()
        if not customer:
            logging.error(f"Customer {request.customer_id} not found")
            return JSONResponse(
                status_code=404,
                content={"error": "Customer not found"}
            )
        
        logging.info(f"Found customer {customer.id} ({customer.name})")
        
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
            logging.info(f"Created API key {api_key.id} for customer {customer.id}")
        except Exception as e:
            db.rollback()
            logging.error(f"Database error creating API key: {str(e)}")
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
        logging.error(f"Error creating API key: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/api-key/{key_id}/toggle")
async def toggle_api_key(key_id: int, db: Session = Depends(get_db)):
    """Toggle an API key's active status"""
    logging.info(f"Toggling API key {key_id}")
    try:
        key = db.query(APIKey).filter_by(id=key_id).first()
        if not key:
            logging.error(f"API key {key_id} not found")
            return JSONResponse(
                status_code=404,
                content={"error": "API key not found"}
            )
        
        key.is_active = not key.is_active
        db.commit()
        logging.info(f"Toggled API key {key_id} to {key.is_active}")
        return JSONResponse(
            status_code=200,
            content={
                "id": key.id,
                "is_active": key.is_active
            }
        )
    except Exception as e:
        db.rollback()
        logging.error(f"Error toggling API key: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# User API key management
@app.post("/api/keys/create", response_model=dict)
async def create_user_api_key(
    name: str = Form(...),
    rate_limit: int = Form(60),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Create a new API key for the current user"""
    
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        logging.info(f"Creating API key '{name}' for user {current_user.username}")
        
        # Check if user has a customer_id
        if current_user.customer_id is None:
            raise HTTPException(status_code=400, detail="User must be associated with a customer to create API keys")
            
        # Create API key
        import secrets
        api_key = APIKey(
            key=secrets.token_urlsafe(32),
            name=name,
            customer_id=current_user.customer_id,
            user_id=current_user.id,  # Associate with the current user
            rate_limit=rate_limit,
            allowed_models=[],
            is_active=True
        )
        
        db.add(api_key)
        db.commit()
        db.refresh(api_key)
        
        logging.info(f"Created API key {api_key.id} for user {current_user.username}")
        
        # Return the created key
        return {
            "success": True,
            "key": api_key.key,
            "name": api_key.name,
            "created_at": api_key.created_at.isoformat() if api_key.created_at else None
        }
    except Exception as e:
        logging.error(f"Error creating API key: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating API key: {str(e)}")

# Get user API keys
@app.get("/api/keys", response_model=list)
async def get_user_api_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get all API keys for the current user"""
    
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        # We want all keys that:
        # 1. Match the user's customer_id OR
        # 2. Match the user's id directly
        if current_user.customer_id is None:
            # Only get keys associated directly with the user
            api_keys = db.query(APIKey).filter(APIKey.user_id == current_user.id).all()
        else:
            # Get keys associated with the user's customer_id OR the user directly
            api_keys = db.query(APIKey).filter(
                (APIKey.customer_id == current_user.customer_id) | 
                (APIKey.user_id == current_user.id)
            ).all()
        
        # Return the API keys
        return [
            {
                "id": key.id,
                "key": key.key,
                "name": key.name,
                "created_at": key.created_at.isoformat() if key.created_at else None,
                "is_active": key.is_active
            }
            for key in api_keys
        ]
    except Exception as e:
        logging.error(f"Error retrieving API keys: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving API keys: {str(e)}")

# Delete API key
@app.delete("/api/keys/{key_id}", response_model=dict)
async def delete_api_key(
    key_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Delete an API key"""
    
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        # Find the API key - user can delete keys associated with their customer_id OR directly with them
        api_key = db.query(APIKey).filter(
            APIKey.key == key_id,
            ((APIKey.customer_id == current_user.customer_id) | (APIKey.user_id == current_user.id))
        ).first()
        
        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")
        
        # Delete the API key
        db.delete(api_key)
        db.commit()
        
        logging.info(f"Deleted API key {api_key.id} for user {current_user.username}")
        
        return {"success": True, "message": "API key deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error deleting API key: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting API key: {str(e)}")

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

# API endpoints for dashboard data
@app.get("/api/dashboard/{customer_id}")
async def dashboard_data(customer_id: int, db: Session = Depends(get_db)):
    """Get dashboard data for a customer"""
    try:
        logging.info(f"Getting dashboard data for customer {customer_id}")
        
        # Get customer
        customer = db.query(Customer).filter_by(id=customer_id).first()
        logging.info(f"Found customer: {customer}")
        
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        # Get API keys
        api_keys = db.query(APIKey).filter_by(customer_id=customer_id).all()
        logging.info(f"Found {len(api_keys)} API keys")
        
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
        
        logging.info(f"Usage stats: {usage_stats}")
        
        # Get usage data
        try:
            billing_service = BillingService(os.getenv("STRIPE_SECRET_KEY"))
            usage_summary = await billing_service.get_customer_usage_summary(db, customer_id)
            logging.info(f"Got usage summary: {usage_summary}")
        except Exception as e:
            logging.error(f"Error getting usage summary: {str(e)}")
            usage_summary = {}
        
        # Format usage data for chart
        today = datetime.utcnow()
        last_30_days = [(today - timedelta(days=x)).strftime('%Y-%m-%d') for x in range(30)]
        usage_data = [0] * 30  # Initialize with zeros
        
        # Convert usage summary to chart data
        if usage_summary:
            for i, date in enumerate(last_30_days):
                usage_data[i] = usage_summary.get(date, 0)
        
        return {
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
        
    except Exception as e:
        logging.exception(f"Error in dashboard data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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

# API endpoints for usage metrics
@app.get("/api/usage/{customer_id}")
def get_usage_metrics(
    customer_id: int,
    timeRange: str,
    db: Session = Depends(get_db)
):
    try:
        # Validate customer exists
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        # Calculate date range
        now = datetime.utcnow()
        if timeRange == "24h":
            start_date = now - timedelta(days=1)
        elif timeRange == "7d":
            start_date = now - timedelta(days=7)
        elif timeRange == "30d":
            start_date = now - timedelta(days=30)
        elif timeRange == "90d":
            start_date = now - timedelta(days=90)
        else:
            raise HTTPException(status_code=400, detail="Invalid time range")

        # Get customer's API keys
        api_key_ids = [key.id for key in customer.api_keys]
        
        # Query usage data
        usage_data = db.query(
            func.sum(Usage.tokens_used).label('total_tokens'),
            func.count().label('total_requests'),
            func.avg(Usage.response_time).label('average_latency')
        ).filter(
            Usage.api_key_id.in_(api_key_ids),
            Usage.timestamp >= start_date
        ).first()

        # Get daily usage
        daily_usage = db.query(
            func.date(Usage.timestamp).label('date'),
            func.sum(Usage.tokens_used).label('tokens'),
            func.count().label('requests')
        ).filter(
            Usage.api_key_id.in_(api_key_ids),
            Usage.timestamp >= start_date
        ).group_by(
            func.date(Usage.timestamp)
        ).all()

        # Format response
        response = {
            "total_tokens": usage_data.total_tokens or 0,
            "total_requests": usage_data.total_requests or 0,
            "average_latency": usage_data.average_latency or 0,
            "usage_by_day": [
                {
                    "date": day.date.strftime("%Y-%m-%d"),
                    "tokens": day.tokens,
                    "requests": day.requests
                }
                for day in daily_usage
            ]
        }

        return response

    except Exception as e:
        logging.error(f"Error fetching usage metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Payment management routes
@app.post("/setup-intent/{customer_id}")
async def create_setup_intent(customer_id: int, db: Session = Depends(get_db)):
    """Create a setup intent for adding a payment method"""
    try:
        # Get customer from database
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
            
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
        logging.info(f"Setting up payment for customer: {customer_id}")
        
        # Check if customer exists in Stripe
        stripe_customer_id = customer.stripe_customer_id
        if stripe_customer_id:
            try:
                # Verify the customer exists in Stripe
                stripe_customer = stripe.Customer.retrieve(stripe_customer_id)
                if hasattr(stripe_customer, 'deleted') and stripe_customer.deleted:
                    # Customer was deleted in Stripe, create a new one
                    stripe_customer_id = None
            except stripe.error.InvalidRequestError:
                # Customer doesn't exist in Stripe, create a new one
                stripe_customer_id = None
                
        # Create new Stripe customer if needed
        if not stripe_customer_id:
            logging.info(f"Creating new Stripe customer for {customer.name}")
            stripe_customer = stripe.Customer.create(
                name=customer.name,
                email=customer.email,
                description=f"Customer ID: {customer.id}"
            )
            stripe_customer_id = stripe_customer.id
            
            # Update the customer record
            customer.stripe_customer_id = stripe_customer_id
            db.commit()
            logging.info(f"Updated customer {customer.id} with new Stripe ID: {stripe_customer_id}")
        
        # Create setup intent using Stripe customer ID
        setup_intent = stripe.SetupIntent.create(
            customer=stripe_customer_id,
            payment_method_types=['card'],
            usage='off_session'  # Allow future off-session payments
        )
        
        logging.info(f"Setup intent created successfully: {setup_intent.id}")
        return {"client_secret": setup_intent.client_secret}
    except Exception as e:
        logging.error(f"Error creating setup intent: {str(e)}")
        logging.exception("Full setup intent error:")
        raise HTTPException(status_code=500, detail=f"Failed to create setup intent: {str(e)}")

@app.get("/setup-intent")
async def create_setup_intent_no_customer():
    """Create a setup intent without a customer (for testing)"""
    try:
        logging.info("Creating setup intent without customer")
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
        
        # Create setup intent without customer
        setup_intent = stripe.SetupIntent.create(
            payment_method_types=['card']
        )
        
        logging.info(f"Setup intent created successfully: {setup_intent.id}")
        return {"client_secret": setup_intent.client_secret}
    except Exception as e:
        logging.error(f"Error creating setup intent: {str(e)}")
        logging.exception("Full setup intent error:")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/setup-intent/1")  # Match the exact URL being called
async def create_setup_intent_simple():
    """Create a setup intent without requiring storage"""
    try:
        logging.info("Creating simple setup intent")
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
        
        # Create setup intent with minimal configuration
        setup_intent = stripe.SetupIntent.create(
            payment_method_types=['card'],
            usage='off_session'
        )
        
        # Add CORS headers explicitly
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }
        
        logging.info(f"Setup intent created successfully: {setup_intent.id}")
        return JSONResponse(
            content={"client_secret": setup_intent.client_secret},
            headers=headers
        )
    except Exception as e:
        logging.error(f"Error creating setup intent: {str(e)}")
        logging.exception("Full setup intent error:")
        raise HTTPException(status_code=400, detail=str(e))

@app.options("/setup-intent/1")
async def setup_intent_options():
    """Handle OPTIONS request for CORS"""
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }
    return JSONResponse(content={}, headers=headers)

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
        logging.error(f"Error getting payment methods: {e}")
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
            logging.error(f"Stripe error attaching payment method: {str(e)}")
            return JSONResponse(
                status_code=400,
                content={"error": str(e)}
            )
            
    except Exception as e:
        logging.error(f"Error attaching payment method: {str(e)}")
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

@app.get("/test-payment", response_class=HTMLResponse)
async def test_payment(request: Request):
    """Test payment page"""
    try:
        logging.info("Accessing test payment page")
        # Check if we're on HTTPS
        is_https = request.url.scheme == "https"
        if not is_https and not os.getenv("DEVELOPMENT_MODE", "false").lower() == "true":
            logging.warning("Stripe requires HTTPS in production. Redirecting to HTTPS.")
            return RedirectResponse(url=str(request.url.replace(scheme="https")))
            
        return templates.TemplateResponse(
            "test_payment.html",
            {
                "request": request,
                "stripe_public_key": os.getenv("STRIPE_PUBLIC_KEY"),
                "is_development": os.getenv("DEVELOPMENT_MODE", "false").lower() == "true"
            }
        )
    except Exception as e:
        logging.error(f"Error rendering test payment page: {str(e)}")
        logging.exception(e)
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "error_message": str(e)
            }
        )

@app.post("/create-payment-intent")
async def create_payment_intent(amount: dict):
    logging.info("=== Starting payment intent creation ===")
    logging.info(f"Received request with amount: {amount}")
    
    try:
        logging.info(f"Creating payment intent for amount: {amount}")
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
        
        # Log the API key being used (last 4 characters only)
        api_key = os.getenv("STRIPE_SECRET_KEY")
        logging.info(f"Using Stripe API key ending in: ...{api_key[-4:]}")
        
        # Convert amount to cents and create intent
        amount_cents = int(amount["amount"] * 100)
        logging.info(f"Converting ${amount['amount']} to {amount_cents} cents")
        
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            metadata={"integration_check": "accept_a_payment"}
        )
        
        logging.info(f"Payment intent created successfully: {intent.id}")
        logging.info(f"Payment intent status: {intent.status}")
        logging.info(f"Payment intent amount: ${intent.amount/100:.2f} USD")
        logging.info("=== Payment intent creation completed ===")
        
        return {"clientSecret": intent.client_secret}
    except Exception as e:
        logging.error("=== Payment intent creation failed ===")
        logging.error(f"Error creating payment intent: {str(e)}")
        logging.exception("Full payment intent error:")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks"""
    try:
        event = None
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature")
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, os.getenv("STRIPE_WEBHOOK_SECRET", "")
            )
        except ValueError as e:
            logging.error("Invalid payload")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            logging.error("Invalid signature")
            raise HTTPException(status_code=400, detail="Invalid signature")
        
        if event["type"] == "payment_intent.succeeded":
            payment_intent = event["data"]["object"]
            logging.info(f"Payment succeeded! Amount: ${payment_intent.amount/100:.2f} USD")
            logging.info(f"Payment ID: {payment_intent.id}")
            logging.info(f"Customer: {payment_intent.customer}")
        
        return {"status": "success"}
    except Exception as e:
        logging.error(f"Webhook error: {str(e)}")
        logging.exception("Full webhook error:")
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
