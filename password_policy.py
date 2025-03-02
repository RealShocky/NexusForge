import re
from typing import Dict, List, Tuple

def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    Validate password strength according to the following rules:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check length
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    # Check for uppercase
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    # Check for lowercase
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    # Check for digits
    if not re.search(r'\d', password):
        return False, "Password must contain at least one digit"
    
    # Check for special characters
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
    
    # Check for common passwords
    common_passwords = [
        "password", "123456", "qwerty", "admin", "welcome",
        "password123", "admin123", "letmein", "welcome1"
    ]
    
    if password.lower() in common_passwords:
        return False, "Password is too common or easily guessable"
    
    return True, ""
