from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey, DateTime, JSON, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
import secrets
import enum
import logging

# Database configuration
SQLALCHEMY_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://flows_user:flows_password@db:5432/flows_db"
)
logging.info(f"Using database URL: {SQLALCHEMY_DATABASE_URL}")

# Make sure directory exists if using a path
db_path = SQLALCHEMY_DATABASE_URL.replace("postgresql://", "")
if db_path.startswith("./"):
    db_path = db_path[2:]
db_dir = os.path.dirname(db_path)
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)
logging.info(f"Using PostgreSQL database at {db_path}")

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class UserRole(enum.Enum):
    ADMIN = "admin"
    CUSTOMER = "customer"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default=UserRole.CUSTOMER.value)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship to customer if the user is associated with a customer
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    customer = relationship("Customer", back_populates="users")
    
    api_keys = relationship("APIKey", back_populates="user")
    created_models = relationship("AIModel", back_populates="creator", foreign_keys="AIModel.created_by")

class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    company = Column(String, nullable=True)
    stripe_customer_id = Column(String, nullable=True)
    payment_method_id = Column(String, nullable=True)
    payment_method_last4 = Column(String, nullable=True)
    payment_method_brand = Column(String, nullable=True)
    subscription_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    users = relationship("User", back_populates="customer")
    api_keys = relationship("APIKey", back_populates="customer")
    invoices = relationship("Invoice", back_populates="customer")

class AIModel(Base):
    __tablename__ = "ai_models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    provider = Column(String, nullable=True, default="openai")
    model_type = Column(String)  # text, embedding, image
    model_name = Column(String)  # actual API model name
    description = Column(String, nullable=True)
    price_per_1k_tokens = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    api_key = Column(String, nullable=True)
    base_url = Column(String, nullable=True)
    context_length = Column(Integer, default=4096)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    config = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Define relationships
    creator = relationship("User", back_populates="created_models", foreign_keys=[created_by])
    usage = relationship("Usage", back_populates="model")

class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    name = Column(String)
    masked_key = Column(String, nullable=True)
    rate_limit = Column(Integer, default=60)  # Requests per minute
    allowed_models = Column(JSON, default=list)  # List of model IDs this key can access
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime, nullable=True)
    
    customer = relationship("Customer", back_populates="api_keys")
    user = relationship("User", back_populates="api_keys")
    usage = relationship("Usage", back_populates="api_key")

class UsageRecord(Base):
    __tablename__ = "usage_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True)
    service = Column(String(100), nullable=False)
    request_count = Column(Integer, default=1)
    cost = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.now)
    
    user = relationship("User")
    api_key = relationship("APIKey")

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
    model = relationship("AIModel", back_populates="usage")

class Invoice(Base):
    __tablename__ = "invoices"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    stripe_invoice_id = Column(String, unique=True)
    amount = Column(Integer)  # Amount in cents
    status = Column(String)  # paid, open, void, draft
    description = Column(String)
    invoice_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
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
    import os
    from auth import get_password_hash, UserRole
    
    # Create tables
    logging.info("Initializing database...")
    # Always create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    # Create admin user and test customer if they don't exist
    db = SessionLocal()
    try:
        # Check if admin user exists
        admin_exists = db.query(User).filter(User.role == UserRole.ADMIN.value).first() is not None
        if not admin_exists:
            logging.info("Creating admin user...")
            # Create initial admin user
            admin_user = User(
                username="admin",
                email="admin@example.com",
                hashed_password=get_password_hash("admin123"),
                role=UserRole.ADMIN.value
            )
            db.add(admin_user)
            db.commit()
        
        # Check if we need to create a test customer
        if db.query(Customer).count() == 0:
            logging.info("Creating test customer and API keys...")
            # Create test customer
            test_customer = Customer(
                name="Test Customer",
                email="test@example.com",
                company="Test Company",
                stripe_customer_id="cus_example"
            )
            db.add(test_customer)
            db.commit()
            
            # Create test customer user
            customer_user = User(
                username="customer",
                email="customer@example.com",
                hashed_password=get_password_hash("customer123"),
                role=UserRole.CUSTOMER.value,
                customer_id=test_customer.id
            )
            db.add(customer_user)
            db.commit()
            
            # Create API key for test customer
            api_key = APIKey(
                key=secrets.token_hex(16),
                customer_id=test_customer.id,
                name="Default API Key",
                rate_limit=60,
                is_active=True
            )
            db.add(api_key)
            db.commit()
            
            # Add sample AI models
            models = [
                {"name": "GPT-3.5 Turbo", "description": "High quality language model from OpenAI", "model_type": "openai", "model_name": "gpt-3.5-turbo", "price_per_1k_tokens": 0.002},
                {"name": "GPT-4", "description": "Advanced language model from OpenAI", "model_type": "openai", "model_name": "gpt-4", "price_per_1k_tokens": 0.03},
                {"name": "Claude 2", "description": "Anthropic's helpful and harmless AI assistant", "model_type": "anthropic", "model_name": "claude-2", "price_per_1k_tokens": 0.011},
            ]
            
            for model_data in models:
                model = AIModel(
                    name=model_data["name"],
                    description=model_data["description"],
                    model_type=model_data["model_type"],
                    model_name=model_data["model_name"],
                    price_per_1k_tokens=model_data["price_per_1k_tokens"]
                )
                db.add(model)
            
            db.commit()
            logging.info("Database initialization complete.")
        
    except Exception as e:
        db.rollback()
        logging.error(f"Error initializing database: {e}")
    finally:
        db.close()
