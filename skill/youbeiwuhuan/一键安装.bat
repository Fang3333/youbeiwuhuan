@echo off
rem 邮备无患 · 一键安装入口（双击这个文件即可，等价于让 WorkBuddy 说「帮我安装这个技能」）
echo ============================================
echo   邮备无患 · 一键安装
echo   电脑保持联网，中途会问一次学号和教务密码
echo ============================================
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
echo.
echo  安装流程结束。看到浏览器打开的网页 http://127.0.0.1:3080 就成功了。
pause