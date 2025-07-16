"""Module to handle the main FastAPI application and its endpoints."""
import logging
import json
import importlib
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from schema import task_states
from router import gmail, file, extract
from models.db import MongodbClient

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s')
logging.getLogger().setLevel(logging.INFO)
app = FastAPI(docs_url="/")

class Config:
    """
    Config class for application settings.

    Attributes:
        SCHEDULER_API_ENABLED (bool): Indicates whether the scheduler's API is enabled.
        JOBS (list): List of scheduled jobs loaded from jobs.json file.
    """
    with open('jobs.json', 'r', encoding='utf-8') as jobs_file:
        JOBS = json.load(jobs_file)
    SCHEDULER_API_ENABLED = True

scheduler = BackgroundScheduler()

def load_and_schedule_jobs():
    """Load jobs from jobs.json and schedule them."""
    logger = logging.getLogger(__name__)

    try:
        for job_config in Config.JOBS:
            module_name, function_name = job_config['func'].split(':')
            try:
                module = importlib.import_module(module_name)
                func = getattr(module, function_name)
            except Exception as e:
                logger.error("Failed to import %s: %s", job_config['func'], str(e))
                continue

            # Handle both cron and interval triggers
            if job_config['trigger'] == 'cron':
                trigger = CronTrigger(
                    hour=job_config.get('hour', '*'),
                    minute=job_config.get('minute', '*'),
                    second=job_config.get('second', '0')
                )
                schedule_info = f"at {job_config.get('hour', '*')}:{job_config.get('minute', '*')}"
            elif job_config['trigger'] == 'interval':
                trigger = IntervalTrigger(
                    weeks=job_config.get('weeks', 0),
                    days=job_config.get('days', 0),
                    hours=job_config.get('hours', 0),
                    minutes=job_config.get('minutes', 0),
                    seconds=job_config.get('seconds', 0)
                )
                schedule_info = (
                    f"every {job_config.get('minutes', 0)} minutes "
                    f"{job_config.get('seconds', 0)} seconds"
                )
            else:
                logger.error("Unknown trigger type: %s", job_config['trigger'])
                continue

            scheduler.add_job(
                func=func,
                trigger=trigger,
                id=job_config['id'],
                max_instances=job_config.get('max_instances', 1),
                coalesce=job_config.get('coalesce', True),
                replace_existing=job_config.get('replace_existing', True)
            )

            logger.info("Scheduled job: %s - Will run %s", job_config['id'], schedule_info)
    except Exception as e:
        logger.error("Error loading jobs: %s", str(e))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Handle application startup and shutdown."""
    logger = logging.getLogger(__name__)

    # Startup
    logger.info("Starting Knowledge Base application")
    try:
        load_and_schedule_jobs()
        scheduler.start()
        logger.info("Gmail scheduler started successfully")
    except Exception as e:
        logger.error("Failed to start scheduler: %s", str(e))

    yield

    # Shutdown
    logger.info("Shutting down Knowledge Base application")
    try:
        scheduler.shutdown()
        logger.info("Scheduler shutdown successfully")
    except Exception as e:
        logger.error("Error shutting down scheduler: %s", str(e))


app = FastAPI(docs_url="/", lifespan=lifespan)

app.include_router(gmail.router)
app.include_router(file.router)
app.include_router(extract.router)

origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials = True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/_health")
def health():
    """
    Returns the health status of the application.

    :return: A string "OK" indicating the health status.
    """
    return "OK"

@app.get("/status/{task_id}")
async def get_status(task_id: str):
    """
    Retrieve the status of a task by its ID.

    Args:
        task_id (str): The unique identifier of the task.

    Returns:
        dict: A dictionary containing the task ID and its status. If the task ID is not found,
              the status will be "NOT_FOUND".
    """
    status = task_states.get(task_id, "NOT_FOUND")
    return {"task_id": task_id, "status": status}

@app.get("/tasks/{task_type}")
async def get_tasks(task_type: str, email: str = Query(...)) -> JSONResponse:
    """
    Retrieve tasks of a specific type for a given user email.

    Args:
        task_type (str): The type of tasks to retrieve (e.g., 'todo', 'inprogress', etc.).
        email (str): The email address of the user whose tasks are to be fetched.
            This is expected as a query parameter.

    Returns:
        dict: A dictionary containing the list of tasks associated
            with the provided email and task type.

    Raises:
        HTTPException: If the query parameters are invalid
            or if there is an error accessing the database.

    Note:
        The function assumes that `MongodbClient` is a properly initialized MongoDB client
        and that the relevant collections exist.
    """
    tasks = MongodbClient["task"][task_type].find_one({"_id": email})
    if tasks:
        del tasks["_id"]
        if "tasks" in tasks:
            tasks["tasks"].sort(key=lambda x: x.get("createdTime", ""))
    else:
        tasks = []
    return JSONResponse(content=tasks, status_code=200)
