@echo off
title NSE Trading Decision Support System
color 0A

echo ============================================
echo  NSE Trading Decision Support System
echo  Starting Dashboard...
echo ============================================
echo.

REM Change to the directory where this batch file lives
cd /d "%~dp0"
echo Working directory: %cd%
echo.

REM Check Python
echo [1/4] Checking Python installation...
python --version 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Python not found!
    echo Please install Python 3.9+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)
echo       Python found.
echo.

REM Install dependencies
echo [2/4] Checking dependencies...
pip install streamlit yfinance pandas numpy feedparser requests beautifulsoup4 plotly --quiet 2>nul
if errorlevel 1 (
    echo WARNING: Some packages may have failed to install.
    echo Trying again with --user flag...
    pip install --user streamlit yfinance pandas numpy feedparser requests beautifulsoup4 plotly --quiet 2>nul
)
echo       Dependencies ready.
echo.

REM Create data directory
if not exist data mkdir data

REM Initialize database
echo [3/4] Initializing database...
python -c "import sys; sys.path.insert(0, '.'); from modules.database import init_database; init_database(); print('       Database ready.')"
if errorlevel 1 (
    echo.
    echo ERROR: Database initialization failed!
    echo Check the error message above.
    echo.
    pause
    exit /b 1
)

REM Store fundamentals
python -c "import sys; sys.path.insert(0, '.'); from modules.fundamental_filter import store_fundamentals; store_fundamentals(); print('       Fundamentals loaded.')"
if errorlevel 1 (
    echo WARNING: Fundamentals loading had issues, but continuing...
)
echo.

REM Start Streamlit
echo [4/4] Starting Streamlit dashboard...
echo.
echo ============================================
echo  Dashboard will open at:
echo  http://localhost:8501
echo.
echo  If it doesn't open automatically, copy the
echo  URL above and paste it in your browser.
echo.
echo  Press Ctrl+C to stop the server.
echo ============================================
echo.

streamlit run app.py --server.port 8501 --server.headless false --browser.gatherUsageStats false 2>&1

echo.
echo ============================================
echo  Dashboard has stopped.
echo ============================================
echo.
echo If you saw errors above, please share them
echo so the issue can be fixed.
echo.
pause
