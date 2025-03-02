from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Optional
from datetime import timedelta
import os
import logging
import stripe

from database import get_db, User, Customer, APIKey, UsageRecord
from auth import (
    Token, UserCreate, UserResponse, 
    get_current_user, get_current_active_user, get_admin_user,
    authenticate_user, create_access_token, create_user, 
    ACCESS_TOKEN_EXPIRE_MINUTES, UserRole, is_admin_exists,
    get_current_user_from_cookie
)
from csrf_protection import verify_csrf_token, get_csrf_token
from password_policy import validate_password_strength
from rate_limiter import rate_limiter, check_auth_rate_limit
from security_logger import SecurityLogger

# Configure templates
templates = Jinja2Templates(directory=str(os.path.join(os.path.dirname(__file__), "templates")))

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Create router
router = APIRouter()

# API Routes for authentication
@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/api/register", response_model=UserResponse)
async def register_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    db_email = db.query(User).filter(User.email == user.email).first()
    if db_email:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # If no admin exists yet, make the first user an admin
    if not is_admin_exists(db):
        user.role = UserRole.ADMIN.value
    
    return create_user(db=db, user=user)

@router.get("/api/users/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user

# Web interface routes
@router.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse(url="/landing")

# Landing page route
@router.get("/landing", response_class=HTMLResponse)
async def landing_page(request: Request, current_user: User = Depends(get_current_user_from_cookie)):
    print(f"Landing page - Current user: {current_user}")
    logging.info(f"Landing page - Current user: {current_user}")
    return templates.TemplateResponse("landing.html", {"request": request, "user": current_user})

# Login route
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse("login.html", {"request": request, "error": error, "csrf_token": get_csrf_token()})

@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_csrf_token),
    client_ip: str = Depends(check_auth_rate_limit)
):
    user = authenticate_user(db, username, password)
    if not user:
        # Record failed login attempt
        rate_limiter.record_auth_attempt(client_ip, success=False)
        
        # Log failed login attempt
        SecurityLogger.log_login_attempt(
            username=username, 
            ip_address=client_ip, 
            success=False, 
            user_agent=request.headers.get("user-agent")
        )
        
        return templates.TemplateResponse(
            "login.html", 
            {"request": request, "error": "Incorrect username or password", "csrf_token": get_csrf_token()}
        )
    
    # Record successful login attempt
    rate_limiter.record_auth_attempt(client_ip, success=True)
    
    # Log successful login
    SecurityLogger.log_login_attempt(
        username=username, 
        ip_address=client_ip, 
        success=True, 
        user_agent=request.headers.get("user-agent")
    )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": username}, expires_delta=access_token_expires
    )
    
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="access_token", 
        value=f"Bearer {access_token}", 
        httponly=True, 
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=True,
        path="/"
    )
    
    return response

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse("register.html", {"request": request, "error": error, "csrf_token": get_csrf_token()})

