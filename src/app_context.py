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
from src.hardsub_processor import run_hardsub_pipeline

def resource_path(relative_path: str) -> str:
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
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
        
        bdsup2sub_setting = self.settings.get("bdsup2sub_path", "assets/BDSup2Sub.jar")
        resolved_path = resource_path(bdsup2sub_setting)
        if not os.path.exists(resolved_path):
            path_in_assets = resource_path(os.path.join("assets", os.path.basename(bdsup2sub_setting)))
            if os.path.exists(path_in_assets):
                resolved_path = path_in_assets
        self.bdsup2sub_path = resolved_path

        self.safety_settings = self.settings.get("safety_settings", [])

        self.subtitles = []
        self.current_index = -1
        self.image_folder = ""
        self.timing_file_path = ""
        self.current_session_dir = None

        self._ensure_app_temp_dir()

    def _ensure_app_temp_dir(self):
        os.makedirs(TEMP_DIR_NAME, exist_ok=True)

    def _create_new_session_dir(self, base_name: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_base_name = "".join(c for c in base_name if c.isalnum() or c in (' ', '.', '_')).rstrip()
        session_name = f"{safe_base_name}_{timestamp}_{str(uuid.uuid4())[:4]}"
        session_path = os.path.join(TEMP_DIR_NAME, session_name)
        os.makedirs(session_path, exist_ok=True)
        os.makedirs(os.path.join(session_path, "images"), exist_ok=True)
        os.makedirs(os.path.join(session_path, "logs"), exist_ok=True)
        self.current_session_dir = session_path
        logging.info(f"New session directory created: {session_path}")
        return session_path

    def cleanup_current_session_temp(self):
        if self.current_session_dir and os.path.exists(self.current_session_dir):
            try:
                # shutil.rmtree(self.current_session_dir)
                logging.info(f"Session directory cleaned up: {self.current_session_dir}")
            except Exception as e:
                logging.error(f"Error cleaning up session directory: {e}")
        # Reset all state variables
        self.current_session_dir = None
        self.image_folder = ""
        self.timing_file_path = ""
        self.subtitles = []
        self.current_index = -1

    def update_settings(self, key, value):
        self.settings[key] = value
        save_settings(self.settings)
        if key == "api_key": self.api_key = value
        elif key == "last_model": self.model_name = value
        elif key == "batch_size": self.batch_size = value
        elif key == "max_retries": self.max_retries = value
        elif key == "ocr_language": self.ocr_language = value
        elif key == "generation_config": self.generation_config = value
        elif key == "bdsup2sub_path": self.bdsup2sub_path = value
        elif key == "safety_settings": self.safety_settings = value

    def get_available_models(self) -> tuple[list, str | None]:
        return get_available_models(self.api_key)

    def inspect_video_subtitles(self, video_path: str) -> tuple[list, str | None]:
        return inspect_video_subtitles(video_path)

    def extract_subtitles_from_video(self, video_path: str, stream_index: int, progress_callback=None, cancellation_event=None) -> tuple[str | None, str | None, str | None]:
        logging.info(f"Extracting subtitles from {os.path.basename(video_path)} (stream {stream_index})...")
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        session_dir = self._create_new_session_dir(base_name)
        
        image_folder, timing_file, error = extract_pgs_subtitles(video_path, stream_index, session_dir, self.bdsup2sub_path, progress_callback, cancellation_event)
        
        if error:
            if error != "Extraction cancelled by user.":
                logging.error(f"Subtitle extraction error: {error}")
            return None, None, error

        self.image_folder = image_folder
        self.timing_file_path = timing_file
        shutil.copy(timing_file, os.path.join(session_dir, os.path.basename(timing_file)))

        if timing_file.lower().endswith(".xml"):
            subtitles = parse_bdsup2sub_xml(timing_file)
        else:
            subtitles = [] 
        
        if subtitles:
            self.subtitles = subtitles
        else:
            error_msg = "Error reading timing file after extraction."
            logging.error(error_msg)
            return image_folder, timing_file, error_msg
            
        return image_folder, timing_file, None

    def load_timing_file(self, timing_path: str) -> tuple[list | None, str | None]:
        logging.info(f"Loading timing file: {os.path.basename(timing_path)}")
        base_name = os.path.splitext(os.path.basename(timing_path))[0]
        session_dir = self._create_new_session_dir(base_name)
        
        session_timing_path = os.path.join(session_dir, os.path.basename(timing_path))
        shutil.copy(timing_path, session_timing_path)

        original_image_folder = os.path.dirname(timing_path)
        session_image_folder = os.path.join(session_dir, "images")

        logging.info(f"Copying images from {original_image_folder} to session directory...")
        copied_count = 0
        try:
            for f in os.listdir(original_image_folder):
                if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                    shutil.copy(os.path.join(original_image_folder, f), session_image_folder)
                    copied_count += 1
            logging.info(f"Copied {copied_count} images.")
        except FileNotFoundError:
             pass

        self.image_folder = session_image_folder
        self.timing_file_path = session_timing_path

        if timing_path.lower().endswith(".xml"):
            subtitles = parse_bdsup2sub_xml(session_timing_path)
        elif timing_path.lower().endswith(".html"):
            subtitles = parse_subtitle_edit_html(session_timing_path)
        else:
            return None, "Unsupported file format."
        
        if subtitles:
            self.subtitles = subtitles
            logging.info(f"Successfully loaded {len(subtitles)} subtitles from timing file.")
            return subtitles, None
        else:
            logging.error("Error reading timing file. File might be corrupt or empty.")
            return None, "Error reading timing file. File might be corrupt or empty."

    def run_ocr_pipeline(self, cancellation_event: threading.Event, progress_callback=None, indices_to_process=None) -> tuple[list | None, str]:
        if not all([self.api_key, self.model_name, self.image_folder, self.current_session_dir]):
            return None, "Missing configuration information to run OCR."
        
        log_folder = os.path.join(self.current_session_dir, "logs")
        os.makedirs(log_folder, exist_ok=True)

        # Kiểm tra xem đây có phải là phiên hardsub không và chọn prompt phù hợp
        is_hardsub_session = self.subtitles and 'channel' in self.subtitles[0]
        if is_hardsub_session:
            try:
                with open(resource_path("assets/prompt_hardsub.txt"), "r", encoding="utf-8") as f:
                    current_ocr_prompt = f.read()
                logging.info("Using dedicated hardsub OCR prompt.")
            except Exception as e:
                logging.error(f"Could not load hardsub prompt: {e}. Falling back to default.")
                current_ocr_prompt = self.ocr_prompt_template
        else:
            current_ocr_prompt = self.ocr_prompt_template

        if self.ocr_language and self.ocr_language.lower() != 'auto':
            current_ocr_prompt += f"\nImportant: The language of the subtitles is {self.ocr_language}. Extract text in this language only."

        subtitles, message = run_ocr_pipeline(
            self.subtitles,
            self.image_folder,
            log_folder,
            self.api_key,
            self.model_name,
            self.generation_config,
            self.safety_settings,
            self.batch_size,
            self.max_retries,
            current_ocr_prompt,
            cancellation_event,
            progress_callback,
            indices_to_process
        )
        if subtitles:
            # Xử lý hậu kỳ cho hardsub
            if is_hardsub_session:
                logging.info("Post-processing hardsub results...")
                for sub in subtitles:
                    if sub.get('channel') == 'top' and sub.get('text'):
                        sub['text'] = f"{{\\an8}}{sub.get('text', '')}"
                
                # Sắp xếp lại phụ đề theo thời gian bắt đầu
                subtitles.sort(key=lambda x: x['start_srt'])
                logging.info("Hardsub results sorted by start time.")

            self.subtitles = subtitles
            return subtitles, message
        return None, message

    def process_hardsub_video(self, video_path: str, options: dict, progress_callback=None, cancellation_event=None) -> tuple[list | None, str | None]:
        logging.info(f"Starting hardsub analysis for: {os.path.basename(video_path)}")
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        session_dir = self._create_new_session_dir(f"HARDSUB_{base_name}")

        self.image_folder = os.path.join(session_dir, "images")
        os.makedirs(self.image_folder, exist_ok=True)
        
        subtitles, error = run_hardsub_pipeline(
            video_path, self.image_folder, options, progress_callback, cancellation_event
        )

        if error:
            logging.error(f"Hardsub pipeline failed: {error}")
            return None, error

        if subtitles:
            self.subtitles = subtitles
            self.timing_file_path = os.path.join(session_dir, "hardsub_log.json")
            with open(self.timing_file_path, 'w', encoding='utf-8') as f:
                json.dump(subtitles, f, indent=2)

        return self.subtitles, None

    def load_session_from_folder(self, session_folder_path: str) -> tuple[list | None, str | None]:
        if not os.path.isdir(session_folder_path):
            return None, "Session folder does not exist."

        self.cleanup_current_session_temp()

        self.current_session_dir = session_folder_path
        self.image_folder = os.path.join(session_folder_path, "images")
        log_folder = os.path.join(session_folder_path, "logs")
        os.makedirs(log_folder, exist_ok=True)

        timing_file = None
        for f in os.listdir(session_folder_path):
            if f.lower().endswith(('.xml', '.html', '.json')): # Add json for hardsub logs
                timing_file = os.path.join(session_folder_path, f)
                break
        
        if not timing_file:
            return None, "No timing file (.xml, .html, .json) found in this session directory."
        
        self.timing_file_path = timing_file

        if timing_file.lower().endswith(".xml"):
            subtitles = parse_bdsup2sub_xml(timing_file)
        elif timing_file.lower().endswith(".html"):
            subtitles = parse_subtitle_edit_html(timing_file)
        elif timing_file.lower().endswith(".json"): # Handle hardsub log
            with open(timing_file, 'r', encoding='utf-8') as f:
                subtitles = json.load(f)
        else:
            return None, "Unsupported timing file format."
        
        if not subtitles:
            return None, "Error reading timing file in session. File might be corrupt or empty."
        
        self.subtitles = subtitles
        
        self.settings['last_failed_batches'] = []
        save_settings(self.settings)

        log_files_found = 0
        if os.path.isdir(log_folder):
            for filename in sorted(os.listdir(log_folder)):
                if filename.startswith("batch_") and filename.endswith(".json"):
                    try:
                        batch_start_index = int(filename.replace("batch_", "").replace(".json", ""))
                        with open(os.path.join(log_folder, filename), 'r', encoding='utf-8') as f:
                            results = json.load(f)
                        log_files_found += 1
                        for res in results:
                            absolute_index = batch_start_index + res.get('index', -1)
                            if 0 <= absolute_index < len(self.subtitles):
                                self.subtitles[absolute_index]['text'] = res.get('text', '')
                    except Exception as e:
                        logging.error(f"Error parsing or saving log {filename}: {e}")
        
        if log_files_found > 0:
            return self.subtitles, f"Loaded {log_files_found} batches from log files. Ready to review and save."
        else:
            return self.subtitles, "No log files found. Only original structure loaded."

    def get_session_list(self) -> list[str]:
        if not os.path.isdir(TEMP_DIR_NAME):
            return []
        sessions = [d for d in os.listdir(TEMP_DIR_NAME) if os.path.isdir(os.path.join(TEMP_DIR_NAME, d))]
        return sorted(sessions, reverse=True)

    def _load_ocr_prompt_template(self) -> str:
        prompt_path = resource_path("assets/prompt.txt")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            logging.warning(f"assets/prompt.txt not found. Using default prompt.")
            return self.settings.get("ocr_prompt", "Extract text from image.")
        except Exception as e:
            logging.error(f"Error reading assets/prompt.txt: {e}. Using default prompt.")
            return self.settings.get("ocr_prompt", "Extract text from image.")
