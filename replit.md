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
- **Batch Sending** - Efficient batch processing (20 emails per batch)
- **Smart Rate Limit Retry** - Emails hitting rate limits automatically retry after 1 hour
- **Provider-Agnostic** - Works with any SMTP provider (Hostinger, SendGrid, Gmail, etc.)

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
   - Skips emails waiting for rate limit reset (rate_limit_retry_at field)
   - Groups emails into batches of 20
   - Dispatches batch tasks to worker queue

2. **Batch Sender** (Celery workers)
   - Processes email batches sequentially (1 concurrent worker)
   - Opens single SMTP connection per batch (efficient)
   - **Rate Limit Handling**: Detects 451/quota errors and schedules 1-hour retry
   - Maintains 15-second delay between emails (respects provider limits)
   - Updates email status in database

3. **Rate Limit Retry Logic**
   - When 451 error detected: sets `rate_limit_retry_at = now + 1 hour`
   - Email stays in 'pending' status but is excluded from send attempts
   - Scheduler automatically resends email after 1 hour
   - Works with all SMTP providers (Hostinger, SendGrid, Gmail, etc.)

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

## Recent Changes (November 27, 2025)
- **Intelligent Hourly Rate Limit Retry** ✅
  - Detects 451 rate limit errors from SMTP servers
  - Sets automatic 1-hour retry for rate-limited emails
  - Works with all SMTP providers (Hostinger, SendGrid, Gmail, Mailgun, etc.)
  - Email stays 'pending' but skipped during hourly limit cooldown
  - Automatically retries when 1 hour has passed
  - Prevents wasted retry attempts that count against provider limits
  
- **Ultra-Conservative Rate Limiting Configuration** ✅
  - Celery concurrency: 1 worker (sequential processing)
  - Per-email delay: 15 seconds (respects provider limits)
  - Batch size: 20 emails (conservative for low-limit accounts)
  - Batch dispatch spacing: 1 second (prevents thundering herd)
  - Connection refresh: Every 200 emails (minimizes reconnections)
  - Connection stabilization: 0.5s after connect/reconnect
  
- **Why This Works**: 
  - All emails eventually send—system doesn't abandon them
  - Takes longer (15-20s per email) but respects all provider restrictions
  - No wasted retries that count against hourly limits
  - Professional Celery backend ensures reliable queuing and delivery

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
