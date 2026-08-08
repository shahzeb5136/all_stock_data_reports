@echo off
cd /d "%~dp0"

cd /d "%~dp0reports"

echo Running dip_analyzer.py...
python dip_analyzer.py
echo.
echo Running stable_growth_report.py...
python stable_growth_report.py
echo.
echo Running surge_analyzer.py...
python surge_analyzer.py
echo.
echo Done!
pause
