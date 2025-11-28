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
- **Fast Batch Sending** - Parallel processing with optimized speed
- **Smart Rate Limit Retry** - Emails hitting rate limits automatically retry
- **Provider-Agnostic** - Works with any SMTP provider (Hostinger, SendGrid, Gmail, etc.)
- **Real-Time Campaign Stats** - Dashboard updates automatically as emails send
- **Email Open Tracking** - Tracks when recipients open emails with unique tracking pixels

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
   - Automatically clears expired rate limit retries
   - Groups emails into batches of 50
   - Dispatches batch tasks to worker queue

2. **Batch Sender** (Celery workers)
   - Processes email batches with 4-second delays between emails
   - Opens single SMTP connection per batch (efficient)
   - **Rate Limit Handling**: Detects 451/quota errors and schedules intelligent retry
   - Updates email status directly via SQL for reliability
   - Maintains delays that respect provider limits

3. **Rate Limit Retry Logic**
   - Smart multi-level detection: 30 sec, 1 min, 1 hour based on failure pattern
   - Email stays in 'pending' status but excluded from send attempts
   - Scheduler automatically retries after cooldown expires
   - Works with all SMTP providers

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

## Recent Changes (November 28, 2025)

### 📊 Comprehensive Campaign Analytics with Charts (November 28, 2025)
**New detailed campaign analytics page with:**
- **Doughnut Chart** - Email distribution (Sent/Failed/Pending)
- **Bar Chart** - Delivery status breakdown with counts
- **Progress Bar** - Real-time campaign completion tracking
- **4 Stat Cards** - Sent, Failed, Pending, Opened with percentages
- **Real-time Updates** - Charts refresh every 2 seconds via API
- **Batch Processing Info** - Track total batches processed
- **Search functionality** - Filter recipient list by status/email

**Features:**
- Automatic chart updates as emails process
- Color-coded status indicators (green=sent, red=failed, yellow=pending)
- Open rate calculation (tracked emails / sent)
- Responsive design works on all devices

### 🎨 Real-Time Processing Status Indicator (November 28, 2025)
**Added to Frontend Dashboard:**
- New 4th status card showing "Sending..." or "Idle"
- Animated plane icon with green glow when emails are being processed
- Shows real-time processing status every 2 seconds
- Users now see exactly what's happening: pending emails → being sent → completed
- Smooth animations and visual feedback

**Why This Matters:**
- Terminal shows "Pending = 0" because emails are processed in batches continuously
- Frontend now reflects the actual system activity
- Users understand emails ARE being sent even when pending count is 0

### 🔧 CRITICAL FIX: Scheduler Timezone Bug (November 28, 2025)
**Problem**:
- 24 pending emails stuck and not being sent
- Scheduler dispatcher not picking them up despite being scheduled for the past

**Root Cause**: 
- Scheduler used `datetime.now()` (local time) instead of `datetime.utcnow()` 
- Database stores all timestamps in UTC
- Time comparison failed: local time > UTC times, so emails never matched "scheduled_time <= now"

**Solution**:
- Changed scheduler_dispatcher to use `datetime.utcnow()`
- Now correctly compares UTC timestamp from database

**Result**:
- ✅ 24 pending emails now being picked up and sent
- ✅ Scheduler correctly identifies all ready-to-send emails
- System fully operational

### 🔴 CRITICAL BUG FIX: Database Commit Issue (November 27, 2025)
**Problem Identified**: 
- Emails were being marked as ✅ sent in logs but NOT updating in database
- 181 pending emails ready to send but staying in pending status
- Root cause: SQLAlchemy ORM mutations not being properly committed in Celery context

**Solution Implemented**:
- ✅ Replaced ORM mutations with explicit SQL UPDATE statements
- ✅ Direct database updates for sent/failed/rate-limited emails
- ✅ Improved error handling with rollback on commit failure
- ✅ Added verbose logging for database commit operations
- ✅ Fixed send_batch_task to properly flush and commit changes

**Performance Impact**: 
- More reliable database persistence
- Cleaner separation between in-memory processing and database commits
- Better error tracking for debugging

### 🔧 Fixed Stuck Emails Issue (November 27, 2025)
**Problem**: 286 emails stuck in pending state for extended periods
- Root cause: Expired rate limit retry times were never cleaned up
- Scheduler couldn't pick them up due to expired retry window logic

**Solution Implemented**:
- Added automatic cleanup in scheduler_dispatcher() function
- Detects expired rate limit retries every 10 seconds
- Clears expired retries and immediately requeues for sending
- Cleared 230+ stuck emails immediately; system resumed normal processing

**Result**: System now catches up automatically on each scheduler run.

### Email Open Tracking 🎯 (November 27, 2025)
**Track when recipients open your emails:**
- Unique tracking pixel injected into every email sent
- Automatically records `opened_at` timestamp when email is opened
- Campaign details page shows: Opened count and Open Rate %
- Privacy-friendly: Uses unique tracking IDs per email
- Works alongside existing sent/pending/failed stats

### Optimized Email Sending Speed
- **Speed**: 30 emails/minute (2 workers with 4-second delays)
- **Batch size**: 50 emails per batch
- **Connection refresh**: Every 500 emails
- **Delay**: 4 seconds between emails for rate limit safety

## Performance & Scalability
- **Multi-User Architecture**: Each user's emails processed independently with their own SMTP settings
- **Batch Processing**: Groups emails in batches of 50 for efficient SMTP usage
- **Parallel Workers**: Celery runs 2 concurrent workers by default
- **Reusable Connections**: Single SMTP connection per batch reduces overhead
- **Smart Dispatcher**: Checks pending emails every 10 seconds, groups by user
- **Retry Mechanism**: Failed emails automatically retry with intelligent delays
- **User Isolation**: Campaigns and settings isolated per user for security
- **Direct SQL Updates**: Reliable database persistence in async context

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

## Troubleshooting

### Pending Emails Not Decreasing
- Check Celery logs for "💾 Database commit successful" messages
- Verify scheduler is running: should show "🔍 Scheduler Running..." every 10 seconds
- Check for rate limit messages: emails hitting limits will show "⏱️" and be queued for retry
- If stuck for long time, check if rate_limit_retry_at has expired (scheduler cleanup will clear them)

### Emails Getting Rate Limited
- Hostinger has strict per-minute limits (~50-60/min)
- Current config: 30/min (2 workers × 4-second delays) = safe operation
- If too many rate limits: increase delay or reduce worker count
- Per-minute limit retry: retries after 1 minute automatically

### Database Commit Errors
- Check if "❌ DATABASE COMMIT ERROR" appears in logs
- Errors are logged with full exception details
- Commits are now using direct SQL for reliability
- If errors persist, check database connectivity
