# src/settings.py
import json
import os
import logging

SETTINGS_FILE = "settings.json"
TEMP_DIR_NAME = "app_temp"

DEFAULT_SETTINGS = {
    "api_key": "",
    "last_model": "gemini-2.5-flash",
    "batch_size": 100,
    "max_retries": 5,
    "ocr_language": "Auto",
    "generation_config": {
        "temperature": 0.3,
        "top_p": 0.95,
        "top_k": 40
    },
    "bdsup2sub_path": "assets/BDSup2Sub.jar",
    "safety_settings": [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
    ],
    "last_failed_batches": []
}

def load_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()

    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            user_settings = json.load(f)
        
        settings = DEFAULT_SETTINGS.copy()
        settings.update(user_settings)
        
        for key, value in DEFAULT_SETTINGS.items():
            if isinstance(value, dict):
                if key not in settings or not isinstance(settings[key], dict):
                    settings[key] = value.copy()
                else:
                    nested_dict = value.copy()
                    nested_dict.update(settings[key])
                    settings[key] = nested_dict

        if settings != user_settings:
            save_settings(settings)
            
        return settings
    except (json.JSONDecodeError, IOError):
        return DEFAULT_SETTINGS.copy()

def save_settings(settings_data: dict):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_data, f, indent=4, ensure_ascii=False)
    except IOError as e:
        logging.error(f"Error saving settings to {SETTINGS_FILE}: {e}")