from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import secrets

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: FastAPI,
        **kwargs
    ):
        super().__init__(app)
        self.csp_directives = kwargs.get("csp_directives", self._default_csp_directives())
        self.hsts_max_age = kwargs.get("hsts_max_age", 31536000)  # 1 year in seconds
        self.include_subdomains = kwargs.get("include_subdomains", True)
        self.preload = kwargs.get("preload", False)
        self.xfo_option = kwargs.get("xfo_option", "DENY")
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Add Content-Security-Policy header
        if self.csp_directives:
            response.headers["Content-Security-Policy"] = self._build_csp_header()
        
        # Add Strict-Transport-Security header
        if self.hsts_max_age > 0:
            hsts_value = f"max-age={self.hsts_max_age}"
            if self.include_subdomains:
                hsts_value += "; includeSubDomains"
            if self.preload:
                hsts_value += "; preload"
            response.headers["Strict-Transport-Security"] = hsts_value
        
        # Add X-Content-Type-Options header
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Add X-Frame-Options header
        response.headers["X-Frame-Options"] = self.xfo_option
        
        # Add X-XSS-Protection header
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Add Referrer-Policy header
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Add Permissions-Policy header
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        
        # Add Cache-Control headers for sensitive pages
        if any(path in request.url.path for path in ["/login", "/register", "/admin", "/dashboard"]):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        
        return response
    
    def _default_csp_directives(self):
        """Default Content Security Policy directives"""
        return {
            "default-src": ["'self'"],
            "script-src": ["'self'", "'unsafe-inline'"],  # Consider removing unsafe-inline in production
            "style-src": ["'self'", "'unsafe-inline'"],
            "img-src": ["'self'", "data:"],
            "font-src": ["'self'"],
            "connect-src": ["'self'"],
            "frame-src": ["'self'"],
            "object-src": ["'none'"],
            "base-uri": ["'self'"],
            "form-action": ["'self'"],
            "frame-ancestors": ["'none'"],
            "upgrade-insecure-requests": []
        }
    
    def _build_csp_header(self):
        """Build the Content-Security-Policy header value"""
        directives = []
        for directive, sources in self.csp_directives.items():
            if sources:
                directives.append(f"{directive} {' '.join(sources)}")
            else:
                directives.append(directive)
        return "; ".join(directives)


def add_security_middleware(app: FastAPI, **kwargs):
    """Add security middleware to FastAPI application"""
    app.add_middleware(SecurityHeadersMiddleware, **kwargs)
    return app
