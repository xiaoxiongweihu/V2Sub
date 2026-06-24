@echo off
if "%1"=="h" goto begin
start mshta vbscript:createobject("wscript.shell").run("""%~nx0"" h",0)(window.close)&&exit
:begin

:: 后面写你原本要执行的命令
.venv\Scripts\python.exe main.py