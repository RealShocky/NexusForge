from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

# Create database engine
DATABASE_URL = "sqlite:///./ai_api.db"
engine = create_engine(DATABASE_URL)
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
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String)
    model_type = Column(String)  # e.g., "huggingface", "openai"
    config = Column(JSON)  # Model-specific configuration
    price_per_1k_tokens = Column(Float)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    name = Column(String)
    rate_limit = Column(Integer, default=60)  # Requests per minute
    allowed_models = Column(JSON)  # List of model IDs this key can access
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    customer = relationship("Customer", back_populates="api_keys")
    usage = relationship("Usage", back_populates="api_key")

class Usage(Base):
    __tablename__ = "usage"

    id = Column(Integer, primary_key=True, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"))
    model_id = Column(Integer, ForeignKey("models.id"))
    request_type = Column(String)  # e.g., "generate", "query"
    tokens_used = Column(Integer)
    response_time = Column(Float)  # in seconds
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

def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
