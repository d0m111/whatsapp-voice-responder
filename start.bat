@echo off
echo Starting WhatsApp Voice Responder...
echo ================================

echo Activating Python environment...
call party\Scripts\activate.bat

echo Starting Python backend...
start "Python Backend" python src\main.py

timeout /t 2 /nobreak > nul

echo Starting WhatsApp bot...
cd whatsapp-bot
start "WhatsApp Bot" node index.js
cd ..

echo Done! Both services are running.
echo Close the windows to stop.
