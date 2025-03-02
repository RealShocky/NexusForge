from fastapi import Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, text
import stripe
import os
from database import SessionLocal, Customer, User, APIKey, AIModel
from auth import get_current_user_from_cookie, get_admin_user
import logging
from datetime import datetime
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure templates
templates = Jinja2Templates(directory="templates")

# Add custom Jinja2 filters
def format_datetime(value, format="%Y-%m-%d %H:%M:%S"):
    """Convert a datetime object to a formatted string"""
    if not value:
        return "N/A"
    return value.strftime(format)

def format_currency(value):
    """Format a number as currency"""
    if not value:
        return "$0.00"
    return f"${value:.2f}"

templates.env.filters["format_datetime"] = format_datetime
templates.env.filters["format_currency"] = format_currency

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_example")

# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def admin_dashboard(
    request: Request, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Admin dashboard showing all customers"""
    
    # Check if user is authenticated and is admin
    if not current_user:
        return RedirectResponse(url="/login")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access admin dashboard")
    
    # Debug output
    logger.info(f"User: {current_user.username} role: {current_user.role}")
    
    try:
        customers = db.query(Customer).all()
        logger.info(f"Found {len(customers)} customers")
        
        # Use SQLAlchemy's func.count instead of raw SQL
        total_api_keys = db.query(func.count(APIKey.id)).scalar() or 0
        total_users = db.query(func.count(User.id)).scalar() or 0
        
        logger.info(f"API Keys: {total_api_keys}, Users: {total_users}")
        
        return templates.TemplateResponse(
            "admin.html",
            {
                "request": request, 
                "user": current_user, 
                "customers": customers,
                "total_api_keys": total_api_keys,
                "total_users": total_users
            }
        )
    except Exception as e:
        logger.error(f"Error in admin_dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

async def create_customer(
    name: str = Form(...),
    email: str = Form(...),
    company: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Create a new customer and their corresponding Stripe customer"""
    
    # Check if user is authenticated and is admin
    if not current_user:
        return RedirectResponse(url="/login")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to create customers")
    
    try:
        logger.info(f"Creating new customer: {name} ({email})")
        
        # Create Stripe customer first
        stripe_customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={
                "company": company
            }
        )
        
        # Create customer in database
        customer = Customer(
            name=name,
            email=email,
            company=company,
            stripe_customer_id=stripe_customer.id
        )
        
        db.add(customer)
        db.commit()
        db.refresh(customer)
        
        logger.info(f"Customer created: {customer.id} (Stripe ID: {stripe_customer.id})")
        return RedirectResponse(url="/admin", status_code=303)
    except Exception as e:
        logger.error(f"Error creating customer: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating customer: {str(e)}")

