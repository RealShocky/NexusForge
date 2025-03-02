"""
Fix script for bcrypt and passlib compatibility issue
"""
import logging
import os
import sys

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_bcrypt_passlib():
    """
    Create a patch for bcrypt/passlib compatibility issue
    """
    try:
        # Path to the file we need to patch
        bcrypt_file_path = "/usr/local/lib/python3.11/site-packages/passlib/handlers/bcrypt.py"
        
        if not os.path.exists(bcrypt_file_path):
            logger.error(f"File not found: {bcrypt_file_path}")
            return
        
        # Read the file
        with open(bcrypt_file_path, "r") as file:
            content = file.read()
        
        # Check if we need to modify
        if "_bcrypt.__about__.__version__" in content:
            # Replace the problematic line
            modified_content = content.replace(
                "version = _bcrypt.__about__.__version__", 
                "version = getattr(_bcrypt, '__version__', getattr(getattr(_bcrypt, '__about__', None), '__version__', '4.0.1'))"
            )
            
            # Write the modified content back
            with open(bcrypt_file_path, "w") as file:
                file.write(modified_content)
            
            logger.info(f"Successfully patched {bcrypt_file_path}")
        else:
            logger.info(f"No need to patch {bcrypt_file_path}")
        
    except Exception as e:
        logger.error(f"Error fixing bcrypt/passlib: {str(e)}")
        raise

if __name__ == "__main__":
    fix_bcrypt_passlib()
