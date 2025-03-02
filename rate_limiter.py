from datetime import datetime, timedelta
from collections import defaultdict
import time
from fastapi import Request, HTTPException, status, Depends
import logging

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self):
        self.requests = defaultdict(list)
        # Store IP-based authentication attempts
        self.auth_attempts = defaultdict(list)
        # Maximum failed login attempts before temporary lockout
        self.max_auth_failures = 5
        # Lockout duration in minutes
        self.auth_lockout_minutes = 15
    
    def is_allowed(self, api_key: str, rate_limit: int) -> bool:
        """Check if request is allowed based on rate limit"""
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)
        
        # Clean old requests
        self.requests[api_key] = [
            req_time for req_time in self.requests[api_key]
            if req_time > minute_ago
        ]
        
        # Check rate limit
        if len(self.requests[api_key]) >= rate_limit:
            return False
        
        # Add new request
        self.requests[api_key].append(now)
        return True

    def is_auth_allowed(self, ip_address: str) -> bool:
        """
        Check if login attempt is allowed based on previous failed attempts
        Returns True if allowed, False if rate limited
        """
        now = datetime.now()
        lockout_time = now - timedelta(minutes=self.auth_lockout_minutes)
        
        # Clean old attempts that are outside the lockout window
        self.auth_attempts[ip_address] = [
            attempt for attempt in self.auth_attempts[ip_address]
            if attempt['time'] > lockout_time
        ]
        
        # Count recent failed attempts
        failed_attempts = sum(1 for attempt in self.auth_attempts[ip_address] 
                           if not attempt['success'])
        
        # Check if IP is locked out
        if failed_attempts >= self.max_auth_failures:
            latest_attempt = max([a['time'] for a in self.auth_attempts[ip_address]], default=datetime.min)
            lockout_until = latest_attempt + timedelta(minutes=self.auth_lockout_minutes)
            time_left = (lockout_until - now).total_seconds() / 60
            
            if time_left > 0:
                logger.warning(f"Authentication attempt blocked due to rate limiting for IP: {ip_address}")
                return False
        
        return True
    
    def record_auth_attempt(self, ip_address: str, success: bool):
        """Record an authentication attempt"""
        now = datetime.now()
        self.auth_attempts[ip_address].append({
            'time': now,
            'success': success
        })
        
        # Log suspicious activity
        if not success:
            failed_attempts = sum(1 for attempt in self.auth_attempts[ip_address] 
                               if not attempt['success'] and attempt['time'] > now - timedelta(minutes=30))
            
            if failed_attempts >= 3:
                logger.warning(f"Multiple failed login attempts detected from IP: {ip_address}")

# Create global rate limiter instance
rate_limiter = RateLimiter()

def check_auth_rate_limit(request: Request):
    """
    Dependency to check if authentication request is allowed
    based on IP address rate limiting
    """
    client_ip = request.client.host
    
    if not rate_limiter.is_auth_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later."
        )
    
    return client_ip
