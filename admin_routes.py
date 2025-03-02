from fastapi import APIRouter, Request, Depends, HTTPException, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from database import get_db, Customer, User, APIKey
from auth import get_current_user
import logging
import os
import stripe
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure templates
templates = Jinja2Templates(directory="templates")

# Add custom Jinja2 filters
def timestamp_to_datetime(timestamp):
    """Convert a Unix timestamp to a formatted datetime string"""
    if not timestamp:
        return "N/A"
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

templates.env.filters["timeformat"] = timestamp_to_datetime

router = APIRouter()

@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Admin dashboard home page"""
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access admin dashboard")
    
    # Get basic stats
    try:
        customers = db.query(Customer).all()
        api_keys_count = db.query(func.count(APIKey.id)).scalar()
        users_count = db.query(func.count(User.id)).scalar()
        
        # Get Stripe stats if available
        try:
            stripe_customers = stripe.Customer.list(limit=1)
            stripe_customers_count = stripe_customers.get('total_count', 0)
            
            stripe_products = stripe.Product.list(limit=1, active=True)
            stripe_products_count = stripe_products.get('total_count', 0)
        except Exception as e:
            logger.error(f"Error fetching Stripe stats: {str(e)}")
            stripe_customers_count = 0
            stripe_products_count = 0
        
        return templates.TemplateResponse(
            "admin.html",
            {
                "request": request,
                "user": current_user,
                "customers": customers,
                "section": "dashboard",
                "customers_count": len(customers),
                "api_keys_count": api_keys_count,
                "users_count": users_count,
                "stripe_customers_count": stripe_customers_count,
                "stripe_products_count": stripe_products_count
            }
        )
    except Exception as e:
        logger.error(f"Error in admin dashboard: {str(e)}")
        return templates.TemplateResponse(
            "admin/error.html",
            {
                "request": request,
                "user": current_user,
                "error": str(e)
            }
        )

@router.get("/debug", response_class=HTMLResponse)
async def admin_debug(request: Request, current_user: User = Depends(get_current_user)):
    """Simplified admin debug page for troubleshooting"""
    
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access admin dashboard")
    
    # Use hard-coded sample data for debug page
    return templates.TemplateResponse(
        "admin_debug.html",
        {
            "request": request,
            "user": current_user,
            "total_api_keys": 0,
            "total_users": 1,
        }
    )

@router.get("/admin/stripe-products", response_class=HTMLResponse)
async def admin_stripe_products(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Admin view for managing Stripe products"""
    try:
        # Fetch products from Stripe
        products = stripe.Product.list(limit=100, active=True)
        
        # Get prices for each product
        for product in products:
            product.prices = stripe.Price.list(product=product.id, active=True)
        
        return templates.TemplateResponse("admin/stripe_products.html", {
            "request": request,
            "user": current_user,
            "products": products.data,
            "section": "stripe_products"
        })
    except Exception as e:
        logger.error(f"Error fetching Stripe products: {str(e)}")
        return templates.TemplateResponse("admin/error.html", {
            "request": request,
            "user": current_user,
            "error": str(e)
        })

@router.get("/admin/stripe-products/create", response_class=HTMLResponse)
async def admin_create_stripe_product_form(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Form for creating a new Stripe product"""
    return templates.TemplateResponse("admin/stripe_product_form.html", {
        "request": request,
        "user": current_user,
        "section": "stripe_products",
        "action": "create"
    })

@router.post("/admin/stripe-products/create")
async def admin_create_stripe_product(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    current_user: User = Depends(get_current_user)
):
    """Create a new Stripe product"""
    try:
        product = stripe.Product.create(
            name=name,
            description=description
        )
        return RedirectResponse(
            url=f"/admin/stripe-products/{product.id}",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        logger.error(f"Error creating Stripe product: {str(e)}")
        return templates.TemplateResponse("admin/stripe_product_form.html", {
            "request": request,
            "user": current_user,
            "section": "stripe_products",
            "action": "create",
            "error": str(e),
            "form_data": {
                "name": name,
                "description": description
            }
        })

@router.get("/admin/stripe-products/{product_id}", response_class=HTMLResponse)
async def admin_view_stripe_product(
    request: Request,
    product_id: str,
    current_user: User = Depends(get_current_user)
):
    """View details of a Stripe product"""
    try:
        product = stripe.Product.retrieve(product_id)
        prices = stripe.Price.list(product=product_id, active=True)
        
        return templates.TemplateResponse("admin/stripe_product_detail.html", {
            "request": request,
            "user": current_user,
            "product": product,
            "prices": prices.data,
            "section": "stripe_products"
        })
    except Exception as e:
        logger.error(f"Error retrieving Stripe product: {str(e)}")
        return templates.TemplateResponse("admin/error.html", {
            "request": request,
            "user": current_user,
            "error": str(e)
        })

@router.get("/admin/stripe-products/{product_id}/add-price", response_class=HTMLResponse)
async def admin_add_stripe_price_form(
    request: Request,
    product_id: str,
    current_user: User = Depends(get_current_user)
):
    """Form for adding a price to a Stripe product"""
    try:
        product = stripe.Product.retrieve(product_id)
        
        return templates.TemplateResponse("admin/stripe_price_form.html", {
            "request": request,
            "user": current_user,
            "product": product,
            "section": "stripe_products"
        })
    except Exception as e:
        logger.error(f"Error retrieving Stripe product for price form: {str(e)}")
        return templates.TemplateResponse("admin/error.html", {
            "request": request,
            "user": current_user,
            "error": str(e)
        })

@router.post("/admin/stripe-products/{product_id}/add-price")
async def admin_add_stripe_price(
    request: Request,
    product_id: str,
    unit_amount: int = Form(...),
    currency: str = Form("usd"),
    price_type: str = Form(...),  # one_time, recurring, metered
    interval: str = Form(None),   # month, year
    usage_type: str = Form(None), # licensed, metered
    current_user: User = Depends(get_current_user)
):
    """Add a price to a Stripe product"""
    try:
        price_data = {
            "product": product_id,
            "unit_amount": int(unit_amount),
            "currency": currency
        }
        
        # Handle different price types
        if price_type == "one_time":
            pass  # No additional fields needed
        elif price_type == "recurring":
            price_data["recurring"] = {
                "interval": interval
            }
        elif price_type == "metered":
            price_data["recurring"] = {
                "interval": interval,
                "usage_type": "metered"
            }
        
        price = stripe.Price.create(**price_data)
        
        return RedirectResponse(
            url=f"/admin/stripe-products/{product_id}",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        logger.error(f"Error creating Stripe price: {str(e)}")
        try:
            product = stripe.Product.retrieve(product_id)
            return templates.TemplateResponse("admin/stripe_price_form.html", {
                "request": request,
                "user": current_user,
                "product": product,
                "section": "stripe_products",
                "error": str(e),
                "form_data": {
                    "unit_amount": unit_amount,
                    "currency": currency,
                    "price_type": price_type,
                    "interval": interval,
                    "usage_type": usage_type
                }
            })
        except:
            return templates.TemplateResponse("admin/error.html", {
                "request": request,
                "user": current_user,
                "error": str(e)
            })
