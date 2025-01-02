from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
import secrets

# Create database engine
DATABASE_URL = "sqlite:///flows.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    company = Column(String)
    stripe_customer_id = Column(String, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    api_keys = relationship("APIKey", back_populates="customer")
    invoices = relationship("Invoice", back_populates="customer")

class AIModel(Base):
    __tablename__ = "ai_models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(String, nullable=True)
    model_type = Column(String)  # e.g., 'huggingface', 'custom'
    model_name = Column(String)  # e.g., 'gpt2', 'bert-base-uncased'
    config = Column(JSON, nullable=True)
    price_per_1k_tokens = Column(Float)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    usage = relationship("Usage", back_populates="model")

class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    name = Column(String)
    rate_limit = Column(Integer, default=60)  # Requests per minute
    allowed_models = Column(JSON, default=list)  # List of model IDs this key can access
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    customer = relationship("Customer", back_populates="api_keys")
    usage = relationship("Usage", back_populates="api_key")

class Usage(Base):
    __tablename__ = "usage"

    id = Column(Integer, primary_key=True, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"))
    model_id = Column(Integer, ForeignKey("ai_models.id"))
    request_type = Column(String)
    tokens_used = Column(Integer)
    response_time = Column(Float)
    cost = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    api_key = relationship("APIKey", back_populates="usage")
    model = relationship("AIModel")

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    stripe_invoice_id = Column(String, unique=True)
    amount = Column(Float)
    status = Column(String)  # e.g., "pending", "paid"
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    customer = relationship("Customer", back_populates="invoices")

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def recreate_database():
    """Drop all tables and recreate them"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

def init_db():
    """Initialize the database if it doesn't exist"""
    Base.metadata.create_all(bind=engine)
    
    # Create session
    db = SessionLocal()
    try:
        # Check if we need to create default models
        if db.query(AIModel).count() == 0:
            # Add GPT-2 model
            gpt2_model = AIModel(
                name="GPT-2 Small",
                description="OpenAI GPT-2 small model for text generation",
                model_type="huggingface",
                model_name="gpt2",
                price_per_1k_tokens=0.01
            )
            db.add(gpt2_model)
            
            # Add custom model example
            custom_model = AIModel(
                name="Custom Model",
                description="Example custom model",
                model_type="custom",
                model_name="custom-v1",
                config={"endpoint": "http://localhost:5000/generate"},
                price_per_1k_tokens=0.02
            )
            db.add(custom_model)
            
            db.commit()
            
        # Check if we need to create a default API key for test customer
        test_customer = db.query(Customer).filter_by(email='test@example.com').first()
        if test_customer and not db.query(APIKey).filter_by(customer_id=test_customer.id).first():
            api_key = APIKey(
                key=secrets.token_urlsafe(32),
                name="Default API Key",
                customer_id=test_customer.id,
                rate_limit=60,
                allowed_models=[]
            )
            db.add(api_key)
            db.commit()
    finally:
        db.close()
