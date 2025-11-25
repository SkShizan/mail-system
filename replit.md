# Flask Email Campaign Manager

## Overview
This is a Flask-based email campaign manager application that allows users to create, schedule, and manage email campaigns. The application features a modern web interface with campaign management, email scheduling, and SMTP configuration, powered by a professional Celery task queue system.

## Project Structure
- `app/` - Main application directory
  - `templates/` - HTML templates for the web interface
  - `__init__.py` - Flask application factory with Celery integration
  - `routes.py` - Application routes and endpoints
  - `models.py` - Database models (Campaign, Email, SMTPSettings)
  - `tasks.py` - Celery tasks for email processing
- `instance/` - Instance-specific files (database)
- `config.py` - Application configuration
- `run.py` - Flask application entry point
- `celery_worker.py` - Celery worker entry point
- `start_celery.sh` - Celery worker and beat startup script
- `requirements.txt` - Python dependencies

## Features
- Dashboard with email statistics
- Campaign creation and management
- Email composition with template support
- CSV/Excel file upload for bulk recipients
- Email scheduling with Celery Beat
- SMTP settings configuration
- Automatic email processing with Celery workers
- Batch email sending for performance
- Automatic retry on failures

## Technology Stack
- **Backend**: Flask (Python web framework)
- **Database**: PostgreSQL (via Replit's built-in database)
- **ORM**: Flask-SQLAlchemy
- **Task Queue**: Celery 5.5+ with Redis broker
- **Message Broker**: Redis
- **Scheduler**: Celery Beat
- **Data Processing**: pandas, openpyxl for file handling

## Architecture

### Email Processing Flow
1. **Scheduler Dispatcher** (runs every 10 seconds via Celery Beat)
   - Finds pending emails due for sending
   - Groups emails into batches of 50
   - Dispatches batch tasks to worker queue

2. **Batch Sender** (Celery workers)
   - Processes email batches in parallel
   - Opens single SMTP connection per batch (efficient)
   - Implements retry logic with exponential backoff
   - Updates email status in database

### Workflows
- **Flask Email Campaign Manager**: Web application on port 5000
- **Celery Worker & Beat**: Background task processor and scheduler

## Setup on Replit
The application is configured to run on Replit with:
- Host: 0.0.0.0 (all interfaces)
- Port: 5000 (required for Replit webview)
- Database: PostgreSQL (automatically configured via DATABASE_URL)
- Redis: Local Redis server on port 6379

## Environment Variables
- `DATABASE_URL` - PostgreSQL connection string (auto-configured by Replit)
- `SECRET_KEY` - Flask secret key (optional, falls back to default)
- `CELERY_BROKER_URL` - Redis connection for Celery (defaults to localhost:6379)
- `CELERY_RESULT_BACKEND` - Redis connection for task results (defaults to localhost:6379)

## Running the Application
The application runs automatically via two configured workflows:
1. Flask web server handles HTTP requests
2. Celery worker + beat processes email tasks and runs scheduled jobs

## Deployment
Configured for Replit Autoscale deployment:
- Stateless web application
- Automatic scaling based on traffic
- Uses PostgreSQL database for persistence
- Celery workers handle background tasks

## Recent Changes (November 25, 2025)
- **Upgraded to Celery + Redis architecture**
  - Replaced simple threading scheduler with professional Celery task queue
  - Added Redis as message broker for distributed task processing
  - Implemented batch email processing for better performance
  - Added automatic retry logic for failed emails
  - Set up Celery Beat for scheduled task execution
- **Configuration improvements**
  - Moved CELERY_BEAT_SCHEDULE into Config class
  - Added proper Celery app initialization with Flask context
  - Fixed routing errors (retry_task redirect)
- **Workflow optimization**
  - Created separate workflow for Celery worker and beat
  - Added Redis auto-start in Celery workflow
  - Maintained Flask workflow on port 5000 for web access

## Performance & Scalability
- Batch processing: Groups emails in batches of 50 for efficient SMTP usage
- Parallel workers: Celery runs 8 concurrent workers by default
- Reusable connections: Single SMTP connection per batch reduces overhead
- Scheduled dispatcher: Checks for pending emails every 10 seconds
- Retry mechanism: Failed emails automatically retry with exponential backoff
