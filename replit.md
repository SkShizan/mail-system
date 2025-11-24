# Flask Email Campaign Manager

## Overview
This is a Flask-based email campaign manager application that allows users to create, schedule, and manage email campaigns. The application features a modern web interface with campaign management, email scheduling, and SMTP configuration.

## Project Structure
- `app/` - Main application directory
  - `templates/` - HTML templates for the web interface
  - `__init__.py` - Flask application factory
  - `routes.py` - Application routes and endpoints
  - `models.py` - Database models (Campaign, Email, SMTPSettings)
  - `email_sender.py` - Email sending logic with scheduler
- `instance/` - Instance-specific files (database)
- `config.py` - Application configuration
- `run.py` - Application entry point
- `requirements.txt` - Python dependencies

## Features
- Dashboard with email statistics
- Campaign creation and management
- Email composition with template support
- CSV/Excel file upload for bulk recipients
- Email scheduling
- SMTP settings configuration
- Automatic email processing with background scheduler

## Technology Stack
- **Backend**: Flask (Python web framework)
- **Database**: PostgreSQL (via Replit's built-in database)
- **ORM**: Flask-SQLAlchemy
- **Scheduler**: schedule library with threading
- **Data Processing**: pandas, openpyxl for file handling

## Setup on Replit
The application is configured to run on Replit with:
- Host: 0.0.0.0 (all interfaces)
- Port: 5000 (required for Replit webview)
- Database: PostgreSQL (automatically configured via DATABASE_URL)

## Environment Variables
- `DATABASE_URL` - PostgreSQL connection string (auto-configured by Replit)
- `SECRET_KEY` - Flask secret key (optional, falls back to default)

## Running the Application
The application runs automatically via the configured workflow. The scheduler starts automatically and processes pending emails every 10 seconds.

## Deployment
Configured for Replit Autoscale deployment:
- Stateless web application
- Automatic scaling based on traffic
- Uses PostgreSQL database for persistence

## Recent Changes (November 24, 2025)
- Imported from GitHub repository
- Configured for Replit environment
- Updated to use host 0.0.0.0 and port 5000
- Added psycopg2-binary for PostgreSQL support
- Set up workflow for automatic application startup
- Configured deployment settings for Replit Autoscale
