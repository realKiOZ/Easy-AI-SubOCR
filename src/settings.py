# src/settings.py
import json
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

SETTINGS_FILE = "settings.json"
TEMP_DIR_NAME = "app_temp"

DEFAULT_SETTINGS = {
    "api_key": "",
    "last_model": "gemini-2.5-flash",
    "batch_size": 120,
    "max_retries": 5,
    "ocr_language": "Auto",
    "generation_config": {
        "temperature": 0.3,
        "top_p": 0.95,
        "top_k": 64
    },
    "bdsup2sub_path": "BDSup2Sub.jar",
    "safety_settings": [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
    ]
}

def load_settings() -> dict:
    """
    Tải cài đặt từ settings.json.
    Nếu file không tồn tại hoặc bị lỗi, tạo mới với giá trị mặc định.
    Nếu thiếu key mới trong file cũ, sẽ cập nhật từ giá trị mặc định.
    """
    if not os.path.exists(SETTINGS_FILE):
        logging.info(f"Không tìm thấy {SETTINGS_FILE}. Tạo file mới với cài đặt mặc định.")
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS

    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            user_settings = json.load(f)
        
        # Hợp nhất cài đặt người dùng với cài đặt mặc định để đảm bảo có đủ các key
        settings = DEFAULT_SETTINGS.copy()
        settings.update(user_settings)
        
        # Xử lý các dict lồng nhau (nested dicts)
        for key, value in DEFAULT_SETTINGS.items():
            if isinstance(value, dict):
                if key not in settings or not isinstance(settings[key], dict):
                    settings[key] = value
                else:
                    # Hợp nhất dict lồng nhau
                    nested_dict = value.copy()
                    nested_dict.update(settings[key])
                    settings[key] = nested_dict

        # Nếu có thay đổi (thêm key mới), lưu lại file
        if settings != user_settings:
            logging.info("Cập nhật settings.json với các key mới từ phiên bản mặc định.")
            save_settings(settings)
            
        return settings
    except (json.JSONDecodeError, IOError) as e:
        logging.warning(f"Lỗi khi đọc {SETTINGS_FILE}: {e}. Sử dụng cài đặt mặc định.")
        return DEFAULT_SETTINGS

def save_settings(settings_data: dict):
    """Lưu dict cài đặt vào file settings.json."""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_data, f, indent=4, ensure_ascii=False)
    except IOError as e:
        logging.error(f"Lỗi khi lưu cài đặt vào {SETTINGS_FILE}: {e}")
