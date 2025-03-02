from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from database import SessionLocal, Customer, Budget, CustomerBudget
from pydantic import BaseModel
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Models
class BudgetCreate(BaseModel):
    budget_id: str
    max_budget: float
    tpm: int
    rpm: int

class BudgetAssign(BaseModel):
    user_id: str
    budget_id: str

@router.post("/budget/new")
async def create_budget(budget: BudgetCreate, db: Session = Depends(get_db)):
    """Create a new budget"""
    try:
        logger.info(f"Creating new budget: {budget.budget_id}")
        
        # Check if budget already exists
        existing_budget = db.query(Budget).filter_by(budget_id=budget.budget_id).first()
        if existing_budget:
            raise HTTPException(status_code=400, detail="Budget ID already exists")
        
        # Create new budget
        new_budget = Budget(
            budget_id=budget.budget_id,
            max_budget=budget.max_budget,
            tpm=budget.tpm,
            rpm=budget.rpm
        )
        
        db.add(new_budget)
        db.commit()
        
        return {"message": "Budget created successfully", "budget_id": budget.budget_id}
    
    except Exception as e:
        logger.error(f"Error creating budget: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/budget/assign")
async def assign_budget(assignment: BudgetAssign, db: Session = Depends(get_db)):
    """Assign a budget to a customer"""
    try:
        logger.info(f"Assigning budget {assignment.budget_id} to user {assignment.user_id}")
        
        # Get customer and budget
        customer = db.query(Customer).filter_by(id=assignment.user_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        
        budget = db.query(Budget).filter_by(budget_id=assignment.budget_id).first()
        if not budget:
            raise HTTPException(status_code=404, detail="Budget not found")
        
        # Check if assignment already exists
        existing_assignment = db.query(CustomerBudget).filter_by(
            customer_id=customer.id,
            budget_id=budget.id
        ).first()
        
        if existing_assignment:
            raise HTTPException(status_code=400, detail="Budget already assigned to this customer")
        
        # Create new assignment
        new_assignment = CustomerBudget(
            customer_id=customer.id,
            budget_id=budget.id
        )
        
        db.add(new_assignment)
        db.commit()
        
        return {"message": "Budget assigned successfully"}
    
    except Exception as e:
        logger.error(f"Error assigning budget: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
