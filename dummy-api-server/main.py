from typing import List
from fastapi import FastAPI, HTTPException, Depends, APIRouter
from sqlalchemy.orm import Session
import os
import models
import schemas
from database import get_db, engine, init_models
from dotenv import load_dotenv
import logging
import traceback
from datetime import datetime
from contextlib import asynccontextmanager
from threading import Thread


# Log manager
from services.redis.log_manager import LogManager


load_dotenv()

# Initialize Logger
logging.basicConfig(filename="dummy-api-server-logs.log", format='%(asctime)s %(levelname)s: %(message)s', filemode='w+')
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
APPLICATION_NAME = "dummy_api_server"


# Initialize FastAPI Router
router = APIRouter(
        prefix = '/users',
        tags=['Users']
)


log_manager = LogManager()


def write_application_log(
    level: str,
    message: str,
    trace: str = "",
    status: str = "open",
):
    log_method = getattr(logger, level.lower(), logger.info)
    log_method(message)
    return log_manager.write_log(
        log_type=level.upper(),
        application_name=APPLICATION_NAME,
        message=message,
        trace=trace,
        status=status,
    )

# Initialize FastAPI application
def custom_function(guid: str, record: dict[str, str]) -> str:
    """Perform the application-specific action for an error log."""
    logger.info("Processing log %s from %s", guid, record.get("application"))
    return "fixed"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Trigger table creation on app startup
    await init_models()
    worker = Thread(
        target=log_manager.consume,
        args=(custom_function,),
        kwargs={"consumer_name": "api-worker"},
        daemon=True,
    )
    worker.start()
    yield
    # Clean up engine connections on shutdown
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(router)
models.Base.metadata.create_all(bind=engine) # Ensure that DB connection is able to create new tables

@app.get("/", status_code=200)
@app.get("/health", status_code=200)
def health_check():
    write_application_log("INFO", "Health-check was invoked. Status = Healthy")
    return {"message": "Server is up!"}


@app.post("/logs", status_code=201, response_model=schemas.LogRecord)
def write_log(log_payload: schemas.LogCreate):
    guid = log_manager.write_log(
        log_type=log_payload.type,
        application_name=log_payload.application,
        message=log_payload.message,
        trace=log_payload.trace,
        status=log_payload.status.value,
    )
    return log_manager.get_log(guid)


@app.get(
    "/logs/{guid}",
    response_model=schemas.LogRecord,
    responses={404: {"description": "Log not found"}},
)
def get_log(guid: str):
    record = log_manager.get_log(guid)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No log found with guid {guid}")
    return record


@router.post("/create", status_code=201, response_model=schemas.UserBase)
def create_user(user_payload: schemas.UserBase, db:Session = Depends(get_db)):
    try:
        # Code bug: Assumes first_name is always a string and attempts string method call
        formatted_name = user_payload.first_name.title()

        new_user = models.User(**user_payload.dict())
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        write_application_log("INFO", f"New user named {formatted_name} was created")
        return new_user
    except Exception as e:
        message = "Error while creating user"
        trace = traceback.format_exc()
        logger.exception(message)
        log_manager.write_log(
            log_type="ERROR",
            application_name=APPLICATION_NAME,
            message=message,
            trace=trace,
        )
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{id}", status_code=200, response_model=List[schemas.UserBase])
def get_users(id:int|None=None, db:Session = Depends(get_db)):
    result = None
    if id:
        result = db.query(models.User).filter(models.User.id == id).first()
        write_application_log("INFO", f"Ran get user for id {id}")
        return [result]
    result = db.query(models.User).all()
    write_application_log("INFO", f"Ran get users at {datetime.now()}")
    return result


@router.delete("/{id}", status_code=200)
def delete_user(id:int, db:Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == id).first()
    if not user:
        write_application_log(
            "ERROR",
            f"Tried to delete a non-existing user with id {id}",
        )
        raise HTTPException(status_code = 404, detail=f"No user found with id {id}")
    db.delete(user)
    db.commit()
    write_application_log("INFO", f"Deleted user with id {id}")
    return {"message": "User deleted successfully!", "data": None}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
