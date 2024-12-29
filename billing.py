import stripe
from sqlalchemy.orm import Session
from database import Customer, Invoice, Usage
from datetime import datetime, timedelta
from sqlalchemy import func
import secrets

class BillingService:
    def __init__(self, stripe_key: str = None):
        self.stripe_key = stripe_key
        if stripe_key:
            stripe.api_key = stripe_key
        
    async def create_customer(self, db: Session, name: str, email: str, company: str):
        """Create a new customer in local database (and Stripe if configured)"""
        try:
            # Generate a mock Stripe customer ID for testing
            stripe_customer_id = f"cus_mock_{secrets.token_hex(10)}"
            
            # Create customer in Stripe if configured
            if self.stripe_key:
                try:
                    stripe_customer = stripe.Customer.create(
                        name=name,
                        email=email,
                        description=f"Customer from {company}"
                    )
                    stripe_customer_id = stripe_customer.id
                except Exception as e:
                    print(f"Stripe error (continuing without Stripe): {str(e)}")
            
            # Create customer in local database
            customer = Customer(
                name=name,
                email=email,
                company=company,
                stripe_customer_id=stripe_customer_id
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)
            
            return customer
            
        except Exception as e:
            db.rollback()
            raise e
    
    async def get_customer_usage_summary(self, db: Session, customer_id: int):
        """Get usage summary for a customer"""
        # Get total usage for the current month
        start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        month_usage = db.query(
            func.sum(Usage.tokens_used).label('total_tokens'),
            func.sum(Usage.cost).label('total_cost'),
            func.count(Usage.id).label('total_requests')
        ).join(Usage.api_key)\
        .filter(
            Usage.api_key.has(customer_id=customer_id),
            Usage.timestamp >= start_of_month
        ).first()
        
        return {
            "total_tokens": month_usage.total_tokens or 0,
            "total_cost": month_usage.total_cost or 0.0,
            "total_requests": month_usage.total_requests or 0
        }
    
    async def create_invoice(self, db: Session, customer_id: int, period_start: datetime, period_end: datetime):
        """Create an invoice for a customer's usage"""
        # Get customer
        customer = db.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            raise ValueError("Customer not found")
            
        # Calculate total usage for the period
        usage = db.query(func.sum(Usage.cost).label('total_cost'))\
            .join(Usage.api_key)\
            .filter(
                Usage.api_key.has(customer_id=customer_id),
                Usage.timestamp.between(period_start, period_end)
            ).scalar()
            
        total_amount = usage or 0.0
        
        # Create invoice in Stripe if configured
        if self.stripe_key:
            try:
                stripe_invoice = stripe.Invoice.create(
                    customer=customer.stripe_customer_id,
                    amount=int(total_amount * 100),  # Convert to cents
                    currency='usd',
                    description=f"API Usage {period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')}"
                )
            except Exception as e:
                print(f"Stripe error (continuing without Stripe): {str(e)}")
                stripe_invoice_id = f"in_mock_{secrets.token_hex(10)}"
            else:
                stripe_invoice_id = stripe_invoice.id
        else:
            stripe_invoice_id = f"in_mock_{secrets.token_hex(10)}"
        
        # Create invoice in local database
        invoice = Invoice(
            customer_id=customer_id,
            stripe_invoice_id=stripe_invoice_id,
            amount=total_amount,
            status="pending",
            period_start=period_start,
            period_end=period_end
        )
        
        db.add(invoice)
        db.commit()
        
        return invoice
