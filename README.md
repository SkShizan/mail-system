# Flask Email Campaign Manager

## Overview
This Flask-based email campaign manager enables users to create, schedule, and manage email campaigns through a modern web interface. It supports multi-user environments, features robust email scheduling, and integrates per-user SMTP configurations. The system is designed for high-volume sending with a professional Celery task queue, ensuring efficient, background processing, intelligent rate limit handling, and real-time campaign analytics. The project aims to provide a reliable, scalable, and user-friendly platform for managing diverse email marketing needs.

## User Preferences
- I want iterative development.
- I prefer detailed explanations.
- Ask before making major changes.
- Do not make changes to the folder `Z`.
- Do not make changes to the file `Y`.

## System Architecture

### UI/UX Decisions
The application features a modern web interface with a personalized dashboard for each user, providing email statistics, campaign management, and real-time activity logs. Key UI elements include:
- **Dashboard Activity Log**: Real-time infographics show sent/failed email counts, top performing campaigns, and a 7-day timeline of recent campaigns with open rates. This updates every 5 seconds.
- **Campaign Analytics Page**: Provides detailed insights with doughnut charts for email distribution (Sent/Failed/Pending), bar charts for delivery status breakdown, and a progress bar for completion tracking. This updates every 2 seconds.
- **Real-Time Processing Status Indicator**: A visual indicator on the dashboard (e.g., "Sending..." with an animated plane icon) shows current system activity.

### Technical Implementations
- **Backend**: Flask (Python web framework).
- **Authentication**: Flask-Login with password hashing (werkzeug.security).
- **Database**: PostgreSQL (via Replit's built-in database).
- **ORM**: Flask-SQLAlchemy.
- **Task Queue**: Celery 5.5+ with Redis broker.
- **Message Broker**: Redis.
- **Scheduler**: Celery Beat.
- **Timezone Handling**: `pytz` for IST to UTC conversion for scheduling.
- **Data Processing**: `pandas` and `openpyxl` for handling recipient file uploads.
- **Email Tracking**: Unique tracking pixels are embedded in emails to record `opened_at` timestamps, enabling accurate open rate calculations. Proper `multipart/alternative` MIME structure is used for broad email client compatibility.

### Feature Specifications
- **Multi-User Support**: Each user has isolated campaigns, emails, and SMTP settings.
- **Campaign Management**: CRUD operations for email campaigns.
- **Email Composition**: Rich text editor with template support.
- **Bulk Upload**: CSV/Excel support for recipient lists.
- **Smart Scheduling**: Timezone-aware scheduling (IST to UTC conversion).
- **SMTP Integration**: Per-user configurable SMTP settings, provider-agnostic.
- **Automated Processing**: Celery workers handle background email sending.
- **Fast Batch Sending**: Emails grouped into batches of 50 for efficient, parallel processing with connection reuse and intelligent delays.
- **Smart Rate Limit Retry**: Automated multi-level retry logic (30 sec, 1 min, 1 hour) for emails hitting SMTP rate limits, with automatic cleanup of expired retries.
- **Comprehensive Analytics**: Dashboard and campaign-specific analytics with real-time updates for sent, failed, pending, and opened emails.

### System Design Choices
- **Email Processing Flow**:
    1. **Scheduler Dispatcher**: Runs every 10 seconds (Celery Beat) to find pending emails, clear expired rate limit retries, group emails into batches of 50, and dispatch batch tasks to the worker queue. It marks emails as "dispatched" with a `batch_id` to prevent duplicates.
    2. **Batch Sender**: Celery workers process email batches, applying 4-second delays between individual emails. A single SMTP connection is used per batch for efficiency.
    3. **Rate Limit Handling**: Detects 451/quota errors and intelligently schedules retries.
    4. **Database Updates**: Direct SQL `UPDATE` statements are used for reliable status updates (sent, failed, rate-limited) in the Celery context to avoid ORM commit issues.
- **Performance & Scalability**: Designed for multi-user, high-volume sending with parallel Celery workers, batch processing, reusable SMTP connections, and a smart dispatcher.
- **Deployment**: Configured for Replit Autoscale deployment, leveraging PostgreSQL for persistence and Celery workers for background tasks.

## External Dependencies
- **PostgreSQL**: Used as the primary database for application data.
- **Redis**: Serves as the message broker for Celery and for storing task results.
- **Hostinger, SendGrid, Gmail**: Examples of compatible SMTP providers; the system is provider-agnostic.