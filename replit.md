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
- **User Authentication** - Secure login/signup with password hashing
- **Multi-User Support** - Each user has their own campaigns, emails, and SMTP settings
- **Dashboard** - Personalized email statistics per user
- **Campaign Management** - Create, edit, and delete email campaigns
- **Email Composition** - Rich text editor with template support
- **Bulk Upload** - CSV/Excel file upload for recipient lists
- **Smart Scheduling** - Schedule emails with IST timezone support (auto-converts to UTC)
- **SMTP Integration** - Per-user SMTP configuration
- **Automated Processing** - Celery workers process emails in background
- **Batch Sending** - Efficient batch processing (50 emails per batch)
- **Auto Retry** - Failed emails automatically retry with exponential backoff

## Technology Stack
- **Backend**: Flask (Python web framework)
- **Authentication**: Flask-Login with password hashing (werkzeug.security)
- **Database**: PostgreSQL (via Replit's built-in database)
- **ORM**: Flask-SQLAlchemy
- **Task Queue**: Celery 5.5+ with Redis broker
- **Message Broker**: Redis
- **Scheduler**: Celery Beat
- **Timezone**: pytz for IST to UTC conversion
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
- **Authentication & Multi-User Support** ✅
  - Implemented secure login/signup system with Flask-Login
  - Added User model with password hashing
  - Per-user campaigns, emails, and SMTP settings
  - Protected all routes with @login_required decorator
  - Database migrations: Added user_id foreign keys to Campaign and SMTPSettings tables
- **Celery + Redis Architecture** ✅
  - Replaced simple threading scheduler with professional Celery task queue
  - Added Redis as message broker for distributed task processing
  - Implemented user-aware batch email processing
  - Batch sender fetches correct SMTP settings per user
  - Dispatcher groups emails by user to prevent mixing
- **Debug Logging** ✅
  - Extensive emoji-based logging throughout the system
  - Scheduler logs every 10 seconds with pending email count
  - Batch sender logs SMTP connection status, each email sent, and final stats
  - IST to UTC conversion logging in routes
- **Timezone Handling** ✅
  - Automatic IST (Asia/Kolkata) to UTC conversion
  - System stores all times in UTC internally
  - User enters times in IST, system converts automatically
- **Bug Fixes** ✅
  - Fixed Celery Beat schedule configuration
  - Fixed flask-login import errors
  - Fixed database schema mismatches
  - Fixed routing errors

## Performance & Scalability
- **Multi-User Architecture**: Each user's emails processed independently with their own SMTP settings
- **Batch Processing**: Groups emails in batches of 50 for efficient SMTP usage
- **Parallel Workers**: Celery runs 8 concurrent workers by default
- **Reusable Connections**: Single SMTP connection per batch reduces overhead
- **Smart Dispatcher**: Checks pending emails every 10 seconds, groups by user
- **Retry Mechanism**: Failed emails automatically retry with exponential backoff
- **User Isolation**: Campaigns and settings isolated per user for security

## How to Use
1. **Sign Up**: Visit `/signup` to create a new account
2. **Login**: Use your credentials at `/login`
3. **Configure SMTP**: Go to Settings and add your SMTP server details
4. **Create Campaign**: Click "Compose" to create a new email campaign
5. **Upload Recipients**: Use CSV/Excel file or paste email addresses
6. **Schedule**: Set time in IST (e.g., 9:27 AM) - system auto-converts to UTC
7. **Monitor**: Dashboard shows real-time stats for your campaigns
8. **Background Processing**: Celery automatically sends emails at scheduled times

## Current Users
- **shizan** (shizankhan011@gmail.com)
- **glennscape** (glennscape2@gmail.com)