@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    company: str = Form(""),
    terms: bool = Form(...),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_csrf_token)
):
    # Validate form inputs
    if password != confirm_password:
        return templates.TemplateResponse(
            "register.html", 
            {"request": request, "error": "Passwords do not match", "csrf_token": get_csrf_token()}
        )
    
    if not terms:
        return templates.TemplateResponse(
            "register.html", 
            {"request": request, "error": "You must agree to the Terms of Service", "csrf_token": get_csrf_token()}
        )
    
    # Check if username already exists
    db_user = db.query(User).filter(User.username == username).first()
    if db_user:
        return templates.TemplateResponse(
            "register.html", 
            {"request": request, "error": "Username already registered", "csrf_token": get_csrf_token()}
        )
    
    # Check if email already exists
    db_email = db.query(User).filter(User.email == email).first()
    if db_email:
        return templates.TemplateResponse(
            "register.html", 
            {"request": request, "error": "Email already registered", "csrf_token": get_csrf_token()}
        )
    
    # Validate password strength
    is_strong, password_error = validate_password_strength(password)
    if not is_strong:
        return templates.TemplateResponse(
            "register.html", 
            {"request": request, "error": password_error, "csrf_token": get_csrf_token()}
        )
    
    # Create user
    role = UserRole.CUSTOMER.value
    if not is_admin_exists(db):
        role = UserRole.ADMIN.value
    
    user = UserCreate(username=username, email=email, password=password, role=role)
    db_user = create_user(db=db, user=user)
    
    # If user is a customer, create a customer record
    if role == UserRole.CUSTOMER.value:
        # Create Stripe customer first
        try:
            stripe_customer = stripe.Customer.create(
                email=email,
                name=username,
                metadata={"company": company}
            )
            
            # Create customer in database
            customer = Customer(
                name=username,
                email=email,
                company=company,
                stripe_customer_id=stripe_customer.id
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)
            
            # Link user to customer
            db_user.customer_id = customer.id
            db.commit()
            
        except Exception as e:
            logging.error(f"Error creating customer: {str(e)}")
            # Continue anyway - we can link the user to a customer later
    
    # Create access token and redirect
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": username}, expires_delta=access_token_expires
    )
    
    try:
        # Check if user has customer_id to determine redirect
        db.refresh(db_user)
        redirect_url = "/dashboard" if db_user.customer_id else "/admin"
    except:
        # If any error occurs, default to dashboard which will handle the redirect
        redirect_url = "/dashboard"
    
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True, max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60, secure=True)
    
    return response

@router.post("/logout")
async def logout(request: Request, response: Response):
    # Clear the access token cookie
    response.delete_cookie(key="access_token")
    
    # Log the logout event
    user = await get_current_user_from_cookie(request)
    if user:
        SecurityLogger.log_security_event(
            event_type="logout",
            details={
                "username": user.username,
                "ip_address": request.client.host,
                "user_agent": request.headers.get("user-agent")
            }
        )
    
    return RedirectResponse(url="/login", status_code=303)

# Dashboard route - protect with authentication
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_redirect(request: Request, current_user: User = Depends(get_current_active_user)):
    # Ensure db session is refreshed to get latest customer_id
    if not current_user.customer_id and current_user.role == UserRole.ADMIN.value:
        # Admin users without a customer_id go to admin dashboard
        return RedirectResponse(url="/admin")
    elif not current_user.customer_id:
        # Users with no customer_id but not admin get an error
        return templates.TemplateResponse(
            "error.html", 
            {"request": request, "error": "No customer account found for this user. Please contact support."}
        )
    
    # Regular users go to their customer dashboard
    return templates.TemplateResponse(
        "dashboard.html", 
        {"request": request, "user": current_user}
    )

# Debug route to list all users
@router.get("/debug/users")
async def list_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [{"id": user.id, "username": user.username, "email": user.email, "role": user.role} for user in users]

# Admin dashboard redirects to admin_routes
@router.get("/admin", response_class=HTMLResponse)
async def admin_redirect(request: Request, current_user: User = Depends(get_current_user)):
    # Check if user is authenticated and has admin role
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions. Admin role required."
        )
    
    # Use the admin dashboard function directly from admin.py
    from admin import admin_dashboard
    db = next(get_db())  # Get a proper DB session
    return await admin_dashboard(request, db, current_user)

# Landing page routes for features, pricing, etc.
@router.get("/features", response_class=HTMLResponse)
async def features_page(request: Request, current_user: User = Depends(get_current_user_from_cookie)):
    return templates.TemplateResponse("features.html", {"request": request, "user": current_user})

@router.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request, current_user: User = Depends(get_current_user_from_cookie)):
    return templates.TemplateResponse("pricing.html", {"request": request, "user": current_user, "current_user": current_user})

@router.get("/contact", response_class=HTMLResponse)
async def contact_page(request: Request, current_user: User = Depends(get_current_user_from_cookie)):
    return templates.TemplateResponse("contact.html", {"request": request, "user": current_user, "current_user": current_user})
