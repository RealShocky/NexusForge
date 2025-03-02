import logging
import os
import sys
import psycopg2
from psycopg2 import sql

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_users():
    """
    Migrate the users table to add customer_id column
    """
    # Get database connection parameters from environment variables or use defaults
    db_host = os.environ.get("POSTGRES_HOST", "db")
    db_port = os.environ.get("POSTGRES_PORT", "5432")
    db_name = os.environ.get("POSTGRES_DB", "flows_db")
    db_user = os.environ.get("POSTGRES_USER", "flows_user")
    db_password = os.environ.get("POSTGRES_PASSWORD", "flows_password")
    
    db_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    logger.info(f"Migrating users table at: {db_url}")
    
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
        
        # Check if customer_id column exists in users table
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_name = 'users' AND column_name = 'customer_id'
            )
        """)
        
        column_exists = cursor.fetchone()[0]
        
        if not column_exists:
            logger.info("Adding customer_id column to users table")
            
            # First, check if the customers table exists
            cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'customers')")
            customers_table_exists = cursor.fetchone()[0]
            
            if not customers_table_exists:
                logger.warning("Customers table does not exist. Creating it first...")
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
            
            # Add the customer_id column with foreign key constraint
            cursor.execute("""
                ALTER TABLE users 
                ADD COLUMN customer_id INTEGER REFERENCES customers(id)
            """)
            
            logger.info("Added customer_id column to users table successfully")
            
            # Update existing users with a default customer if needed
            # For example, create a default customer for admin users
            cursor.execute("SELECT id, email FROM users WHERE role = 'admin' AND customer_id IS NULL")
            admin_users = cursor.fetchall()
            
            if admin_users:
                for user_id, user_email in admin_users:
                    # Check if admin customer exists
                    cursor.execute("SELECT id FROM customers WHERE email = %s", (user_email,))
                    customer = cursor.fetchone()
                    
                    if customer:
                        customer_id = customer[0]
                    else:
                        # Create a new customer for the admin
                        cursor.execute("""
                            INSERT INTO customers (name, email, company) 
                            VALUES ('Admin', %s, 'NexusAI') 
                            RETURNING id
                        """, (user_email,))
                        customer_id = cursor.fetchone()[0]
                    
                    # Update the user with the customer_id
                    cursor.execute("""
                        UPDATE users SET customer_id = %s WHERE id = %s
                    """, (customer_id, user_id))
                    
                    logger.info(f"Updated user {user_id} with customer_id {customer_id}")
        else:
            logger.info("customer_id column already exists in users table")
        
        logger.info("Users table migration completed successfully")
        
    except Exception as e:
        logger.error(f"Error during users table migration: {str(e)}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    migrate_users()
