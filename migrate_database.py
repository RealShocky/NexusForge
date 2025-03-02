import os
import logging
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_database():
    """Update the database schema to add missing columns"""
    try:
        # Get the database path
        db_path = os.getenv("DATABASE_URL", "sqlite:///flows.db")
        
        # For SQLite, extract the file path
        if db_path.startswith("sqlite:///"):
            db_path = db_path[10:]
        
        logger.info(f"Migrating database at: {db_path}")
        
        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all columns in the api_keys table
        columns = [row[1] for row in cursor.execute("PRAGMA table_info(api_keys)")]
        
        # Add missing columns
        if "user_id" not in columns:
            logger.info("Adding user_id column to api_keys table")
            cursor.execute("ALTER TABLE api_keys ADD COLUMN user_id INTEGER REFERENCES users(id)")
            conn.commit()
            logger.info("Added user_id column successfully")
        else:
            logger.info("user_id column already exists in api_keys table")
        
        if "masked_key" not in columns:
            logger.info("Adding masked_key column to api_keys table")
            cursor.execute("ALTER TABLE api_keys ADD COLUMN masked_key TEXT")
            conn.commit()
            logger.info("Added masked_key column successfully")
        else:
            logger.info("masked_key column already exists in api_keys table")
        
        if "last_used" not in columns:
            logger.info("Adding last_used column to api_keys table")
            cursor.execute("ALTER TABLE api_keys ADD COLUMN last_used DATETIME")
            conn.commit()
            logger.info("Added last_used column successfully")
        else:
            logger.info("last_used column already exists in api_keys table")
        
        # Close the connection
        conn.close()
        logger.info("Database migration completed successfully")
        
    except Exception as e:
        logger.error(f"Error during database migration: {str(e)}")
        raise

if __name__ == "__main__":
    migrate_database()
