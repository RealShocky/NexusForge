from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from database import get_db, User
from auth import get_current_user_from_cookie, get_password_hash
from fastapi.templating import Jinja2Templates

router = APIRouter()

templates = Jinja2Templates(directory="templates")

@router.get("/account-settings", response_class=HTMLResponse)
async def account_settings(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_from_cookie)):
    """Render the account settings page"""
    if not current_user:
        return RedirectResponse(url="/login")
    
    return templates.TemplateResponse("account_settings.html", {
        "request": request,
        "user": current_user
    })

@router.post("/account-settings", response_class=HTMLResponse)
async def update_account(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_cookie),
    username: str = Form(None),
    email: str = Form(None),
    current_password: str = Form(None),
    new_password: str = Form(None),
    confirm_password: str = Form(None)
):
    """Update account settings"""
    if not current_user:
        return RedirectResponse(url="/login")
    
    # Create a dictionary to store messages
    messages = {
        "success": None,
        "errors": {}
    }
    
    # Update username if provided
    if username and username != current_user.username:
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user and existing_user.id != current_user.id:
            messages["errors"]["username"] = "Username already taken"
        else:
            current_user.username = username
            messages["success"] = "Account updated successfully"
    
    # Update email if provided
    if email and email != current_user.email:
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user and existing_user.id != current_user.id:
            messages["errors"]["email"] = "Email already in use"
        else:
            current_user.email = email
            if not messages["success"]:
                messages["success"] = "Account updated successfully"
    
    # Update password if provided
    if new_password:
        if not current_password:
            messages["errors"]["current_password"] = "Current password is required"
        elif not current_user.verify_password(current_password):
            messages["errors"]["current_password"] = "Current password is incorrect"
        elif new_password != confirm_password:
            messages["errors"]["confirm_password"] = "Passwords do not match"
        else:
            current_user.password_hash = get_password_hash(new_password)
            if not messages["success"]:
                messages["success"] = "Account updated successfully"
    
    # Save changes if there are no errors
    if not messages["errors"] and messages["success"]:
        db.commit()
    
    return templates.TemplateResponse("account_settings.html", {
        "request": request,
        "user": current_user,
        "messages": messages
    })
