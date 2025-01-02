import stripe
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from database import Customer, Invoice, Usage

class BillingService:
    def __init__(self, session: Session, stripe_key: Optional[str] = None):
        self.session = session
        if stripe_key:
            stripe.api_key = stripe_key
    
    def calculate_usage_cost(self, tokens_used: int, price_per_1k_tokens: float) -> float:
        """Calculate the cost of usage based on tokens and price"""
        return (tokens_used / 1000.0) * price_per_1k_tokens
    
    def record_usage(self, api_key_id: int, model_id: int, request_type: str, tokens_used: int, response_time: float, cost: float):
        """Record API usage for billing"""
        usage = Usage(
            api_key_id=api_key_id,
            model_id=model_id,
            request_type=request_type,
            tokens_used=tokens_used,
            response_time=response_time,
            cost=cost
        )
        self.session.add(usage)
        self.session.commit()
    
    def create_invoice(self, customer_id: int, amount: float, period_start: datetime, period_end: datetime):
        """Create an invoice for a customer"""
        invoice = Invoice(
            customer_id=customer_id,
            amount=amount,
            status="pending",
            period_start=period_start,
            period_end=period_end
        )
        self.session.add(invoice)
        self.session.commit()
        return invoice
    
    def get_customer_usage(self, customer_id: int, start_date: datetime, end_date: datetime) -> float:
        """Get total usage cost for a customer in a given period"""
        total_cost = 0.0
        customer = self.session.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            return total_cost
            
        for api_key in customer.api_keys:
            usages = self.session.query(Usage).filter(
                Usage.api_key_id == api_key.id,
                Usage.timestamp >= start_date,
                Usage.timestamp <= end_date
            ).all()
            
            for usage in usages:
                total_cost += usage.cost
                
        return total_cost
