from typing import List
from fastapi import FastAPI, HTTPException, Depends, APIRouter
from sqlalchemy.orm import Session
import os
import models
import schemas
from database import get_db, engine
from dotenv import load_dotenv
import logging
from datetime import datetime

load_dotenv()

# Initialize Logger
logging.basicConfig(filename="dummy-api-server-logs.log", format='%(asctime)s %(levelname)s: %(message)s', filemode='w+')
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


# Initialize FastAPI Router
router = APIRouter(
        prefix = '/users',
        tags=['Users']
)

# Initialize FastAPI application
app = FastAPI()
app.include_router(router)
models.Base.metadata.create_all(bind=engine) # Ensure that DB connection is able to create new tables

@app.get("/", status_code=200)
@app.get("/health", status_code=200)
def health_check():
    logger.info("Health-check was invoked. Status = Healthy")
    return {"message": "Server is up!"}


@router.post("/create", status_code=201, response_model=schemas.UserBase)
def create_user(user_payload: schemas.UserBase, db:Session = Depends(get_db)):
    try:
        # Code bug: Assumes first_name is always a string and attempts string method call
        formatted_name = user_payload.first_name.title()

        new_user = models.User(**user_payload.dict())
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        logger.info(f"New user named {formatted_name} was created")
        return new_user
    except Exception as e:
        logger.exception("Error while creating user")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{id}", status_code=200, response_model=List[schemas.UserBase])
def get_users(id:int|None=None, db:Session = Depends(get_db)):
    result = None
    if id:
        result = db.query(models.User).filter(models.User.id == id).first()
        return [result]
    result = db.query(models.User).all()
    logger.info(f"Ran get user at {datetime.now()}")
    return result


@router.delete("/{id}", status_code=200)
def delete_user(id:int, db:Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == id).first()
    if not user:
        logger.error("Tried to delete a non-existing user")
        raise HTTPException(status_code = 404, detail=f"No user found with id {id}")
    db.delete(user)
    db.commit()
    logger.info(f"Deleted user with id {id}")
    return {"message": "User deleted successfully!", "data": None}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
