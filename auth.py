import os
from datetime import datetime, timedelta
from typing import Optional, Union, Dict, Any
from fastapi import Depends, FastAPI, HTTPException, status, Request, Cookie
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import User, Customer, SessionLocal, get_db, UserRole
import logging
logger = logging.getLogger(__name__)

# Secret key for JWT token
SECRET_KEY = os.getenv("SECRET_KEY", "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

# Models for authentication
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: Optional[str] = UserRole.CUSTOMER.value

class UserInDB(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool
    hashed_password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool

# Helper functions
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def get_user(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()

def authenticate_user(db: Session, username: str, password: str):
    user = get_user(db, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Get token from either cookie OR authorization header
async def get_token(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
):
    # First try to get from Authorization header
    if token:
        return token
    
    # Then try to get from cookie
    access_token = request.cookies.get("access_token")
    if access_token:
        # Check if it already has "Bearer " prefix
        if access_token.startswith("Bearer "):
            return access_token.replace("Bearer ", "")
        else:
            return access_token
    
    return None

async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(get_token), 
    db: Session = Depends(get_db)
):
    if token is None:
        return None
        
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None
    
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        return None
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if not current_user:
        return None
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_admin_user(current_user: User = Depends(get_current_active_user)):
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user

def create_user(db: Session, user: UserCreate):
    """Create a new user in the database"""
    db_user = User(
        username=user.username,
        email=user.email,
        hashed_password=get_password_hash(user.password),
        role=user.role
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def is_admin_exists(db: Session):
    """Check if an admin user exists"""
    return db.query(User).filter(User.role == UserRole.ADMIN.value).first() is not None

async def get_token_from_cookie(
    request: Request,
    access_token: Optional[str] = Cookie(None)
):
    logger.info(f"Cookie access_token present: {access_token is not None}")
    logger.info(f"Request cookies keys: {request.cookies.keys()}")
    
    if access_token:
        # Check if it already has "Bearer " prefix
        if access_token.startswith("Bearer "):
            token = access_token.replace("Bearer ", "")
            logger.info(f"Extracted token from cookie parameter")
            return token
        else:
            logger.info(f"Using raw token from cookie parameter")
            return access_token
    
    # Also try to get from request.cookies directly as a fallback
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        if cookie_token.startswith("Bearer "):
            token = cookie_token.replace("Bearer ", "")
            logger.info(f"Extracted token from request.cookies")
            return token
        else:
            logger.info(f"Using raw token from request.cookies")
            return cookie_token
    
    logger.warning("No token found in cookies")
    return None

async def get_current_user_from_cookie(
    request: Request,
    token: Optional[str] = Depends(get_token_from_cookie),
    db: Session = Depends(get_db)
):
    logger.info(f"get_current_user_from_cookie called with token present: {token is not None}")
    
    if token is None:
        logger.warning("No token provided to get_current_user_from_cookie")
        return None
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            logger.warning("No username found in token payload")
            return None
        logger.info(f"Token decoded successfully for user: {username}")
    except JWTError as e:
        logger.error(f"JWT error decoding token: {str(e)}")
        return None
    
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        logger.warning(f"No user found for username: {username}")
        return None
    
    logger.info(f"User authenticated: {user.username} (role: {user.role})")
    return user
