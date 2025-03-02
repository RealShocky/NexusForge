import os
import logging
import psycopg2
from psycopg2 import sql
from passlib.context import CryptContext
import sys

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password):
    return pwd_context.hash(password)

def reset_user_password(username, new_password):
    """
    Reset password for a specific user
    """
    # Get database connection parameters from environment variables
    db_host = os.environ.get("POSTGRES_HOST", "db")
    db_port = os.environ.get("POSTGRES_PORT", "5432")
    db_name = os.environ.get("POSTGRES_DB", "flows_db")
    db_user = os.environ.get("POSTGRES_USER", "db_user")  # Use generic default
    db_password = os.environ.get("POSTGRES_PASSWORD", "")  # Empty default password
    
    logger.info(f"Resetting password for user: {username}")
    
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
        
        # Check if user exists
        cursor.execute("SELECT id, email FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        
        if not user:
            logger.error(f"User {username} not found in the database")
            
            # List all available users
            cursor.execute("SELECT username FROM users")
            available_users = cursor.fetchall()
            logger.info("Available users:")
            for user in available_users:
                logger.info(f"  {user[0]}")
            
            return False
        
        user_id, email = user
        logger.info(f"User found with ID: {user_id}. Updating password.")
        
        # Hash the new password
        hashed_password = hash_password(new_password)
        
        # Update the user's password
        cursor.execute(
            "UPDATE users SET hashed_password = %s WHERE id = %s",
            (hashed_password, user_id)
        )
        
        # Make sure user is active
        cursor.execute(
            "UPDATE users SET is_active = TRUE WHERE id = %s",
            (user_id,)
        )
        
        logger.info(f"Password updated for user {username}")
        
        # Check if there's a customer for this user
        cursor.execute("SELECT id FROM customers WHERE email = %s", (email,))
        customer = cursor.fetchone()
        
        if not customer:
            # Create a customer for the user if needed
            customer_name = username.replace(".", " ").title()
            cursor.execute(
                "INSERT INTO customers (name, email, company) VALUES (%s, %s, %s) RETURNING id",
                (customer_name, email, "NexusAI")
            )
            customer_id = cursor.fetchone()[0]
            
            # Link user to customer
            cursor.execute(
                "UPDATE users SET customer_id = %s WHERE id = %s",
                (customer_id, user_id)
            )
            logger.info(f"Created and linked customer with ID {customer_id} to user {username}")
        
        logger.info(f"Password reset completed. User {username} can now login with the new password")
        return True
        
    except Exception as e:
        logger.error(f"Error resetting user password: {str(e)}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

def create_user(username, email, password, role="customer"):
    """
    Create a new user if it doesn't exist
    """
    # Get database connection parameters from environment variables
    db_host = os.environ.get("POSTGRES_HOST", "db")
    db_port = os.environ.get("POSTGRES_PORT", "5432")
    db_name = os.environ.get("POSTGRES_DB", "flows_db")
    db_user = os.environ.get("POSTGRES_USER", "db_user")  # Use generic default
    db_password = os.environ.get("POSTGRES_PASSWORD", "")  # Empty default password
    
    logger.info(f"Creating user: {username}")
    
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
        
        # Check if user already exists
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        
        if user:
            logger.info(f"User {username} already exists with ID: {user[0]}")
            return False
        
        # Create a customer 
        customer_name = username.replace(".", " ").title()
        cursor.execute(
            "INSERT INTO customers (name, email, company) VALUES (%s, %s, %s) RETURNING id",
            (customer_name, email, "NexusAI")
        )
        customer_id = cursor.fetchone()[0]
        logger.info(f"Created customer with ID {customer_id}")
        
        # Hash the password
        hashed_password = hash_password(password)
        
        # Create the user
        cursor.execute(
            """
            INSERT INTO users (username, email, hashed_password, role, is_active, customer_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (username, email, hashed_password, role, True, customer_id)
        )
        logger.info(f"Created new user: {username}")
        return True
        
    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python reset_user_password.py <username> <new_password>")
        print("Or: python reset_user_password.py create <username> <email> <password> [role]")
        sys.exit(1)
        
    if sys.argv[1] == "create":
        if len(sys.argv) < 5:
            print("Usage for create: python reset_user_password.py create <username> <email> <password> [role]")
            sys.exit(1)
            
        username = sys.argv[2]
        email = sys.argv[3]
        password = sys.argv[4]
        role = sys.argv[5] if len(sys.argv) > 5 else "customer"
        
        create_user(username, email, password, role)
    else:
        username = sys.argv[1]
        new_password = sys.argv[2]
        
        reset_user_password(username, new_password)