async def sync_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Sync a customer with Stripe (create Stripe customer if missing)"""
    
    # Check if user is authenticated and is admin
    if not current_user:
        return RedirectResponse(url="/login")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to sync customers")
    
    try:
        logger.info(f"Syncing customer {customer_id} with Stripe")
        
        # Get customer
        customer = db.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        
        # Check if customer has a Stripe customer ID
        if not customer.stripe_customer_id:
            logger.info(f"Customer {customer_id} has no Stripe customer ID, creating one")
            
            # Create Stripe customer
            stripe_customer = stripe.Customer.create(
                email=customer.email,
                name=customer.name,
                metadata={
                    "company": customer.company or ""
                }
            )
            
            # Update customer with Stripe ID
            customer.stripe_customer_id = stripe_customer.id
            db.commit()
            
            logger.info(f"Created Stripe customer: {stripe_customer.id}")
        
        return RedirectResponse(url="/admin", status_code=303)
    except Exception as e:
        logger.error(f"Error syncing customer: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error syncing customer: {str(e)}")

async def view_customer(
    customer_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """View customer details including Stripe info"""
    
    # Check if user is authenticated and is admin
    if not current_user:
        return RedirectResponse(url="/login")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to view customer details")
    
    try:
        logger.info(f"Viewing details for customer {customer_id}")
        
        # Get customer
        customer = db.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        
        # Get Stripe customer details if available
        stripe_details = None
        if customer.stripe_customer_id:
            try:
                stripe_customer = stripe.Customer.retrieve(customer.stripe_customer_id)
                stripe_details = {
                    "id": stripe_customer.id,
                    "name": stripe_customer.name,
                    "email": stripe_customer.email,
                    "created": datetime.fromtimestamp(stripe_customer.created).strftime("%Y-%m-%d %H:%M:%S"),
                    "default_source": stripe_customer.default_source,
                    "invoice_prefix": stripe_customer.invoice_prefix
                }
            except Exception as e:
                logger.error(f"Error retrieving Stripe customer: {str(e)}")
                stripe_details = {"error": str(e)}
        
        return templates.TemplateResponse(
            "customer_details.html",
            {
                "request": request,
                "customer": customer,
                "stripe_details": stripe_details
            }
        )
    except Exception as e:
        logger.error(f"Error viewing customer: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error viewing customer: {str(e)}")

# API Key management
async def create_api_key(
    customer_id: int = Form(...),
    name: str = Form(...),
    rate_limit: int = Form(60),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Create a new API key for a customer"""
    
    # Check if user is authenticated and is admin
    if not current_user:
        return RedirectResponse(url="/login")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to create API keys")
    
    try:
        logger.info(f"Creating API key for customer {customer_id}")
        
        # Check if customer exists
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            logger.error(f"Customer {customer_id} not found")
            raise HTTPException(status_code=404, detail="Customer not found")
        
        # Create API key
        import secrets
        api_key = APIKey(
            key=secrets.token_urlsafe(32),
            name=name,
            customer_id=customer_id,
            rate_limit=rate_limit,
            allowed_models=[],
            is_active=True
        )
        
        db.add(api_key)
        db.commit()
        db.refresh(api_key)
        
        logger.info(f"Created API key {api_key.id} for customer {customer.id}")
        
        # Return to admin dashboard
        return RedirectResponse(url="/admin", status_code=302)
    
    except Exception as e:
        logger.error(f"Error creating API key: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating API key: {str(e)}")

# API Key form
async def api_key_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Show form to create a new API key"""
    
    # Check if user is authenticated and is admin
    if not current_user:
        return RedirectResponse(url="/login")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to create API keys")
    
    customers = db.query(Customer).all()
    
    return templates.TemplateResponse(
        "admin_api_key_form.html",
        {"request": request, "user": current_user, "customers": customers}
    )

# Model management
async def add_model_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Show form to add a new AI model"""
    
    if not current_user:
        logger.warning("User not authenticated for add_model_form")
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user.role != "admin":
        logger.warning(f"User {current_user.username} is not an admin")
        raise HTTPException(status_code=403, detail="Not authorized to add models")
    
    logger.info(f"Admin user {current_user.username} accessing add_model_form")
    
    return templates.TemplateResponse(
        "admin_add_model.html",
        {"request": request, "current_user": current_user}
    )

