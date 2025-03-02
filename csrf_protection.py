import secrets
import time
from typing import Optional
from fastapi import Request, HTTPException, status, Cookie, Depends
from pydantic import BaseModel

# CSRF token expiration time in seconds (30 minutes)
CSRF_TOKEN_EXPIRE_SECONDS = 1800
# Name for the CSRF token cookie
CSRF_TOKEN_COOKIE_NAME = "csrf_token"
# Name for the CSRF token form field
CSRF_TOKEN_FIELD_NAME = "csrf_token"

class CSRFToken(BaseModel):
    value: str
    expires_at: float  # timestamp when token expires

def _generate_csrf_token() -> CSRFToken:
    """Generate a new CSRF token with expiration time"""
    return CSRFToken(
        value=secrets.token_hex(32),
        expires_at=time.time() + CSRF_TOKEN_EXPIRE_SECONDS
    )

def get_csrf_token(request: Request) -> str:
    """
    Get or generate a CSRF token for the current request.
    If a valid token exists in cookies, use it, otherwise generate a new one.
    """
    existing_token = request.cookies.get(CSRF_TOKEN_COOKIE_NAME)
    if existing_token:
        # In a real implementation, we would verify the token's validity here
        # For simplicity, we're just checking if it exists
        return existing_token
    
    # Generate a new token
    new_token = _generate_csrf_token()
    return new_token.value

async def verify_csrf_token(
    request: Request,
    csrf_token: Optional[str] = Cookie(None, alias=CSRF_TOKEN_COOKIE_NAME)
):
    """
    Verify that the CSRF token in the form data matches the one in cookies.
    This is used as a dependency for POST/PUT/DELETE endpoints.
    """
    # Skip CSRF check for non-browser clients (API clients)
    # Check if the request has an Authorization header
    if "authorization" in request.headers:
        return True
    
    # For API endpoints that don't require CSRF protection
    if request.url.path.startswith("/api/"):
        return True
    
    # For OPTIONS requests (preflight)
    if request.method == "OPTIONS":
        return True
    
    # For GET requests, no CSRF check needed
    if request.method == "GET":
        return True
    
    # For form submissions and other state-changing operations
    if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
        form_data = await request.form()
        form_csrf_token = form_data.get(CSRF_TOKEN_FIELD_NAME)
        
        if not csrf_token or not form_csrf_token or csrf_token != form_csrf_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="CSRF token missing or invalid"
            )
    
    return True

def csrf_protect(func):
    """
    Decorator to add CSRF protection to a route.
    Use this for form handling routes.
    """
    async def wrapper(*args, **kwargs):
        request = kwargs.get("request")
        if not request:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
        
        if not request:
            raise ValueError("Request object not found in arguments")
        
        await verify_csrf_token(request)
        return await func(*args, **kwargs)
    
    return wrapper
