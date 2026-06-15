@echo off
REM ============================================
REM  Daily Pre-Market Analysis Automation
REM  Schedule this with Windows Task Scheduler
REM  to run at 8:15 AM IST daily (Mon-Fri)
REM ============================================
REM
REM TO SET UP WINDOWS TASK SCHEDULER:
REM 1. Open Task Scheduler (search "Task Scheduler" in Start)
REM 2. Click "Create Task" (not Basic Task)
REM 3. General tab: Name = "NSE Morning Analysis", check "Run with highest privileges"
REM 4. Triggers tab: New -> Daily, Start at 8:15 AM, check "Enabled"
REM    Advanced: Check only Mon-Fri (uncheck Sat/Sun)
REM 5. Actions tab: New -> Start a program
REM    Program: Full path to this file, e.g. C:\Users\YOU\nse_trader\DAILY_RUN.bat
REM 6. Conditions tab: Uncheck "Start only if AC power" if on laptop
REM 7. Click OK and enter your Windows password
REM
REM The analysis results will be visible when you open the dashboard.
REM ============================================

cd /d "%~dp0"

echo [%date% %time%] Starting daily analysis... >> logs\daily_run.log 2>&1

REM Create logs directory if needed
if not exist logs mkdir logs

REM Run the data pipeline and analysis
python -c "
import sys
sys.path.insert(0, '.')
from modules.database import init_database, log_system_event
from modules.data_fetcher import run_data_pipeline
from modules.news_engine import process_and_store_news
from modules.fundamental_filter import store_fundamentals

print('Initializing...')
init_database()
store_fundamentals()

print('Running data pipeline...')
success = run_data_pipeline()

if success:
    print('Fetching news...')
    try:
        count = process_and_store_news()
        print(f'Processed {count} news items')
    except Exception as e:
        print(f'News fetch warning: {e}')
    
    log_system_event('scheduler', 'INFO', 'Daily pre-market run completed')
    print('Daily analysis complete!')
else:
    log_system_event('scheduler', 'ERROR', 'Data pipeline failed')
    print('ERROR: Data pipeline failed')
" >> logs\daily_run.log 2>&1

echo [%date% %time%] Daily run finished. >> logs\daily_run.log 2>&1