async def add_model(
    name: str = Form(...),
    provider: str = Form(...),
    model_type: str = Form(...),
    model_name: str = Form(None),
    custom_model_name: str = Form(None),
    description: str = Form(""),
    price_per_1k_tokens: float = Form(0.0),
    context_length: int = Form(4096),
    base_url: str = Form(None),
    api_key: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Add a new model to the system"""
    
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to add models")
    
    try:
        logger.info(f"Adding new model: {name} (provider: {provider})")
        
        # Determine the actual model name (from dropdown or custom input)
        actual_model_name = model_name
        if model_name == "custom" or not model_name:
            actual_model_name = custom_model_name
            
        if not actual_model_name:
            raise HTTPException(status_code=400, detail="Model name is required")
        
        # Create model
        model = AIModel(
            name=name,
            provider=provider,
            model_type=model_type,
            model_name=actual_model_name,
            description=description,
            price_per_1k_tokens=price_per_1k_tokens,
            context_length=context_length,
            base_url=base_url if base_url else None,
            api_key=api_key if api_key else None,
            created_by=current_user.id,
            config={
                "provider": provider,
                "model_type": model_type,
                "base_url": base_url
            }
        )
        
        db.add(model)
        db.commit()
        db.refresh(model)
        
        logger.info(f"Added new model {model.id}: {model.name}")
        
        # Redirect to admin dashboard
        return RedirectResponse(url="/admin", status_code=303)
    
    except Exception as e:
        logger.error(f"Error adding model: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error adding model: {str(e)}")

from fastapi import APIRouter
router = APIRouter()

@router.get("/admin/models")
async def list_models(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """List all AI models with management options"""
    
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to view models")
    
    # Get all models
    models = db.query(AIModel).order_by(AIModel.id).all()
    
    # Get environment settings
    from settings import (
        get_openai_settings,
        get_anthropic_settings,
        get_huggingface_settings,
        get_local_settings,
        get_ollama_settings
    )
    
    env = {
        "openai": get_openai_settings(),
        "anthropic": get_anthropic_settings(),
        "huggingface": get_huggingface_settings(),
        "local": get_local_settings(),
        "ollama": get_ollama_settings()
    }
    
    return templates.TemplateResponse(
        "admin_models.html",
        {
            "request": request,
            "current_user": current_user,
            "models": models,
            "env": env
        }
    )

@router.get("/admin/customers")
async def list_customers(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """List all customers with management options"""
    
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to view customers")
    
    # Get all customers
    customers = db.query(Customer).order_by(Customer.id).all()
    
    return templates.TemplateResponse(
        "admin_customers.html",
        {
            "request": request,
            "current_user": current_user,
            "customers": customers,
            "section": "customers"
        }
    )

@router.get("/admin/api-keys")
async def list_api_keys(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """List all API keys with management options"""
    
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to view API keys")
    
    # Get all API keys
    api_keys = db.query(APIKey).order_by(APIKey.id).all()
    
    # Get all customers for the dropdown
    customers = db.query(Customer).order_by(Customer.name).all()
    
    return templates.TemplateResponse(
        "admin_api_keys.html",
        {
            "request": request,
            "current_user": current_user,
            "api_keys": api_keys,
            "customers": customers,
            "section": "api_keys"
        }
    )

@router.get("/admin/api-key/{key_id}/toggle")
async def toggle_api_key_status(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Toggle an API key's active status"""
    
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to manage API keys")
    
    api_key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    
    # Toggle status
    api_key.is_active = not api_key.is_active
    db.commit()
    
    return RedirectResponse(url="/admin/api-keys", status_code=303)

@router.get("/admin/stripe-products")
async def admin_stripe_products(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Admin view for managing Stripe products"""
    
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access admin dashboard")
    
    try:
        # Get all active Stripe products with their prices
        products = stripe.Product.list(limit=100, active=True)
        
        # Add pricing info to each product
        for product in products:
            product_id = product["id"]
            product["prices"] = stripe.Price.list(product=product_id, active=True)["data"]
        
        return templates.TemplateResponse(
            "admin_stripe_products.html",
            {
                "request": request,
                "current_user": current_user,
                "products": products.get("data", []),
                "section": "stripe_products"
            }
        )
    except Exception as e:
        logger.error(f"Error retrieving Stripe products: {str(e)}")
        # Still render the template but with an error message
        return templates.TemplateResponse(
            "admin_stripe_products.html",
            {
                "request": request,
                "current_user": current_user,
                "products": [],
                "error": str(e),
                "section": "stripe_products"
            }
        )

@router.get("/admin/usage")
async def admin_usage(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Admin view for usage analytics"""
    
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access admin dashboard")
    
    try:
        # Get usage statistics
        # This would be replaced with actual queries in a production environment
        customers = db.query(Customer).all()
        
        # Placeholder statistics data - would be replaced with actual DB queries
        total_requests = 0
        total_tokens = 0
        total_cost = 0
        active_customers = 0
        
        for customer in customers:
            # This is placeholder logic - would need actual usage tracking
            customer.requests = 0  # Placeholder
            customer.tokens = customer.requests * 0  # Placeholder
            customer.cost = customer.tokens * 0.00002  # Placeholder cost
            customer.last_active = datetime.now()  # Placeholder
            
            total_requests += customer.requests
            total_tokens += customer.tokens
            total_cost += customer.cost
            
            # Count customers active in the last 7 days
            if (datetime.now() - customer.last_active).days < 7:
                active_customers += 1
        
        return templates.TemplateResponse(
            "admin_usage.html",
            {
                "request": request,
                "current_user": current_user,
                "customers": customers,
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "total_cost": total_cost,
                "active_customers": active_customers,
                "section": "usage"
            }
        )
    except Exception as e:
        logger.error(f"Error retrieving usage data: {str(e)}")
        # Still render the template but with an error message
        return templates.TemplateResponse(
            "admin_usage.html",
            {
                "request": request,
                "current_user": current_user,
                "customers": [],
                "error": str(e),
                "section": "usage"
            }
        )

@router.get("/admin/settings")
async def admin_settings(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Admin view for system settings"""
    
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access admin dashboard")
    
    try:
        # Get all models for the dropdown
        models = db.query(AIModel).all()
        
        # Get environment settings
        from settings import (
            get_openai_settings,
            get_anthropic_settings,
            get_huggingface_settings,
            get_local_settings,
            get_ollama_settings
        )
        
        env = {
            "openai": get_openai_settings(),
            "anthropic": get_anthropic_settings(),
            "huggingface": get_huggingface_settings(),
            "local": get_local_settings(),
            "ollama": get_ollama_settings()
        }
        
        # Mock settings data - would be loaded from DB or environment in production
        settings = {
            "app_name": "NexusAI Forge",
            "support_email": "support@example.com",
            "default_model": models[0].id if models else None,
            "registration_enabled": True,
            "stripe_public_key": os.getenv("STRIPE_PUBLIC_KEY", ""),
            "stripe_secret_key": "sk_test_*********************",
            "default_currency": "usd",
            "markup_percentage": 20,
            "jwt_secret": "secret_*********************",
            "token_expiry": 24,
            "enable_rate_limiting": True,
            "rate_limit": 60,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_username": "user@example.com",
            "smtp_password": "pass_*********************",
            "smtp_tls": True,
            "log_level": "INFO",
            "log_to_file": True,
            "log_file_path": "logs/app.log",
            "log_rotation": True
        }
        
        return templates.TemplateResponse(
            "admin_settings.html",
            {
                "request": request,
                "current_user": current_user,
                "settings": settings,
                "models": models,
                "env": env,
                "section": "settings"
            }
        )
    except Exception as e:
        logger.error(f"Error retrieving settings: {str(e)}")
        # Still render the template but with an error message
        return templates.TemplateResponse(
            "admin_settings.html",
            {
                "request": request,
                "current_user": current_user,
                "settings": {},
                "models": [],
                "env": {},
                "error": str(e),
                "section": "settings"
            }
        )

@router.get("/admin/stripe-product/{product_id}")
async def view_stripe_product(
    product_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie)
):
    """View and manage details of a specific Stripe product"""
    
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access admin dashboard")
    
    try:
        # Get product details from Stripe
        product = stripe.Product.retrieve(product_id)
        
        # Get all prices for this product
        prices = stripe.Price.list(product=product_id, active=None, limit=100)
        
        # Get subscriptions for this product (this is a simplified approach)
        # In a real app, you would need to filter by price IDs related to this product
        subscriptions = []
        try:
            subs = stripe.Subscription.list(limit=100)
            for sub in subs.get('data', []):
                # Check if any item in the subscription is for this product
                for item in sub.get('items', {}).get('data', []):
                    price = item.get('price', {})
                    if price and price.get('product') == product_id:
                        # Add subscription with some useful info
                        status_colors = {
                            'active': 'success',
                            'past_due': 'warning',
                            'unpaid': 'danger',
                            'canceled': 'secondary',
                            'incomplete': 'info',
                            'incomplete_expired': 'danger',
                            'trialing': 'primary',
                            'paused': 'warning'
                        }
                        
                        subscriptions.append({
                            'id': sub.get('id'),
                            'customer': sub.get('customer'),
                            'status': sub.get('status'),
                            'status_color': status_colors.get(sub.get('status'), 'secondary'),
                            'current_period_start': datetime.fromtimestamp(sub.get('current_period_start', 0)),
                            'current_period_end': datetime.fromtimestamp(sub.get('current_period_end', 0)),
                            'amount': item.get('price', {}).get('unit_amount', 0) / 100
                        })
                        break
        except Exception as e:
            logger.error(f"Error retrieving subscriptions: {str(e)}")
        
        # Convert timestamps to datetime objects for the template
        if product.get('created'):
            product['created'] = datetime.fromtimestamp(product.get('created', 0))
            
        return templates.TemplateResponse(
            "admin_stripe_product_detail.html", 
            {
                "request": request,
                "current_user": current_user,
                "product": product,
                "prices": prices.get('data', []),
                "subscriptions": subscriptions,
                "section": "stripe_products"
            }
        )
    except Exception as e:
        logger.error(f"Error retrieving Stripe product details: {str(e)}")
        return templates.TemplateResponse(
            "admin_stripe_product_detail.html",
            {
                "request": request, 
                "current_user": current_user,
                "error": f"Error retrieving product: {str(e)}",
                "product": {"id": product_id, "name": "Unknown Product"},
                "prices": [],
                "subscriptions": [],
                "section": "stripe_products"
            }
        )

@router.get("/admin/models")
async def list_models(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """List all AI models with management options"""
    
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to view models")
    
    # Get all models
    models = db.query(AIModel).order_by(AIModel.id).all()
    
    # Get environment settings
    from settings import (
        get_openai_settings,
        get_anthropic_settings,
        get_huggingface_settings,
        get_local_settings,
        get_ollama_settings
    )
    
    env = {
        "openai": get_openai_settings(),
        "anthropic": get_anthropic_settings(),
        "huggingface": get_huggingface_settings(),
        "local": get_local_settings(),
        "ollama": get_ollama_settings()
    }
    
    return templates.TemplateResponse(
        "admin_models.html",
        {
            "request": request,
            "current_user": current_user,
            "models": models,
            "env": env
        }
    )

@router.get("/admin/model/{model_id}/toggle")
async def toggle_model_status(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Toggle a model's active status"""
    
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to modify models")
    
    # Get the model
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    # Toggle status
    model.is_active = not model.is_active
    db.commit()
    
    logger.info(f"Model {model.id} ({model.name}) status toggled to {model.is_active}")
    
    return RedirectResponse(url="/admin/models", status_code=303)

@router.get("/admin/model/{model_id}/test")
async def test_model(
    request: Request,
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Test a model with a simple prompt"""
    
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to test models")
    
    # Get the model
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    test_results = None
    error_message = None
    
    # Test prompt
    prompt = "Hello, please respond with a simple greeting."
    
    if request.query_params.get("run") == "true":
        try:
            # Import the model service
            from model_service import get_model_service
            
            # Get model service
            model_service = get_model_service(model_id, db)
            
            # Test the model
            result = await model_service.generate_text(
                model_name=model.model_name,
                prompt=prompt,
                max_tokens=50
            )
            
            test_results = {
                "prompt": prompt,
                "response": result["text"],
                "tokens": result["total_tokens"],
                "latency": f"{result.get('latency', 0):.2f}s"
            }
            
        except Exception as e:
            logger.error(f"Error testing model {model.id}: {str(e)}")
            error_message = str(e)
    
    return templates.TemplateResponse(
        "admin_test_model.html",
        {
            "request": request,
            "current_user": current_user,
            "model": model,
            "test_results": test_results,
            "error_message": error_message,
            "prompt": prompt
        }
    )

@router.get("/admin/model/{model_id}/edit")
async def edit_model_form(
    request: Request,
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Show form to edit an existing AI model"""
    
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to edit models")
    
    # Get the model
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    logger.info(f"Admin user {current_user.username} accessing edit form for model {model.id}")
    
    return templates.TemplateResponse(
        "admin_edit_model.html",
        {
            "request": request,
            "current_user": current_user,
            "model": model
        }
    )

@router.post("/admin/model/{model_id}/edit")
async def edit_model(
    model_id: int,
    name: str = Form(...),
    description: str = Form(""),
    price_per_1k_tokens: float = Form(0.0),
    is_active: bool = Form(False),
    context_length: int = Form(4096),
    base_url: str = Form(None),
    api_key: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Update an existing model"""
    
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to modify models")
    
    # Get the model
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    try:
        # Update model fields
        model.name = name
        model.description = description
        model.price_per_1k_tokens = price_per_1k_tokens
        model.is_active = is_active
        model.context_length = context_length
        
        # Only update these if provided
        if base_url:
            model.base_url = base_url
        
        if api_key:
            model.api_key = api_key
        
        db.commit()
        
        logger.info(f"Model {model.id} ({model.name}) updated")
        
        return RedirectResponse(url="/admin/models", status_code=303)
    
    except Exception as e:
        logger.error(f"Error updating model {model.id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating model: {str(e)}")

@router.post("/admin/stripe-product/{product_id}/update")
async def update_stripe_product(
    product_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Update a Stripe product's metadata/features"""
    
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to update products")
    
    try:
        form_data = await request.form()
        name = form_data.get("name")
        description = form_data.get("description", "")
        features = form_data.get("features", "")
        
        # Update the product in Stripe
        stripe.Product.modify(
            product_id,
            name=name,
            description=description,
            metadata={
                "features": features
            }
        )
        
        return RedirectResponse(url=f"/admin/stripe-product/{product_id}", status_code=303)
    except Exception as e:
        logger.error(f"Error updating Stripe product: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating product: {str(e)}")

@router.get("/admin/stripe-price/{price_id}/toggle")
async def toggle_stripe_price(
    price_id: str,
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Toggle a Stripe price active status"""
    
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to manage prices")
    
    try:
        # Get current price to check its status
        price = stripe.Price.retrieve(price_id)
        
        # Toggle price status (active to inactive or vice versa)
        # Note: Stripe doesn't allow direct updates to a price's active status
        # Instead, we need to create a new price or archive the existing one
        # For simplicity, we'll just show how to archive a price (make inactive)
        if price.get('active', False):
            stripe.Price.modify(price_id, active=False)
        else:
            # Cannot reactivate a price in Stripe, would need to create a new one
            # We'll redirect with an error message
            raise HTTPException(
                status_code=400, 
                detail="Stripe doesn't allow reactivating inactive prices. You must create a new price."
            )
        
        # Get product ID from the price object to redirect back to product details
        product_id = price.get('product', '')
        
        return RedirectResponse(url=f"/admin/stripe-product/{product_id}", status_code=303)
    except Exception as e:
        logger.error(f"Error toggling Stripe price: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error toggling price: {str(e)}")

@router.get("/admin/stripe-product/create", response_class=HTMLResponse)
async def admin_create_stripe_product_form_singular(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Form for creating a new Stripe product - singular URL format"""
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access admin dashboard")
        
    return templates.TemplateResponse("admin/stripe_product_form.html", {
        "request": request,
        "user": current_user,
        "section": "stripe_products",
        "action": "create"
    })

@router.post("/admin/stripe-product/create")
async def admin_create_stripe_product_singular(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Create a new Stripe product - singular URL format"""
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access admin dashboard")
        
    try:
        product = stripe.Product.create(
            name=name,
            description=description
        )
        return RedirectResponse(
            url=f"/admin/stripe-product/{product.id}",
            status_code=303
        )
    except Exception as e:
        logger.error(f"Error creating Stripe product: {str(e)}")
        return templates.TemplateResponse(
            "admin/stripe_product_form.html",
            {
                "request": request,
                "user": current_user,
                "section": "stripe_products",
                "action": "create",
                "error": str(e),
                "name": name,
                "description": description
            }
        )

@router.get("/admin/stripe-product/{product_id}/price", response_class=HTMLResponse)
async def add_price_to_product_form(
    product_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Form for adding a price to a Stripe product - singular URL format"""
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access admin dashboard")
    
    try:
        # Get product details from Stripe
        product = stripe.Product.retrieve(product_id)
        
        return templates.TemplateResponse("admin/stripe_price_form.html", {
            "request": request,
            "user": current_user,
            "section": "stripe_products",
            "product": product,
            "action": "create",
            "pricing_models": [
                {"id": "one_time", "name": "One-time payment"},
                {"id": "recurring", "name": "Subscription (recurring)"},
                {"id": "usage", "name": "Usage-based (pay-as-you-go)"}
            ],
            "billing_periods": [
                {"id": "day", "name": "Daily"},
                {"id": "week", "name": "Weekly"},
                {"id": "month", "name": "Monthly"},
                {"id": "year", "name": "Yearly"}
            ]
        })
    except Exception as e:
        logger.error(f"Error retrieving product for price form: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving product: {str(e)}")

@router.post("/admin/stripe-product/{product_id}/price")
async def add_price_to_product(
    product_id: str,
    request: Request,
    unit_amount: float = Form(...),
    currency: str = Form(...),
    pricing_model: str = Form(...),
    billing_period: Optional[str] = Form(None),
    usage_type: Optional[str] = Form(None),
    aggregation_type: Optional[str] = Form(None),
    nickname: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Add a price to a Stripe product - singular URL format"""
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access admin dashboard")
    
    try:
        # Convert amount to cents/smallest currency unit
        unit_amount_int = int(unit_amount * 100)
        
        price_data = {
            "product": product_id,
            "currency": currency,
            "nickname": nickname,
            "unit_amount": unit_amount_int,
        }
        
        # Handle different pricing models
        if pricing_model == "recurring":
            price_data["recurring"] = {"interval": billing_period}
        elif pricing_model == "usage":
            price_data["recurring"] = {"interval": billing_period, "usage_type": usage_type}
            
            # For metered usage, we need to specify the aggregation
            if usage_type == "metered":
                price_data["recurring"]["aggregate_usage"] = aggregation_type
        
        # Create the price in Stripe
        price = stripe.Price.create(**price_data)
        
        # Redirect to the product page
        return RedirectResponse(
            url=f"/admin/stripe-product/{product_id}",
            status_code=303
        )
    except Exception as e:
        logger.error(f"Error creating price: {str(e)}")
        
        # Get product details for re-rendering the form
        product = stripe.Product.retrieve(product_id)
        
        return templates.TemplateResponse("admin/stripe_price_form.html", {
            "request": request,
            "user": current_user,
            "section": "stripe_products",
            "product": product,
            "action": "create",
            "error": str(e),
            "unit_amount": unit_amount,
            "currency": currency,
            "pricing_model": pricing_model,
            "billing_period": billing_period,
            "nickname": nickname,
            "pricing_models": [
                {"id": "one_time", "name": "One-time payment"},
                {"id": "recurring", "name": "Subscription (recurring)"},
                {"id": "usage", "name": "Usage-based (pay-as-you-go)"}
            ],
            "billing_periods": [
                {"id": "day", "name": "Daily"},
                {"id": "week", "name": "Weekly"},
                {"id": "month", "name": "Monthly"},
                {"id": "year", "name": "Yearly"}
            ]
        })

def setup_routes(app):
    # Existing routes...
    
    # Admin routes
    app.include_router(router, prefix="")
