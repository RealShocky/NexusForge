import os
import logging
import psycopg2
from psycopg2 import sql
from passlib.context import CryptContext

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password):
    return pwd_context.hash(password)

def reset_admin_password():
    """
    Reset the admin user password and ensure the user exists
    """
    # Get database connection parameters from environment variables or use defaults
    db_host = os.environ.get("POSTGRES_HOST", "db")
    db_port = os.environ.get("POSTGRES_PORT", "5432")
    db_name = os.environ.get("POSTGRES_DB", "flows_db")
    db_user = os.environ.get("POSTGRES_USER", "flows_user")
    db_password = os.environ.get("POSTGRES_PASSWORD", "flows_password")
    
    # New admin credentials
    admin_username = "admin"
    admin_password = "admin123"
    admin_email = "admin@nexusai.com"
    
    logger.info(f"Resetting password for user: {admin_username}")
    
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
        
        # Check if admin user exists
        cursor.execute("SELECT id, email FROM users WHERE username = %s", (admin_username,))
        admin_user = cursor.fetchone()
        
        hashed_password = hash_password(admin_password)
        
        if admin_user:
            user_id, email = admin_user
            logger.info(f"Admin user found with ID: {user_id}. Updating password.")
            
            # Update the admin password
            cursor.execute(
                "UPDATE users SET hashed_password = %s WHERE id = %s",
                (hashed_password, user_id)
            )
            logger.info(f"Password updated for user {admin_username}")
            
            # Make sure user is active
            cursor.execute(
                "UPDATE users SET is_active = TRUE WHERE id = %s",
                (user_id,)
            )
            
            # Check if there's a customer for this admin
            cursor.execute("SELECT id FROM customers WHERE email = %s", (email,))
            customer = cursor.fetchone()
            
            if not customer:
                # Create a customer for admin if needed
                cursor.execute(
                    "INSERT INTO customers (name, email, company) VALUES (%s, %s, %s) RETURNING id",
                    ("Admin", email, "NexusAI")
                )
                customer_id = cursor.fetchone()[0]
                
                # Link user to customer
                cursor.execute(
                    "UPDATE users SET customer_id = %s WHERE id = %s",
                    (customer_id, user_id)
                )
                logger.info(f"Created and linked customer with ID {customer_id} to admin user")
            
        else:
            logger.info(f"Admin user not found. Creating new admin user.")
            
            # Create a customer for the admin
            cursor.execute(
                "INSERT INTO customers (name, email, company) VALUES (%s, %s, %s) RETURNING id",
                ("Admin", admin_email, "NexusAI")
            )
            customer_id = cursor.fetchone()[0]
            logger.info(f"Created customer with ID {customer_id}")
            
            # Create the admin user
            cursor.execute(
                """
                INSERT INTO users (username, email, hashed_password, role, is_active, customer_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (admin_username, admin_email, hashed_password, "admin", True, customer_id)
            )
            logger.info(f"Created new admin user: {admin_username}")
        
        # Display all users for debugging
        cursor.execute("SELECT id, username, email, role FROM users")
        users = cursor.fetchall()
        logger.info("Available users:")
        for user in users:
            logger.info(f"  ID: {user[0]}, Username: {user[1]}, Email: {user[2]}, Role: {user[3]}")
        
        logger.info(f"Admin password reset completed. You can now login with username '{admin_username}' and password '{admin_password}'")
        
    except Exception as e:
        logger.error(f"Error resetting admin password: {str(e)}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    reset_admin_password()
