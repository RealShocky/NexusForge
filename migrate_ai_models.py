import logging
import os
import sys
import psycopg2
from psycopg2 import sql

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_database():
    """
    Migrate the database schema to ensure all required tables exist with the correct columns
    """
    # Get database connection parameters from environment variables
    db_host = os.environ.get("POSTGRES_HOST", "db")
    db_port = os.environ.get("POSTGRES_PORT", "5432")
    db_name = os.environ.get("POSTGRES_DB", "flows_db")
    db_user = os.environ.get("POSTGRES_USER", "db_user")  # Use generic default
    db_password = os.environ.get("POSTGRES_PASSWORD", "")  # Empty default password
    
    db_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    logger.info(f"Migrating database at: {db_url}")
    
    try:
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=db_password
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Check if users table exists
        cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')")
        users_table_exists = cursor.fetchone()[0]
        
        if not users_table_exists:
            logger.warning("Table users does not exist. Creating it...")
            cursor.execute("""
                CREATE TABLE users (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR UNIQUE,
                    username VARCHAR UNIQUE,
                    hashed_password VARCHAR,
                    full_name VARCHAR,
                    role VARCHAR DEFAULT 'user',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Created users table successfully")
            
            # Create admin user
            cursor.execute("""
                INSERT INTO users (email, username, hashed_password, full_name, role, is_active)
                VALUES ('admin@example.com', 'admin', '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW', 'Admin User', 'admin', true)
            """)
            logger.info("Created admin user with username 'admin' and password 'password'")
        
        # Check if ai_models table exists
        cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'ai_models')")
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            logger.warning("Table ai_models does not exist. Creating it...")
            # Create the table with all required columns
            cursor.execute("""
                CREATE TABLE ai_models (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR UNIQUE,
                    model_type VARCHAR,
                    model_name VARCHAR,
                    description VARCHAR,
                    price_per_1k_tokens FLOAT DEFAULT 0.0,
                    is_active BOOLEAN DEFAULT TRUE,
                    provider VARCHAR DEFAULT 'openai',
                    api_key VARCHAR,
                    base_url VARCHAR,
                    context_length INTEGER DEFAULT 4096,
                    created_by INTEGER REFERENCES users(id),
                    config JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Created ai_models table successfully")
            
            # Add a default model
            cursor.execute("""
                INSERT INTO ai_models (name, model_type, model_name, description, provider, price_per_1k_tokens, is_active)
                VALUES ('GPT-3.5 Turbo', 'text', 'gpt-3.5-turbo', 'OpenAI GPT-3.5 Turbo model for general text generation', 'openai', 0.002, true)
            """)
            logger.info("Added default GPT-3.5 Turbo model")
        else:
            # Columns to add with their types
            columns = [
                ("provider", "VARCHAR DEFAULT 'openai'"),
                ("api_key", "VARCHAR"),
                ("base_url", "VARCHAR"),
                ("context_length", "INTEGER DEFAULT 4096"),
                ("created_by", "INTEGER REFERENCES users(id)")
            ]
            
            # Add missing columns
            for column_name, column_type in columns:
                # Check if column exists
                cursor.execute(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'ai_models' AND column_name = '{column_name}'
                    )
                """)
                
                column_exists = cursor.fetchone()[0]
                
                if not column_exists:
                    logger.info(f"Adding {column_name} column to ai_models table")
                    cursor.execute(f"ALTER TABLE ai_models ADD COLUMN {column_name} {column_type}")
                    logger.info(f"Added {column_name} column successfully")
                else:
                    logger.info(f"Column {column_name} already exists in ai_models table")
            
            # Check if 'updated_at' column exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'ai_models' AND column_name = 'updated_at'
                )
            """)
            updated_at_exists = cursor.fetchone()[0]
            
            if not updated_at_exists:
                logger.info("Adding updated_at column to ai_models table")
                cursor.execute("ALTER TABLE ai_models ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                logger.info("Added updated_at column successfully")
        
        logger.info("Database migration completed successfully")
        
    except Exception as e:
        logger.error(f"Error during database migration: {str(e)}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    migrate_database()
