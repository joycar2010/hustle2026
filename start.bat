@echo off
echo Starting MT5 Microservice...
cd /d %~dp0
python -m venv venv
call venv\Scripts\activate.bat
pip install -r requirements.txt
python app/main.py
