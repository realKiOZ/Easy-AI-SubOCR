# src/app_context.py

import os
import sys
import shutil
import json
import uuid
import logging
from datetime import datetime
import threading

from src.settings import load_settings, save_settings, TEMP_DIR_NAME
from src.video_processor import inspect_video_subtitles, extract_pgs_subtitles
from src.ocr import run_ocr_pipeline, get_available_models
from src.utils import parse_bdsup2sub_xml, parse_subtitle_edit_html
from src.localization import EN_TRANSLATIONS

def resource_path(relative_path: str) -> str:
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class AppContext:
    def __init__(self):
        self.settings = load_settings()
        self.api_key = self.settings.get("api_key", "")
        self.model_name = self.settings.get("last_model", "")
        self.batch_size = self.settings.get("batch_size", 120)
        self.max_retries = self.settings.get("max_retries", 5)
        self.ocr_prompt_template = self._load_ocr_prompt_template()
        self.ocr_language = self.settings.get("ocr_language", "Auto")
        self.generation_config = self.settings.get("generation_config", {})
        
        # Attempt to resolve the path for BDSup2Sub.jar robustly
        bdsup2sub_setting = self.settings.get("bdsup2sub_path", "assets/BDSup2Sub.jar")
        resolved_path = resource_path(bdsup2sub_setting)
        if not os.path.exists(resolved_path):
            # If not found, try to find it in the assets folder as a fallback
            path_in_assets = resource_path(os.path.join("assets", os.path.basename(bdsup2sub_setting)))
            if os.path.exists(path_in_assets):
                resolved_path = path_in_assets
        self.bdsup2sub_path = resolved_path

        self.safety_settings = self.settings.get("safety_settings", [])

        self.subtitles = []
        self.current_index = -1
        self.image_folder = ""
        self.timing_file_path = ""
        self.current_session_dir = None # Thư mục gốc của phiên làm việc hiện tại

        self._ensure_app_temp_dir()

    def _ensure_app_temp_dir(self):
        os.makedirs(TEMP_DIR_NAME, exist_ok=True)

    def _create_new_session_dir(self, base_name: str) -> str:
        """Creates a new session directory based on the source file name."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_base_name = "".join(c for c in base_name if c.isalnum() or c in (' ', '.', '_')).rstrip()
        session_name = f"{safe_base_name}_{timestamp}_{str(uuid.uuid4())[:4]}"
        session_path = os.path.join(TEMP_DIR_NAME, session_name)
        os.makedirs(session_path, exist_ok=True)
        os.makedirs(os.path.join(session_path, "images"), exist_ok=True)
        os.makedirs(os.path.join(session_path, "logs"), exist_ok=True)
        self.current_session_dir = session_path
        logging.info(EN_TRANSLATIONS["log_new_session_dir_created"].format(path=session_path))
        return session_path

    def cleanup_current_session_temp(self):
        """Cleans up the current working session directory."""
        if self.current_session_dir and os.path.exists(self.current_session_dir):
            try:
                shutil.rmtree(self.current_session_dir)
                logging.info(EN_TRANSLATIONS["log_session_cleaned_up"].format(path=self.current_session_dir))
                self.current_session_dir = None
                self.image_folder = ""
                self.timing_file_path = ""
                self.subtitles = []
                self.current_index = -1
            except Exception as e:
                logging.error(EN_TRANSLATIONS["log_session_cleanup_error"].format(error=e))

    def update_settings(self, key, value):
        """Cập nhật một cài đặt và lưu vào file."""
        self.settings[key] = value
        save_settings(self.settings)
        # Cập nhật các thuộc tính tương ứng
        if key == "api_key": self.api_key = value
        elif key == "last_model": self.model_name = value
        elif key == "batch_size": self.batch_size = value
        elif key == "max_retries": self.max_retries = value
        elif key == "ocr_language": self.ocr_language = value
        elif key == "generation_config": self.generation_config = value
        elif key == "bdsup2sub_path": self.bdsup2sub_path = value
        elif key == "safety_settings": self.safety_settings = value

    def get_available_models(self) -> tuple[list, str | None]:
        """Fetches a list of available Gemini models."""
        return get_available_models(self.api_key)

    def inspect_video_subtitles(self, video_path: str) -> tuple[list, str | None]:
        """Scans a video file for image subtitle streams."""
        return inspect_video_subtitles(video_path)

    def extract_subtitles_from_video(self, video_path: str, stream_index: int, progress_callback=None, cancellation_event=None) -> tuple[str | None, str | None, str | None]:
        """Extracts subtitles from a video, parses them, and loads them into the context."""
        logging.info(EN_TRANSLATIONS["log_extracting_subtitles_from"].format(video_file=os.path.basename(video_path), index=stream_index))
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        session_dir = self._create_new_session_dir(base_name)
        
        image_folder, timing_file, error = extract_pgs_subtitles(video_path, stream_index, session_dir, self.bdsup2sub_path, progress_callback, cancellation_event)
        
        if error:
            # Don't log user cancellation as a generic subtitle extraction error
            if error != EN_TRANSLATIONS["error_extraction_cancelled_by_user"]:
                logging.error(EN_TRANSLATIONS["log_subtitle_extraction_error"].format(error=error))
            return None, None, error

        self.image_folder = image_folder
        self.timing_file_path = timing_file
        shutil.copy(timing_file, os.path.join(session_dir, os.path.basename(timing_file)))

        # After extraction, read the timing file to load subtitles
        if timing_file.lower().endswith(".xml"):
            subtitles = parse_bdsup2sub_xml(timing_file)
        else:
            subtitles = [] 
        
        if subtitles:
            self.subtitles = subtitles
        else:
            error_msg = EN_TRANSLATIONS["log_timing_file_read_error_after_extraction"]
            logging.error(error_msg)
            return image_folder, timing_file, error_msg
            
        return image_folder, timing_file, None

    def load_timing_file(self, timing_path: str) -> tuple[list | None, str | None]:
        """Loads a timing file (XML/HTML) and sets up the session directory."""
        logging.info(EN_TRANSLATIONS["log_loading_timing_file"].format(file=os.path.basename(timing_path)))
        base_name = os.path.splitext(os.path.basename(timing_path))[0]
        session_dir = self._create_new_session_dir(base_name)
        
        session_timing_path = os.path.join(session_dir, os.path.basename(timing_path))
        shutil.copy(timing_path, session_timing_path)

        original_image_folder = os.path.dirname(timing_path)
        session_image_folder = os.path.join(session_dir, "images")

        logging.info(EN_TRANSLATIONS["log_copying_images"].format(source=original_image_folder))
        copied_count = 0
        for f in os.listdir(original_image_folder):
            if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                shutil.copy(os.path.join(original_image_folder, f), session_image_folder)
                copied_count += 1
        logging.info(EN_TRANSLATIONS["log_images_copied"].format(count=copied_count))

        self.image_folder = session_image_folder
        self.timing_file_path = session_timing_path

        if timing_path.lower().endswith(".xml"):
            subtitles = parse_bdsup2sub_xml(session_timing_path)
        elif timing_path.lower().endswith(".html"):
            subtitles = parse_subtitle_edit_html(session_timing_path)
        else:
            return None, EN_TRANSLATIONS["error_unsupported_timing_file_format"]
        
        if subtitles:
            self.subtitles = subtitles
            logging.info(EN_TRANSLATIONS["log_timing_file_loaded_success"].format(count=len(subtitles)))
            return subtitles, None
        else:
            logging.error(EN_TRANSLATIONS["log_timing_file_read_error_corrupt_empty"])
            return None, EN_TRANSLATIONS["log_timing_file_read_error_corrupt_empty"]

    def run_ocr_pipeline(self, cancellation_event: threading.Event, progress_callback=None) -> tuple[list | None, str]:
        """Runs the OCR pipeline."""
        if not all([self.api_key, self.model_name, self.timing_file_path, self.image_folder, self.current_session_dir]):
            return None, EN_TRANSLATIONS["error_ocr_config_missing"]
        
        log_folder = os.path.join(self.current_session_dir, "logs")
        os.makedirs(log_folder, exist_ok=True) # Ensure log directory exists

        # Construct OCR prompt dynamically
        current_ocr_prompt = self.ocr_prompt_template
        if self.ocr_language and self.ocr_language.lower() != 'auto':
            current_ocr_prompt += f"\nImportant: The language of the subtitles is {self.ocr_language}. Extract text in this language only."

        subtitles, message = run_ocr_pipeline(
            self.timing_file_path,
            self.image_folder,
            log_folder,
            self.api_key,
            self.model_name,
            self.generation_config,
            self.safety_settings,
            self.batch_size,
            self.max_retries,
            current_ocr_prompt,
            cancellation_event, # Pass the cancellation event
            progress_callback
        )
        if subtitles:
            self.subtitles = subtitles
            return subtitles, message
        return None, message

    def load_session_from_folder(self, session_folder_path: str) -> tuple[list | None, str | None]:
        """Reloads a working session from a saved folder."""
        if not os.path.isdir(session_folder_path):
            return None, EN_TRANSLATIONS["error_session_folder_not_exist"]

        self.cleanup_current_session_temp() # Clean up current session first

        self.current_session_dir = session_folder_path
        self.image_folder = os.path.join(session_folder_path, "images")
        log_folder = os.path.join(session_folder_path, "logs")
        os.makedirs(log_folder, exist_ok=True) # Ensure log directory exists

        # Find timing file in session directory
        timing_file = None
        for f in os.listdir(session_folder_path):
            if f.lower().endswith(('.xml', '.html')):
                timing_file = os.path.join(session_folder_path, f)
                break
        
        if not timing_file:
            return None, EN_TRANSLATIONS["error_no_timing_file_in_session"]
        
        self.timing_file_path = timing_file

        # Parse timing file to get original subtitle structure
        if timing_file.lower().endswith(".xml"):
            subtitles = parse_bdsup2sub_xml(timing_file)
        elif timing_file.lower().endswith(".html"):
            subtitles = parse_subtitle_edit_html(timing_file)
        else:
            return None, EN_TRANSLATIONS["error_unsupported_timing_file_format_session"]
        
        if not subtitles:
            return None, EN_TRANSLATIONS["error_timing_file_read_error_session"]
        
        self.subtitles = subtitles

        # Load OCR results from JSON log files
        log_files_found = 0
        if os.path.isdir(log_folder):
            for filename in sorted(os.listdir(log_folder)):
                if filename.startswith("batch_") and filename.endswith(".json"):
                    try:
                        batch_start_index = int(filename.replace("batch_", "").replace(".json", ""))
                        with open(os.path.join(log_folder, filename), 'r', encoding='utf-8') as f:
                            results = json.load(f) # Read raw JSON
                        log_files_found += 1
                        for res in results:
                            absolute_index = batch_start_index + res['index']
                            if 0 <= absolute_index < len(self.subtitles):
                                self.subtitles[absolute_index]['text'] = res.get('text', '')
                    except Exception as e:
                        logging.error(EN_TRANSLATIONS["log_error_parsing_saving_log"].format(filename=filename, error=e))
        
        if log_files_found > 0:
            return self.subtitles, EN_TRANSLATIONS["log_loaded_batches_from_log"].format(count=log_files_found)
        else:
            return self.subtitles, EN_TRANSLATIONS["log_no_log_files_found"]

    def get_session_list(self) -> list[str]:
        """Gets a list of saved working session directories."""
        if not os.path.isdir(TEMP_DIR_NAME):
            return []
        sessions = [d for d in os.listdir(TEMP_DIR_NAME) if os.path.isdir(os.path.join(TEMP_DIR_NAME, d))]
        return sorted(sessions, reverse=True) # Sort in reverse to show newest sessions first

    def _load_ocr_prompt_template(self) -> str:
        """Loads the OCR prompt content from prompt.txt."""
        prompt_path = resource_path("assets/prompt.txt")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            logging.warning(EN_TRANSLATIONS["warning_prompt_file_not_found"].format(path=prompt_path))
            return EN_TRANSLATIONS["default_ocr_prompt"]
        except Exception as e:
            logging.error(EN_TRANSLATIONS["error_reading_prompt_file"].format(path=prompt_path, error=e))
            return EN_TRANSLATIONS["default_ocr_prompt"]
