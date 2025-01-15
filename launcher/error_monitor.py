import os
import sys

# Путь к резервному файлу для записи ошибок
backup_error_log = r"C:\Users\konstpm\Desktop\Beneki\launcher\backup_error_log.txt"

def log_errors_from_file(log_file):
    """
    Копирует весь текст из лог-файла в резервный файл.
    """
    try:
        with open(log_file, 'r', encoding='utf-8') as source_file:
            log_content = source_file.read()
            
            # Записываем содержимое в резервный файл
            with open(backup_error_log, 'a', encoding='utf-8') as backup_file:
                backup_file.write(f"\n--- Errors from {log_file} ---\n")
                backup_file.write(log_content + '\n')
                backup_file.write(f"--- End of errors from {log_file} ---\n")
    except FileNotFoundError:
        log_error(f"Log file {log_file} not found.")

def check_if_file_not_empty(log_file):
    """
    Проверяет, не пуст ли лог-файл.
    Возвращает True, если файл не пустой.
    """
    try:
        if os.path.getsize(log_file) > 0:
            return True
    except FileNotFoundError:
        log_error(f"Log file {log_file} not found.")
    return False

if __name__ == "__main__":
    # Лог-файл для проверки (лог ошибок бота)
    error_log = r"C:\Users\konstpm\Desktop\Beneki\launcher\bot_error_log.txt"
    error_flag = r"C:\Users\konstpm\Desktop\Beneki\error_flag.txt"

    # Проверяем, не пуст ли лог-файл
    if check_if_file_not_empty(error_log):
        # Если файл не пустой, создаём файл-флаг ошибки и копируем весь текст ошибок в бэкап
        with open(error_flag, 'w') as flag_file:
            flag_file.write("Error: log file is not empty.")
        
        # Копируем ошибки в резервный файл
        log_errors_from_file(error_log)
        sys.exit(1)  # Ошибка найдена
    else:
        sys.exit(0)  # Ошибок нет





   



