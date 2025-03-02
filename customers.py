from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from database import get_db, Customer, User
from auth import get_current_active_user
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/customers", tags=["customers"])

@router.get("/{customer_id}")
async def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get a customer by ID"""
    # Verify the user has access to this customer
    if current_user.customer_id != customer_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to access this customer")
    
    # Get the customer
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "company": customer.company,
        "has_payment_method": bool(customer.payment_method_id),
        "payment_method_last4": customer.payment_method_last4,
        "payment_method_brand": customer.payment_method_brand,
        "subscription_active": customer.subscription_active
    }

@router.put("/{customer_id}")
async def update_customer(
    customer_id: int,
    name: Optional[str] = Body(None),
    email: Optional[str] = Body(None),
    company: Optional[str] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update a customer"""
    # Verify the user has access to this customer
    if current_user.customer_id != customer_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to update this customer")
    
    # Get the customer
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Update customer fields
    if name is not None:
        customer.name = name
    if email is not None:
        customer.email = email
    if company is not None:
        customer.company = company
    
    # Commit changes
    db.commit()
    
    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "company": customer.company
    }

@router.get("/")
async def list_customers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """List all customers (admin only)"""
    # Verify the user is an admin
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to list all customers")
    
    # Get all customers
    customers = db.query(Customer).all()
    
    return [
        {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "company": customer.company,
            "has_payment_method": bool(customer.payment_method_id),
            "payment_method_last4": customer.payment_method_last4,
            "payment_method_brand": customer.payment_method_brand,
            "subscription_active": customer.subscription_active
        }
        for customer in customers
    ]
