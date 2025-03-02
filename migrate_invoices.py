import logging
import os
import sys
import psycopg2
from psycopg2 import sql

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_invoices():
    """
    Migrate the invoices table to update the schema:
    - Update amount to be Integer (cents)
    - Add description and invoice_url columns
    - Remove period_start and period_end columns
    """
    # Get database connection parameters from environment variables
    db_host = os.environ.get("POSTGRES_HOST", "db")
    db_port = os.environ.get("POSTGRES_PORT", "5432")
    db_name = os.environ.get("POSTGRES_DB", "flows_db")
    db_user = os.environ.get("POSTGRES_USER", "db_user")  # Use generic default
    db_password = os.environ.get("POSTGRES_PASSWORD", "")  # Empty default password
    
    # Create connection string for logging with masked password
    masked_db_url = f"postgresql://{db_user}:****@{db_host}:{db_port}/{db_name}"
    logger.info(f"Migrating invoices table at: {masked_db_url}")
    
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
        
        # Check if invoices table exists
        cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'invoices')")
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            logger.warning("Table invoices does not exist. Creating it...")
            # Create the table with all required columns
            cursor.execute("""
                CREATE TABLE invoices (
                    id SERIAL PRIMARY KEY,
                    customer_id INTEGER REFERENCES customers(id),
                    stripe_invoice_id VARCHAR UNIQUE,
                    amount INTEGER,
                    status VARCHAR,
                    description VARCHAR,
                    invoice_url VARCHAR,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Created invoices table successfully")
        else:
            # Check and update columns as needed
            
            # Check if description column exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'invoices' AND column_name = 'description'
                )
            """)
            description_exists = cursor.fetchone()[0]
            
            if not description_exists:
                logger.info("Adding description column to invoices table")
                cursor.execute("ALTER TABLE invoices ADD COLUMN description VARCHAR")
                logger.info("Added description column successfully")
            
            # Check if invoice_url column exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'invoices' AND column_name = 'invoice_url'
                )
            """)
            invoice_url_exists = cursor.fetchone()[0]
            
            if not invoice_url_exists:
                logger.info("Adding invoice_url column to invoices table")
                cursor.execute("ALTER TABLE invoices ADD COLUMN invoice_url VARCHAR")
                logger.info("Added invoice_url column successfully")
            
            # Check if period_start column exists (to remove)
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'invoices' AND column_name = 'period_start'
                )
            """)
            period_start_exists = cursor.fetchone()[0]
            
            if period_start_exists:
                logger.info("Removing period_start column from invoices table")
                cursor.execute("ALTER TABLE invoices DROP COLUMN period_start")
                logger.info("Removed period_start column successfully")
            
            # Check if period_end column exists (to remove)
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'invoices' AND column_name = 'period_end'
                )
            """)
            period_end_exists = cursor.fetchone()[0]
            
            if period_end_exists:
                logger.info("Removing period_end column from invoices table")
                cursor.execute("ALTER TABLE invoices DROP COLUMN period_end")
                logger.info("Removed period_end column successfully")
            
            # Check if amount column is of type INTEGER
            cursor.execute("""
                SELECT data_type 
                FROM information_schema.columns 
                WHERE table_name = 'invoices' AND column_name = 'amount'
            """)
            amount_type = cursor.fetchone()
            
            if amount_type and amount_type[0].lower() != 'integer':
                logger.info("Changing amount column type to INTEGER")
                # Create a temporary column, copy data, and then rename
                cursor.execute("ALTER TABLE invoices ADD COLUMN amount_new INTEGER")
                cursor.execute("UPDATE invoices SET amount_new = CAST(amount * 100 AS INTEGER)")  # Convert from dollars to cents
                cursor.execute("ALTER TABLE invoices DROP COLUMN amount")
                cursor.execute("ALTER TABLE invoices RENAME COLUMN amount_new TO amount")
                logger.info("Changed amount column type to INTEGER successfully")
        
        logger.info("Invoices table migration completed successfully")
        
    except Exception as e:
        logger.error(f"Error during invoices table migration: {str(e)}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    migrate_invoices()
