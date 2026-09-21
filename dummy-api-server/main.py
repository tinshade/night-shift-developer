from typing import List
from fastapi import FastAPI, HTTPException, Depends, APIRouter, Request
from fastapi.responses import JSONResponse
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


def report_exception(message: str) -> None:
    """Record an unexpected failure so the night-shift worker can pick it up.

    Only genuine defects go through here. An expected 4xx (a missing record, a
    bad payload) is normal behaviour and must NOT be logged at ERROR level, or
    the repair pipeline will be handed work that has nothing to fix.
    """
    trace = traceback.format_exc()
    logger.exception(message)
    log_manager.write_log(
        log_type="ERROR",
        application_name=APPLICATION_NAME,
        message=message,
        trace=trace,
    )


# Initialize FastAPI application
def custom_function(guid: str, record: dict[str, str]) -> str:
    """Perform the application-specific action for an error log."""
    logger.info("Processing log %s from %s", guid, record.get("application"))
    return "fixed"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Trigger table creation on app startup
    init_models()
    yield
    # Clean up engine connections on shutdown
    engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Turn any unhandled failure into an ERROR log the repair worker can claim.

    Without this, a defect that raises outside a route's own try/except - a
    ZeroDivisionError in a handler, a ResponseValidationError during
    serialisation - returns 500 to the caller but never reaches Redis, so the
    night-shift worker is never woken up.

    HTTPException is deliberately not routed here: a 404 or 422 is expected
    behaviour, and FastAPI's own handler deals with it.
    """
    report_exception(f"{type(exc).__name__}: {exc} at {request.method} {request.url.path}")
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.get("/", status_code=200)
@app.get("/health", status_code=200)
def health_check():
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


@app.get("/logs/stats", status_code=200)
def log_stats(status: str = "open"):
    """Report how many logs sit in each repair status."""
    counts = log_manager.count_by_status()
    selected = counts.get(status, 0)
    share = counts.get("open", 0) / selected if selected else 0.0
    return {"counts": counts, "status": status, "open_share": share}


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


@router.post("/create", status_code=201, response_model=schemas.UserRead)
def create_user(user_payload: schemas.UserBase, db:Session = Depends(get_db)):
    try:
        formatted_name = user_payload.first_name.title()

        new_user = models.User(**user_payload.dict())
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        write_application_log("INFO", f"New user named {formatted_name} was created")
        return new_user
    except Exception as e:
        db.rollback()
        report_exception("Error while creating user")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", status_code=200, response_model=List[schemas.UserRead])
def list_users(limit: int = 10, offset: int = 0, db:Session = Depends(get_db)):
    """Return a page of users. `limit` caps the page size, `offset` skips rows."""
    users = db.query(models.User).order_by(models.User.id).offset(offset).limit(limit).all()
    write_application_log("INFO", f"Listed users limit={limit} offset={offset} at {datetime.now()}")
    return users


@router.get("/{id}", status_code=200, response_model=schemas.UserRead)
def get_user(id:int, db:Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == id).first()
    write_application_log("INFO", f"Ran get user for id {id}")
    return user


@router.delete("/{id}", status_code=200)
def delete_user(id:int, db:Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == id).first()
    if not user:
        # Expected condition, not a defect. See get_user above.
        logger.warning("Tried to delete a non-existing user with id %s", id)
        raise HTTPException(status_code = 404, detail=f"No user found with id {id}")
    db.delete(user)
    db.commit()
    write_application_log("INFO", f"Deleted user with id {id}")
    return {"message": "User deleted successfully!", "data": None}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
