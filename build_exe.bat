@echo off
rem Builds dist\WIT\WIT.exe with the config folder next to it. Run from the WIT folder.
rem Copy the whole dist\WIT folder to the target machine; edit dist\WIT\config\settings.yaml there.
poetry run pip install pyinstaller "ttkbootstrap==1.10.1"
poetry run pyinstaller --noconfirm --clean --windowed --name WIT --paths src ^
  --collect-data ttkbootstrap --hidden-import PIL._tkinter_finder ^
  --exclude-module docling --exclude-module torch --exclude-module matplotlib --exclude-module scipy ^
  app.py
if errorlevel 1 exit /b 1
xcopy /E /I /Y config dist\WIT\config >nul
echo.
echo Done: dist\WIT\WIT.exe   (config in dist\WIT\config)
