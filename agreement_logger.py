import csv
import os
import time
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

CSV_FILE = "agreements_log.csv"

def log_agreement_to_csv(user_id: int, username: str = None):
    """Дописывает запись о принятии соглашения в CSV-файл."""
    try:
        file_exists = os.path.isfile(CSV_FILE)
        timestamp = int(time.time())
        datetime_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        username = username if username else "None"

        with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "datetime", "user_id", "username"])
            writer.writerow([timestamp, datetime_str, user_id, username])
    except Exception as e:
        logger.error(f"Ошибка записи в CSV-файл: {e}")
