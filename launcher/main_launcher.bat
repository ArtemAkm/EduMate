@echo off
setlocal

:: Путь к директории и файлам
set work_dir=C:\Users\konstpm\Desktop\Beneki
set main_script=%work_dir%\main.py
set error_monitor=%work_dir%\launcher\error_monitor.py
set error_flag=%work_dir%\error_flag.txt
set log_file=%work_dir%\launcher\bot_error_log.txt

:loop
cls

:: Проверяем, запущен ли main.py
tasklist /FI "IMAGENAME eq python.exe" | find /I "python.exe" >nul
if %errorlevel% neq 0 (
    echo Main script is not running. Starting main.py...
    cd /d %work_dir%
    start "" "C:\Documents and Settings\konstpm\Local Settings\Programs\Python\Python312\python.exe" %main_script%
    echo Main script started.
) else (
    echo Main script is already running.

    :: Удаляем старый файл флага ошибки, если он существует
    if exist %error_flag% del %error_flag%

    :: Запуск скрипта error_monitor.py для проверки лога ошибок бота
    call "C:\Documents and Settings\konstpm\Local Settings\Programs\Python\Python312\python.exe" %error_monitor%

    :: Проверяем наличие файла флага ошибки
    if exist %error_flag% (
        echo "Critical error found. Restarting script..."
        taskkill /f /im python.exe >nul

        :: Очищаем лог-файл
        type nul > %log_file%

        cd /d %work_dir%
        start "" "C:\Documents and Settings\konstpm\Local Settings\Programs\Python\Python312\python.exe" %main_script%
        
        :: Удаляем файл флага после перезапуска скрипта
        del %error_flag%
    ) else (
        echo No critical errors found.
    )
)

:: Ожидаем 30 секунд перед следующей проверкой
timeout /t 30 /nobreak

:: Возвращаемся к началу цикла
goto loop









































