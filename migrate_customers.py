import logging
import os
import sys
import psycopg2
from psycopg2 import sql

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_customers():
    """
    Migrate the customers table to include new columns for Stripe payment integration:
    - stripe_customer_id (string)
    - payment_method_id (string)
    - payment_method_last4 (string)
    - payment_method_brand (string)
    - subscription_active (boolean)
    """
    # Get database connection parameters from environment variables
    db_host = os.environ.get("POSTGRES_HOST", "db")
    db_port = os.environ.get("POSTGRES_PORT", "5432")
    db_name = os.environ.get("POSTGRES_DB", "flows_db")
    db_user = os.environ.get("POSTGRES_USER", "db_user")  # Use generic default
    db_password = os.environ.get("POSTGRES_PASSWORD", "")  # Empty default password
    
    # Create connection string for logging with masked password
    masked_db_url = f"postgresql://{db_user}:****@{db_host}:{db_port}/{db_name}"
    logger.info(f"Migrating customers table at: {masked_db_url}")
    
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
        
        # Check if customers table exists
        cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'customers')")
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            logger.warning("Table customers does not exist. Creating it...")
            # Create the table with all required columns
            cursor.execute("""
                CREATE TABLE customers (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR,
                    email VARCHAR UNIQUE,
                    company VARCHAR,
                    stripe_customer_id VARCHAR,
                    payment_method_id VARCHAR,
                    payment_method_last4 VARCHAR,
                    payment_method_brand VARCHAR,
                    subscription_active BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Created customers table successfully")
        else:
            # Columns to add with their types
            columns = [
                ("stripe_customer_id", "VARCHAR"),
                ("payment_method_id", "VARCHAR"),
                ("payment_method_last4", "VARCHAR"),
                ("payment_method_brand", "VARCHAR"),
                ("subscription_active", "BOOLEAN DEFAULT FALSE")
            ]
            
            # Add missing columns
            for column_name, column_type in columns:
                # Check if column exists
                cursor.execute(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'customers' AND column_name = '{column_name}'
                    )
                """)
                
                column_exists = cursor.fetchone()[0]
                
                if not column_exists:
                    logger.info(f"Adding {column_name} column to customers table")
                    cursor.execute(f"ALTER TABLE customers ADD COLUMN {column_name} {column_type}")
                    logger.info(f"Added {column_name} column successfully")
                else:
                    logger.info(f"Column {column_name} already exists in customers table")
            
            # Make stripe_customer_id nullable if it is not
            cursor.execute("""
                SELECT is_nullable 
                FROM information_schema.columns 
                WHERE table_name = 'customers' AND column_name = 'stripe_customer_id'
            """)
            is_nullable = cursor.fetchone()[0]
            
            if is_nullable == 'NO':
                logger.info("Making stripe_customer_id column nullable")
                cursor.execute("ALTER TABLE customers ALTER COLUMN stripe_customer_id DROP NOT NULL")
                logger.info("Made stripe_customer_id column nullable successfully")
        
        logger.info("Customers table migration completed successfully")
        
    except Exception as e:
        logger.error(f"Error during customers table migration: {str(e)}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    migrate_customers()
