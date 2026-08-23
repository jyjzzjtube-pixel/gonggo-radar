@echo off
chcp 65001 >nul
cd /d C:\Users\jyjzz\WORKSPACE\apps\gonggo_radar
echo [공공공고 레이더] 최신 공고 수집 중...
python build_static.py 3
echo.
echo 로컬 서버 시작: http://127.0.0.1:5095/app/
start "" http://127.0.0.1:5095/app/
python server.py
