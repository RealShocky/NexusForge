from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from database import get_db, Customer, User, Invoice
from auth import get_current_active_user, get_current_user_from_cookie
import os
import stripe
import logging
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")

# Log API key status (masked for security)
if stripe.api_key:
    logger.info(f"Stripe Secret Key loaded: {stripe.api_key[:4]}...{stripe.api_key[-4:]}")
else:
    logger.error("Stripe Secret Key is not set")

if STRIPE_PUBLISHABLE_KEY:
    logger.info(f"Stripe Publishable Key loaded: {STRIPE_PUBLISHABLE_KEY[:4]}...{STRIPE_PUBLISHABLE_KEY[-4:]}")
else:
    logger.error("Stripe Publishable Key is not set")

# Create router
router = APIRouter(tags=["payment"])

# Templates
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

@router.get("/payment/manage", response_class=HTMLResponse)
async def payment_management(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Render the payment management page for the current user"""
    if not current_user:
        return templates.TemplateResponse("login.html", {"request": request, "error": "You must be logged in to access this page"})
    
    # Get customer associated with the current user
    customer = db.query(Customer).filter(Customer.id == current_user.customer_id).first()
    if not customer:
        return templates.TemplateResponse("payment_management.html", {
            "request": request,
            "user": current_user,
            "customer_id": 0,
            "payment_methods": [],
            "invoices": [],
            "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY,
            "error": "No customer account found. Please contact support."
        })
    
    # If customer has no Stripe ID, create one
    if not customer.stripe_customer_id:
        try:
            stripe_customer = stripe.Customer.create(
                email=customer.email,
                name=customer.name,
                metadata={"internal_customer_id": str(customer.id)}
            )
            customer.stripe_customer_id = stripe_customer.id
            db.commit()
        except Exception as e:
            logger.error(f"Error creating Stripe customer: {str(e)}")
            return templates.TemplateResponse("payment_management.html", {
                "request": request,
                "user": current_user,
                "customer_id": customer.id,
                "payment_methods": [],
                "invoices": [],
                "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY,
                "error": "Could not create payment profile. Please try again later."
            })
    
    # Get payment methods
    payment_methods = []
    default_payment_method_id = None
    try:
        stripe_customer = stripe.Customer.retrieve(customer.stripe_customer_id)
        if stripe_customer.get("invoice_settings", {}).get("default_payment_method"):
            default_payment_method_id = stripe_customer["invoice_settings"]["default_payment_method"]
            
        payment_methods_response = stripe.PaymentMethod.list(
            customer=customer.stripe_customer_id,
            type="card"
        )
        payment_methods = payment_methods_response.data
    except Exception as e:
        logger.error(f"Error retrieving payment methods: {str(e)}")
    
    # Get invoices
    invoices = []
    try:
        # Query local database first
        db_invoices = db.query(Invoice).filter(Invoice.customer_id == customer.id).all()
        
        # If no local invoices, try to get from Stripe
        if not db_invoices:
            stripe_invoices = stripe.Invoice.list(customer=customer.stripe_customer_id)
            for invoice in stripe_invoices.data:
                invoices.append({
                    "created": datetime.fromtimestamp(invoice.created),
                    "description": invoice.lines.data[0].description if invoice.lines.data else "Invoice",
                    "amount": invoice.total / 100,  # Convert from cents to dollars
                    "status": invoice.status,
                    "invoice_pdf": invoice.invoice_pdf
                })
        else:
            for invoice in db_invoices:
                invoices.append({
                    "created": invoice.created_at,
                    "description": invoice.description,
                    "amount": invoice.amount / 100,  # Convert from cents to dollars
                    "status": invoice.status,
                    "invoice_pdf": invoice.invoice_url if invoice.invoice_url else "#"
                })
    except Exception as e:
        logger.error(f"Error retrieving invoices: {str(e)}")
    
    return templates.TemplateResponse("payment_management.html", {
        "request": request,
        "user": current_user,
        "customer_id": customer.id,
        "payment_methods": payment_methods,
        "default_payment_method_id": default_payment_method_id,
        "invoices": invoices,
        "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY
    })

@router.post("/api/setup-intent/{customer_id}")
async def create_setup_intent(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Create a SetupIntent for adding a payment method"""
    logger.info(f"Creating setup intent for customer: {customer_id}")
    
    # Verify the user has access to this customer
    if str(current_user.customer_id) != customer_id and current_user.role != "admin":
        logger.error(f"Customer ID mismatch: {current_user.customer_id} != {customer_id}")
        raise HTTPException(status_code=403, detail="Not authorized to access this customer")
    
    # Get the customer
    customer = db.query(Customer).filter(Customer.id == int(customer_id)).first()
    if not customer:
        logger.error(f"Customer not found for ID: {customer_id}")
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Check if customer exists in Stripe
    stripe_customer_id = customer.stripe_customer_id
    if stripe_customer_id:
        try:
            # Verify the customer exists in Stripe
            stripe_customer = stripe.Customer.retrieve(stripe_customer_id)
            if hasattr(stripe_customer, 'deleted') and stripe_customer.deleted:
                # Customer was deleted in Stripe, create a new one
                stripe_customer_id = None
                logger.warning(f"Stripe customer {stripe_customer_id} was deleted, will create a new one")
        except stripe.error.InvalidRequestError as e:
            # Customer doesn't exist in Stripe, create a new one
            stripe_customer_id = None
            logger.warning(f"Stripe customer {stripe_customer_id} not found, will create a new one: {str(e)}")
            
    # Create new Stripe customer if needed
    if not stripe_customer_id:
        try:
            logger.info(f"Creating new Stripe customer for {customer.name}")
            stripe_customer = stripe.Customer.create(
                email=customer.email,
                name=customer.name,
                metadata={"internal_customer_id": str(customer.id)}
            )
            stripe_customer_id = stripe_customer.id
            
            # Update the customer record
            customer.stripe_customer_id = stripe_customer_id
            db.commit()
            logger.info(f"Updated customer {customer.id} with new Stripe ID: {stripe_customer_id}")
        except Exception as e:
            logger.error(f"Error creating Stripe customer: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to create payment profile")
    
    # Log the Stripe API key (last 4 chars only for security)
    api_key = stripe.api_key
    if api_key:
        masked_key = f"...{api_key[-4:]}" if len(api_key) > 4 else "Invalid key"
        logger.info(f"Using Stripe API key: {masked_key}")
    else:
        logger.error("Stripe API key is not set!")
    
    # Create SetupIntent
    try:
        # Log the customer Stripe ID we're using
        logger.info(f"Creating SetupIntent for Stripe customer: {stripe_customer_id}")
        
        # Ensure we're using the correct API key
        current_key = stripe.api_key
        logger.info(f"Current API key (masked): {current_key[:4]}...{current_key[-4:]}")
        
        # Force use of live key for this operation
        stripe.api_key = "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"
        logger.info("Switched to live API key for setup intent")
        
        setup_intent = stripe.SetupIntent.create(
            customer=stripe_customer_id,
            payment_method_types=["card"],
            usage="off_session"
        )
        
        # Restore original key
        stripe.api_key = current_key
        
        logger.info(f"Setup intent created: {setup_intent.id}")
        return {"client_secret": setup_intent.client_secret}
    except Exception as e:
        logger.error(f"Error creating SetupIntent: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create setup intent: {str(e)}")

@router.get("/payment-confirmation", response_class=HTMLResponse)
async def payment_confirmation(
    request: Request,
    setup_intent_client_secret: Optional[str] = None,
    setup_intent: Optional[str] = None,
    redirect_status: Optional[str] = None,
    current_user: User = Depends(get_current_user_from_cookie)
):
    """Handle the payment confirmation after a successful payment method setup"""
    if not current_user:
        return RedirectResponse(url="/login")
    
    success = False
    message = ""
    
    if setup_intent and redirect_status == "succeeded":
        success = True
        message = "Your payment method has been added successfully."
    elif redirect_status == "failed":
        message = "Failed to add your payment method. Please try again."
    elif redirect_status == "canceled":
        message = "The payment method setup was canceled."
    
    return templates.TemplateResponse("payment_confirmation.html", {
        "request": request,
        "success": success,
        "message": message
    })

@router.post("/api/attach-payment-method/{customer_id}")
async def attach_payment_method(
    customer_id: int,
    payment_method_id: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Attach a payment method to a customer"""
    # Verify the user has access to this customer
    if current_user.customer_id != customer_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access this customer")
    
    # Get the customer
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    if not customer.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Customer has no payment profile")
    
    # Attach payment method to customer
    try:
        payment_method = stripe.PaymentMethod.attach(
            payment_method_id,
            customer=customer.stripe_customer_id
        )
        
        # Update customer record with payment method details
        customer.payment_method_id = payment_method.id
        customer.payment_method_last4 = payment_method.card.last4
        customer.payment_method_brand = payment_method.card.brand
        db.commit()
        
        # Set as default payment method if no default exists
        stripe_customer = stripe.Customer.retrieve(customer.stripe_customer_id)
        if not stripe_customer.get("invoice_settings", {}).get("default_payment_method"):
            stripe.Customer.modify(
                customer.stripe_customer_id,
                invoice_settings={"default_payment_method": payment_method.id}
            )
        
        return {"success": True, "payment_method": {
            "id": payment_method.id,
            "last4": payment_method.card.last4,
            "brand": payment_method.card.brand
        }}
    except Exception as e:
        logger.error(f"Error attaching payment method: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to attach payment method")

@router.post("/api/set-default-payment-method/{customer_id}")
async def set_default_payment_method(
    customer_id: int,
    payment_method_id: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Set a payment method as the default for a customer"""
    # Verify the user has access to this customer
    if current_user.customer_id != customer_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access this customer")
    
    # Get the customer
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    if not customer.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Customer has no payment profile")
    
    # Set as default payment method
    try:
        stripe.Customer.modify(
            customer.stripe_customer_id,
            invoice_settings={"default_payment_method": payment_method_id}
        )
        
        # Get payment method details
        payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
        
        # Update customer record
        customer.payment_method_id = payment_method.id
        customer.payment_method_last4 = payment_method.card.last4
        customer.payment_method_brand = payment_method.card.brand
        db.commit()
        
        return {"success": True}
    except Exception as e:
        logger.error(f"Error setting default payment method: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to set default payment method")

@router.post("/api/delete-payment-method/{customer_id}")
async def delete_payment_method(
    customer_id: int,
    payment_method_id: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Delete a payment method for a customer"""
    # Verify the user has access to this customer
    if current_user.customer_id != customer_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access this customer")
    
    # Get the customer
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    if not customer.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Customer has no payment profile")
    
    # Check if this is the default payment method
    is_default = False
    try:
        stripe_customer = stripe.Customer.retrieve(customer.stripe_customer_id)
        is_default = stripe_customer.get("invoice_settings", {}).get("default_payment_method") == payment_method_id
    except Exception as e:
        logger.error(f"Error checking default payment method: {str(e)}")
    
    # Delete payment method
    try:
        stripe.PaymentMethod.detach(payment_method_id)
        
        # Clear customer record if this was the default payment method
        if is_default or customer.payment_method_id == payment_method_id:
            customer.payment_method_id = None
            customer.payment_method_last4 = None
            customer.payment_method_brand = None
            db.commit()
        
        return {"success": True}
    except Exception as e:
        logger.error(f"Error deleting payment method: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete payment method")

@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    try:
        # Get the webhook signature
        signature = request.headers.get("stripe-signature")
        
        # Get the webhook secret from environment variables
        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
        
        if not webhook_secret:
            logger.error("Stripe webhook secret not configured")
            return JSONResponse(status_code=500, content={"error": "Webhook secret not configured"})
        
        # Get the request body as bytes
        body = await request.body()
        
        # Verify the webhook signature
        try:
            event = stripe.Webhook.construct_event(
                body, signature, webhook_secret
            )
        except ValueError as e:
            logger.error(f"Invalid webhook payload: {str(e)}")
            return JSONResponse(status_code=400, content={"error": "Invalid payload"})
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid signature: {str(e)}")
            return JSONResponse(status_code=400, content={"error": "Invalid signature"})
        
        # Handle the event
        if event["type"] == "invoice.payment_succeeded":
            await handle_successful_payment(event["data"]["object"], request)
        elif event["type"] == "invoice.payment_failed":
            await handle_failed_payment(event["data"]["object"], request)
        
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return JSONResponse(status_code=500, content={"error": str(e)})

async def handle_successful_payment(invoice, request: Request):
    """Handle successful payment webhook event"""
    try:
        db = next(get_db())
        
        # Get customer from Stripe customer ID
        stripe_customer_id = invoice.get("customer")
        customer = db.query(Customer).filter(Customer.stripe_customer_id == stripe_customer_id).first()
        
        if not customer:
            logger.error(f"Customer not found for Stripe ID: {stripe_customer_id}")
            return
        
        # Create invoice record
        db_invoice = Invoice(
            customer_id=customer.id,
            stripe_invoice_id=invoice.get("id"),
            amount=invoice.get("total"),
            status="paid",
            description=invoice.get("description") or "API Usage",
            invoice_url=invoice.get("invoice_pdf"),
            created_at=datetime.fromtimestamp(invoice.get("created"))
        )
        db.add(db_invoice)
        db.commit()
        
        logger.info(f"Recorded successful payment for customer {customer.id}")
    except Exception as e:
        logger.error(f"Error handling successful payment: {str(e)}")

async def handle_failed_payment(invoice, request: Request):
    """Handle failed payment webhook event"""
    try:
        db = next(get_db())
        
        # Get customer from Stripe customer ID
        stripe_customer_id = invoice.get("customer")
        customer = db.query(Customer).filter(Customer.stripe_customer_id == stripe_customer_id).first()
        
        if not customer:
            logger.error(f"Customer not found for Stripe ID: {stripe_customer_id}")
            return
        
        # Create invoice record for failed payment
        db_invoice = Invoice(
            customer_id=customer.id,
            stripe_invoice_id=invoice.get("id"),
            amount=invoice.get("total"),
            status="failed",
            description=invoice.get("description") or "API Usage (Failed Payment)",
            invoice_url=invoice.get("hosted_invoice_url"),
            created_at=datetime.fromtimestamp(invoice.get("created"))
        )
        db.add(db_invoice)
        
        # Update customer subscription status
        customer.subscription_active = False
        
        db.commit()
        
        logger.info(f"Recorded failed payment for customer {customer.id}")
    except Exception as e:
        logger.error(f"Error handling failed payment: {str(e)}")

@router.get("/test-stripe-keys")
async def test_stripe_keys():
    """Test endpoint to verify Stripe keys are correctly configured"""
    try:
        # Test the secret key by making a simple API call
        customers = stripe.Customer.list(limit=1)
        
        return {
            "success": True,
            "message": "Stripe keys are configured correctly",
            "publishable_key": STRIPE_PUBLISHABLE_KEY,
            "secret_key_valid": True
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error with Stripe configuration: {str(e)}",
            "publishable_key": STRIPE_PUBLISHABLE_KEY,
            "secret_key_valid": False
        }
