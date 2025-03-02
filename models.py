from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Budget(Base):
    __tablename__ = 'budgets'
    
    id = Column(Integer, primary_key=True)
    budget_id = Column(String(255), unique=True, nullable=False)
    max_budget = Column(Float, nullable=False)
    tpm = Column(Integer)  # Tokens per minute
    rpm = Column(Integer)  # Requests per minute
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    customers = relationship("CustomerBudget", back_populates="budget")

class CustomerBudget(Base):
    __tablename__ = 'customer_budgets'
    
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customers.id'))
    budget_id = Column(Integer, ForeignKey('budgets.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    customer = relationship("Customer", back_populates="budgets")
    budget = relationship("Budget", back_populates="customers")
