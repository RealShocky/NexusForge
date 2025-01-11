from fastapi import Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import stripe
import os
from database import SessionLocal, Customer
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure templates
templates = Jinja2Templates(directory="templates")

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    """Admin dashboard showing all customers"""
    customers = db.query(Customer).all()
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "customers": customers}
    )

async def create_customer(
    name: str = Form(...),
    email: str = Form(...),
    company: str = Form(...),
    db: Session = Depends(get_db)
):
    """Create a new customer and their corresponding Stripe customer"""
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
        logger.info(f"Created Stripe customer: {stripe_customer.id}")
        
        # Create our customer record
        customer = Customer(
            name=name,
            email=email,
            company=company,
            stripe_customer_id=stripe_customer.id
        )
        db.add(customer)
        db.commit()
        logger.info(f"Created local customer record with ID: {customer.id}")
        
        return RedirectResponse(url="/admin", status_code=303)
    except Exception as e:
        logger.error(f"Error creating customer: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

async def sync_customer(
    customer_id: int,
    db: Session = Depends(get_db)
):
    """Sync a customer with Stripe (create Stripe customer if missing)"""
    try:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
            
        if not customer.stripe_customer_id:
            # Create new Stripe customer
            stripe_customer = stripe.Customer.create(
                email=customer.email,
                name=customer.name,
                metadata={
                    "company": customer.company
                }
            )
            customer.stripe_customer_id = stripe_customer.id
            db.commit()
            logger.info(f"Created Stripe customer for existing customer: {stripe_customer.id}")
        
        # Redirect back to admin page instead of returning JSON
        return RedirectResponse(url="/admin", status_code=303)
    except Exception as e:
        logger.error(f"Error syncing customer: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

async def view_customer(
    customer_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """View customer details including Stripe info"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
        
    stripe_customer = None
    if customer.stripe_customer_id:
        try:
            stripe_customer = stripe.Customer.retrieve(customer.stripe_customer_id)
        except stripe.error.StripeError as e:
            logger.error(f"Error retrieving Stripe customer: {str(e)}")
    
    return templates.TemplateResponse(
        "customer_detail.html",
        {
            "request": request,
            "customer": customer,
            "stripe_customer": stripe_customer
        }
    )
