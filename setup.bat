@echo off
python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
echo.
echo Setup done. Run:  .venv\Scripts\activate  then  python run_demo.py
