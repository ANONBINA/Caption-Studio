echo off
cls
mode 1000,500
color 0a
for /l %%i in (1,1,255) do (
    echo %%i
    timeout /t 0.01 >nul
)
