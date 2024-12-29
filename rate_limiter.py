from datetime import datetime, timedelta
from collections import defaultdict
import time

class RateLimiter:
    def __init__(self):
        self.requests = defaultdict(list)
    
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
