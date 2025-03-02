from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, ForeignKey, Float, JSON, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os
import sys

# Database URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./nexusai.db")

# Create engine and session
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Get a session
db = SessionLocal()

try:
    print("Starting database migration...")
    
    # Check if we're using PostgreSQL or SQLite
    if 'postgres' in DATABASE_URL:
        # PostgreSQL version
        print("Using PostgreSQL migration...")
        
        # Check if user_id column exists in api_keys table
        check_user_id = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='api_keys' AND column_name='user_id'
        """
        result = db.execute(text(check_user_id)).fetchone()
        
        if not result:
            print("Adding user_id column to api_keys table...")
            db.execute(text("ALTER TABLE api_keys ADD COLUMN user_id INTEGER REFERENCES users(id)"))
        
        # Check if masked_key column exists in api_keys table
        check_masked_key = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='api_keys' AND column_name='masked_key'
        """
        result = db.execute(text(check_masked_key)).fetchone()
        
        if not result:
            print("Adding masked_key column to api_keys table...")
            db.execute(text("ALTER TABLE api_keys ADD COLUMN masked_key VARCHAR"))
        
        # Check if last_used column exists in api_keys table
        check_last_used = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='api_keys' AND column_name='last_used'
        """
        result = db.execute(text(check_last_used)).fetchone()
        
        if not result:
            print("Adding last_used column to api_keys table...")
            db.execute(text("ALTER TABLE api_keys ADD COLUMN last_used TIMESTAMP"))
        
        # Check if customer_id is NULLable
        check_nullable = """
        SELECT is_nullable 
        FROM information_schema.columns 
        WHERE table_name='api_keys' AND column_name='customer_id'
        """
        result = db.execute(text(check_nullable)).fetchone()
        
        if result and result[0] == 'NO':  # 'NO' means NOT NULL
            print("Making customer_id column nullable...")
            db.execute(text("ALTER TABLE api_keys ALTER COLUMN customer_id DROP NOT NULL"))
        
        # Check if usage_records table exists
        check_table = """
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_name='usage_records'
        """
        result = db.execute(text(check_table)).fetchone()
        
        if not result:
            print("Creating usage_records table...")
            db.execute(text("""
            CREATE TABLE usage_records (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                api_key_id INTEGER REFERENCES api_keys(id),
                service VARCHAR(100) NOT NULL,
                request_count INTEGER DEFAULT 1,
                cost FLOAT DEFAULT 0.0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """))
    else:
        # SQLite version
        print("Using SQLite migration...")
        
        # Check if user_id column exists in api_keys table
        check_user_id = "SELECT COUNT(*) FROM pragma_table_info('api_keys') WHERE name='user_id'"
        result = db.execute(text(check_user_id)).scalar()
        
        if result == 0:
            print("Adding user_id column to api_keys table...")
            db.execute(text("ALTER TABLE api_keys ADD COLUMN user_id INTEGER REFERENCES users(id)"))
        
        # Check if masked_key column exists in api_keys table
        check_masked_key = "SELECT COUNT(*) FROM pragma_table_info('api_keys') WHERE name='masked_key'"
        result = db.execute(text(check_masked_key)).scalar()
        
        if result == 0:
            print("Adding masked_key column to api_keys table...")
            db.execute(text("ALTER TABLE api_keys ADD COLUMN masked_key VARCHAR"))
        
        # Check if last_used column exists in api_keys table
        check_last_used = "SELECT COUNT(*) FROM pragma_table_info('api_keys') WHERE name='last_used'"
        result = db.execute(text(check_last_used)).scalar()
        
        if result == 0:
            print("Adding last_used column to api_keys table...")
            db.execute(text("ALTER TABLE api_keys ADD COLUMN last_used TIMESTAMP"))
        
        # Create usage_records table if it doesn't exist
        db.execute(text("""
        CREATE TABLE IF NOT EXISTS usage_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            api_key_id INTEGER REFERENCES api_keys(id),
            service VARCHAR(100) NOT NULL,
            request_count INTEGER DEFAULT 1,
            cost FLOAT DEFAULT 0.0,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """))
    
    # Commit the transaction
    db.commit()
    print("Database migration completed successfully!")

except Exception as e:
    db.rollback()
    print(f"Error during migration: {str(e)}")
    sys.exit(1)

finally:
    db.close()
