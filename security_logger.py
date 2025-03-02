import logging
import os
from datetime import datetime
import json
from typing import Dict, Any, Optional
from fastapi import Request

# Configure security-specific logger
logger = logging.getLogger("security")
logger.setLevel(logging.INFO)

# Create a file handler for security logs
os.makedirs("logs", exist_ok=True)
security_log_file = os.path.join("logs", "security.log")
file_handler = logging.FileHandler(security_log_file)

# Create a formatter that obscures sensitive data
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

class SecurityLogger:
    @staticmethod
    def mask_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """Mask sensitive data in logs"""
        SENSITIVE_FIELDS = {
            "password", "token", "api_key", "secret", "credit_card", 
            "card_number", "cvv", "expiry", "access_token", "refresh_token"
        }
        
        masked_data = {}
        for key, value in data.items():
            if key.lower() in SENSITIVE_FIELDS:
                masked_data[key] = "********"
            elif isinstance(value, dict):
                masked_data[key] = SecurityLogger.mask_sensitive_data(value)
            elif isinstance(value, list):
                masked_data[key] = [
                    SecurityLogger.mask_sensitive_data(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                masked_data[key] = value
        
        return masked_data
    
    @staticmethod
    def log_login_attempt(username: str, ip_address: str, success: bool, user_agent: Optional[str] = None):
        """Log login attempts"""
        security_event = {
            "event_type": "login_attempt",
            "timestamp": datetime.now().isoformat(),
            "username": username,
            "ip_address": ip_address,
            "success": success,
            "user_agent": user_agent
        }
        
        if success:
            logger.info(f"Successful login: {username} from {ip_address}")
        else:
            logger.warning(f"Failed login attempt: {username} from {ip_address}")
        
        logger.debug(json.dumps(security_event))
    
    @staticmethod
    def log_api_access(request: Request, user_id: str, endpoint: str):
        """Log API access"""
        security_event = {
            "event_type": "api_access",
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "ip_address": request.client.host,
            "method": request.method,
            "endpoint": endpoint,
            "user_agent": request.headers.get("user-agent", "unknown")
        }
        
        logger.info(f"API access: {user_id} accessed {endpoint} from {request.client.host}")
        logger.debug(json.dumps(security_event))
    
    @staticmethod
    def log_unauthorized_access(request: Request, endpoint: str):
        """Log unauthorized access attempts"""
        security_event = {
            "event_type": "unauthorized_access",
            "timestamp": datetime.now().isoformat(),
            "ip_address": request.client.host,
            "method": request.method,
            "endpoint": endpoint,
            "user_agent": request.headers.get("user-agent", "unknown"),
            "headers": dict(request.headers)
        }
        
        logger.warning(f"Unauthorized access attempt to {endpoint} from {request.client.host}")
        logger.debug(json.dumps(SecurityLogger.mask_sensitive_data(security_event)))
    
    @staticmethod
    def log_security_event(event_type: str, details: Dict[str, Any], level: str = "info"):
        """Log a generic security event"""
        security_event = {
            "event_type": event_type,
            "timestamp": datetime.now().isoformat(),
            "details": details
        }
        
        masked_event = SecurityLogger.mask_sensitive_data(security_event)
        
        if level == "info":
            logger.info(f"Security event: {event_type}")
            logger.debug(json.dumps(masked_event))
        elif level == "warning":
            logger.warning(f"Security warning: {event_type}")
            logger.debug(json.dumps(masked_event))
        elif level == "error":
            logger.error(f"Security error: {event_type}")
            logger.debug(json.dumps(masked_event))
        elif level == "critical":
            logger.critical(f"Critical security event: {event_type}")
            logger.debug(json.dumps(masked_event))
