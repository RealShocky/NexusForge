import stripe
from sqlalchemy.orm import Session
from database import Customer, Invoice, Usage, SessionLocal
from datetime import datetime, timedelta
from sqlalchemy import func
import secrets
import logging

logger = logging.getLogger(__name__)

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
        try:
            # Calculate usage for the last 30 days
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            
            # Query usage data grouped by date
            usage_by_day = db.query(
                func.date(Usage.timestamp).label('date'),
                func.count(Usage.id).label('count'),
                func.sum(Usage.tokens_used).label('tokens'),
                func.sum(Usage.cost).label('cost')
            ).join(Usage.api_key)\
            .filter(
                Usage.api_key.has(customer_id=customer_id),
                Usage.timestamp >= thirty_days_ago
            ).group_by(func.date(Usage.timestamp))\
            .order_by('date')\
            .all()
            
            # Convert to dictionary with date strings as keys
            usage_dict = {}
            for usage in usage_by_day:
                date_str = usage.date.strftime('%Y-%m-%d')
                usage_dict[date_str] = usage.count
                
            return usage_dict
            
        except Exception as e:
            logger.error(f"Error getting usage summary: {str(e)}")
            return {}
    
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

    async def create_payment_intent(self, db: Session, customer_id: int, amount: float):
        """Create a payment intent for a customer"""
        try:
            customer = db.query(Customer).filter_by(id=customer_id).first()
            if not customer:
                raise ValueError("Customer not found")

            # Create payment intent in Stripe
            if self.stripe_key:
                intent = stripe.PaymentIntent.create(
                    amount=int(amount * 100),  # Convert to cents
                    currency='usd',
                    customer=customer.stripe_customer_id,
                    automatic_payment_methods={'enabled': True},
                )
                return intent
            else:
                raise ValueError("Stripe key not configured")
        except Exception as e:
            raise e

    async def get_payment_methods(self, db: Session, customer_id: int):
        """Get all payment methods for a customer"""
        try:
            customer = db.query(Customer).filter_by(id=customer_id).first()
            if not customer:
                return type('MockPaymentMethods', (), {'data': []})()

            if not self.stripe_key:
                return type('MockPaymentMethods', (), {'data': []})()

            try:
                payment_methods = stripe.PaymentMethod.list(
                    customer=customer.stripe_customer_id,
                    type='card'
                )
                return payment_methods
            except stripe.error.StripeError as e:
                print(f"Stripe error: {str(e)}")
                return type('MockPaymentMethods', (), {'data': []})()
                
        except Exception as e:
            print(f"Error in get_payment_methods: {str(e)}")
            return type('MockPaymentMethods', (), {'data': []})()

    async def attach_payment_method(self, db: Session, customer_id: int, payment_method_id: str):
        """Attach a payment method to a customer"""
        try:
            customer = db.query(Customer).filter_by(id=customer_id).first()
            if not customer:
                raise ValueError("Customer not found")

            if self.stripe_key:
                payment_method = stripe.PaymentMethod.attach(
                    payment_method_id,
                    customer=customer.stripe_customer_id,
                )
                return payment_method
            else:
                raise ValueError("Stripe key not configured")
        except Exception as e:
            raise e

    async def get_payment_history(self, db: Session, customer_id: int):
        """Get payment history for a customer"""
        try:
            customer = db.query(Customer).filter_by(id=customer_id).first()
            if not customer:
                raise ValueError("Customer not found")

            if self.stripe_key:
                charges = stripe.Charge.list(
                    customer=customer.stripe_customer_id,
                    limit=100
                )
                return charges
            else:
                raise ValueError("Stripe key not configured")
        except Exception as e:
            raise e

    async def setup_automatic_payments(self, db: Session, customer_id: int, payment_method_id: str):
        """Set up automatic payments for a customer"""
        try:
            customer = db.query(Customer).filter_by(id=customer_id).first()
            if not customer:
                raise ValueError("Customer not found")

            if self.stripe_key:
                # Set the default payment method for the customer
                stripe.Customer.modify(
                    customer.stripe_customer_id,
                    invoice_settings={
                        'default_payment_method': payment_method_id
                    }
                )
                return True
            else:
                raise ValueError("Stripe key not configured")
        except Exception as e:
            raise e
