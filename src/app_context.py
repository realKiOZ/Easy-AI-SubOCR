# src/app_context.py

import os
import sys
import shutil
import json
import uuid
import logging
from datetime import datetime
import threading
import re
import yt_dlp
import time

from src.settings import load_settings, save_settings, TEMP_DIR_NAME, APP_TEMP_PATH
from src.video_processor import inspect_video_subtitles, extract_pgs_subtitles
from src.ocr import run_ocr_pipeline, get_available_models
from src.utils import parse_bdsup2sub_xml, parse_subtitle_edit_html
from src.hardsub_processor import run_hardsub_pipeline, run_vsf_only_pipeline, vsf_time_to_seconds, seconds_to_srt_time


def resource_path(relative_path: str) -> str:
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
        self.batch_size = self.settings.get("batch_size", 100)
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
        self.hardsub_video_path = None
        self.source_file_path = None
        self.source_file_is_from_ytdlp = False
        self.video_frame_rate = 0.0
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
        logging.info(f"New session started: {session_name}")
        return session_path

    def cleanup_current_session_temp(self):
        if self.current_session_dir and os.path.exists(self.current_session_dir):
            logging.info(f"Cleaning up session: {os.path.basename(self.current_session_dir)}")
        self.current_session_dir = None
        self.image_folder = ""
        self.timing_file_path = ""
        self.subtitles = []
        self.current_index = -1
        self.hardsub_video_path = None
        self.source_file_path = None
        self.source_file_is_from_ytdlp = False

    def cleanup_vsf_events(self):
        logging.info("Cleaning up temporary VSF folders...")
        cleaned_count = 0
        for item_name in os.listdir(APP_TEMP_PATH):
            if item_name.startswith(('vsf_event_', 'vsf_run_')) and os.path.isdir(os.path.join(APP_TEMP_PATH, item_name)):
                try:
                    shutil.rmtree(os.path.join(APP_TEMP_PATH, item_name))
                    cleaned_count += 1
                except Exception as e:
                    logging.error(f"Failed to clean up VSF folder '{item_name}': {e}")
        if cleaned_count > 0:
            logging.info(f"Cleaned up {cleaned_count} VSF temporary directories.")

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
        start_time = time.time()
        logging.info(f"Extracting subtitles from '{os.path.basename(video_path)}' (stream {stream_index})...")
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        session_dir = self._create_new_session_dir(base_name)
        
        # Get frame rate
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            self.video_frame_rate = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            logging.info(f"Video frame rate: {self.video_frame_rate:.3f} fps")
        except Exception as e:
            logging.error(f"Could not get frame rate from video: {e}")
            self.video_frame_rate = 23.976 # Fallback

        image_folder, timing_file, error = extract_pgs_subtitles(video_path, stream_index, session_dir, self.bdsup2sub_path, progress_callback, cancellation_event)
        if error:
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
            logging.info(f"Subtitle extraction complete. Found {len(subtitles)} subtitles in {time.time() - start_time:.2f} seconds.")
        else:
            return image_folder, timing_file, "Error reading timing file after extraction."
        return image_folder, timing_file, None

    def load_timing_file(self, timing_path: str) -> tuple[list | None, str | None]:
        start_time = time.time()
        logging.info(f"Loading timing file: '{os.path.basename(timing_path)}'...")
        base_name = os.path.splitext(os.path.basename(timing_path))[0]
        session_dir = self._create_new_session_dir(base_name)
        session_timing_path = os.path.join(session_dir, os.path.basename(timing_path))
        shutil.copy(timing_path, session_timing_path)
        original_image_folder = os.path.dirname(timing_path)
        session_image_folder = os.path.join(session_dir, "images")
        try:
            shutil.copytree(original_image_folder, session_image_folder, dirs_exist_ok=True)
            logging.info(f"Copied images from '{original_image_folder}'.")
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
            logging.info(f"Successfully loaded {len(subtitles)} subtitles from timing file in {time.time() - start_time:.2f} seconds.")
            return subtitles, None
        else:
            return None, "Error reading timing file. File might be corrupt or empty."
        
    def run_ocr_pipeline(self, cancellation_event: threading.Event, progress_callback=None, indices_to_process=None) -> tuple[list | None, str]:
        start_time = time.time()
        if not all([self.api_key, self.model_name, self.image_folder, self.current_session_dir]):
            return None, "Missing configuration information to run OCR."
        log_folder = os.path.join(self.current_session_dir, "logs")
        os.makedirs(log_folder, exist_ok=True)
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

        # Replace language placeholder in the selected prompt
        if self.ocr_language and self.ocr_language.lower() != 'auto':
            language = self.ocr_language
        else:
            language = "the dominant language in the image" # Fallback for Auto
        current_ocr_prompt = current_ocr_prompt.replace("{language}", language)
        
        subtitles, message = run_ocr_pipeline(self.subtitles, self.image_folder, log_folder, self.api_key, self.model_name, self.generation_config, self.safety_settings, self.batch_size, self.max_retries, current_ocr_prompt, cancellation_event, self.video_frame_rate, progress_callback, indices_to_process)
        
        if subtitles:
            if is_hardsub_session:
                logging.info("Post-processing hardsub results...")
                for sub in subtitles:
                    if sub.get('channel') == 'top' and sub.get('text'):
                        sub['text'] = f"{{\\an8}}{sub.get('text', '')}"
                subtitles.sort(key=lambda x: x['start_srt'])
                logging.info("Hardsub results sorted by start time.")

            self.subtitles = subtitles
            logging.info(f"OCR process completed in {time.time() - start_time:.2f} seconds.")
            return subtitles, message
            
        return None, message
        
    def process_hardsub_video_east(self, video_path: str, options: dict, progress_callback=None, cancellation_event=None) -> tuple[list | None, str | None, str | None]:
        start_time = time.time()
        logging.info(f"Starting EAST+VSF hardsub analysis for: '{os.path.basename(video_path)}'")
        
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            self.video_frame_rate = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            logging.info(f"Video frame rate: {self.video_frame_rate:.3f} fps")
        except Exception as e:
            logging.error(f"Could not get frame rate from video: {e}")
            self.video_frame_rate = 23.976 # Fallback

        if self.current_session_dir and self.source_file_is_from_ytdlp:
            session_dir = self.current_session_dir
            logging.info(f"Reusing existing session directory: '{os.path.basename(session_dir)}'")
        else:
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            session_dir = self._create_new_session_dir(f"HARDSUB_{base_name}")
        
        self.image_folder = os.path.join(session_dir, "images")
        
        run_id = uuid.uuid4().hex
        subtitles, error, flag_file = run_hardsub_pipeline(video_path, self.image_folder, options, run_id, progress_callback, cancellation_event)

        if error:
            logging.error(f"EAST+VSF pipeline failed: {error}")
            return None, error, None

        self.subtitles = subtitles
        if subtitles:
            self.timing_file_path = os.path.join(session_dir, "hardsub_log_tmp.json")
            with open(self.timing_file_path, 'w', encoding='utf-8') as f:
                json.dump(subtitles, f, indent=2)
        
        logging.info(f"EAST+VSF analysis complete in {time.time() - start_time:.2f} seconds.")
        return self.subtitles, None, flag_file, run_id

    def process_hardsub_video_vsf_only(self, video_path: str, options: dict, progress_callback=None, cancellation_event=None) -> tuple[list | None, str | None, str | None]:
        start_time = time.time()
        logging.info(f"Starting VSF-Only hardsub analysis for: '{os.path.basename(video_path)}'")
        
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            self.video_frame_rate = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            logging.info(f"Video frame rate: {self.video_frame_rate:.3f} fps")
        except Exception as e:
            logging.error(f"Could not get frame rate from video: {e}")
            self.video_frame_rate = 23.976 # Fallback

        if self.current_session_dir and self.source_file_is_from_ytdlp:
            session_dir = self.current_session_dir
            logging.info(f"Reusing existing session directory: '{os.path.basename(session_dir)}'")
        else:
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            session_dir = self._create_new_session_dir(f"HARDSUB_{base_name}")
        
        self.image_folder = os.path.join(session_dir, "images")
        
        run_id = uuid.uuid4().hex
        subtitles, error, flag_file = run_vsf_only_pipeline(video_path, self.image_folder, options, run_id, progress_callback, cancellation_event)

        if error:
            logging.error(f"VSF-Only pipeline failed: {error}")
            return None, error, None
        
        self.subtitles = []
        
        logging.info(f"VSF-Only analysis started in {time.time() - start_time:.2f} seconds.")
        return self.subtitles, None, flag_file, run_id

    def merge_vsf_results(self, run_id: str) -> list | None:
        start_time = time.time()
        if not self.current_session_dir:
            return None
        
        refined_subtitles = []
        
        vsf_output_dirs = [d for d in os.listdir(APP_TEMP_PATH) if d.startswith((f'vsf_event_{run_id}', f'vsf_run_{run_id}'))]
        
        if not vsf_output_dirs:
            logging.warning("No VSF output directories found for merging.")
            return self.subtitles
            
        logging.info(f"Processing refined results from {len(vsf_output_dirs)} VSF output folder(s)...")
        image_counter = 1
        empty_vsf_dirs_count = 0

        for dir_name in vsf_output_dirs:
            dir_path = os.path.join(APP_TEMP_PATH, dir_name)
            rgb_images_path = os.path.join(dir_path, 'RGBImages')
            
            channel = 'top' if ('_top_' in dir_name or 'vsf_event_top_' in dir_name) else 'bottom'

            if os.path.isdir(rgb_images_path) and os.listdir(rgb_images_path):
                logging.debug(f"Found {len(os.listdir(rgb_images_path))} images in '{dir_name}'.")
                for img_filename in sorted(os.listdir(rgb_images_path)):
                    if img_filename.lower().endswith(('.png', '.jpeg', '.jpg')):
                        try:
                            base_name, original_ext = os.path.splitext(img_filename)
                            time_parts = base_name.split('__')
                            start_time_str = time_parts[0]
                            end_time_match = re.match(r'(\d+_\d+_\d+_\d+)', time_parts[1])
                            if not end_time_match: continue
                            end_time_str = end_time_match.group(1)
                            
                            start_sec = vsf_time_to_seconds(start_time_str)
                            end_sec = vsf_time_to_seconds(end_time_str)
                            
                            new_image_filename = f"hardsub_refined_{image_counter:05d}{original_ext}"
                            shutil.copy(os.path.join(rgb_images_path, img_filename), os.path.join(self.image_folder, new_image_filename))
                            
                            refined_subtitles.append({
                                "start_srt": seconds_to_srt_time(start_sec), 
                                "end_srt": seconds_to_srt_time(end_sec), 
                                "image_file": new_image_filename, 
                                "channel": channel
                            })
                            image_counter += 1
                        except Exception as e:
                            logging.error(f"Failed to process VSF image file '{img_filename}': {e}")
            else:
                empty_vsf_dirs_count += 1
            
            try:
                shutil.rmtree(dir_path)
            except Exception as e:
                logging.error(f"Failed to clean up VSF output folder '{dir_name}': {e}")

        if empty_vsf_dirs_count > 0:
            logging.warning(f"{empty_vsf_dirs_count} VSF output directories did not contain any subtitle images.")

        if refined_subtitles:
            refined_subtitles.sort(key=lambda x: x['start_srt'])
            self.subtitles = refined_subtitles
            
            self.timing_file_path = os.path.join(self.current_session_dir, "hardsub_log_refined.json")
            with open(self.timing_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.subtitles, f, indent=2)
            logging.info(f"Merged {len(self.subtitles)} subtitles in {time.time() - start_time:.2f} seconds.")
            return self.subtitles
            
        logging.warning("VSF processing finished, but no new valid subtitle images were generated.")
        return self.subtitles
            
    def load_session_from_folder(self, session_folder_path: str) -> tuple[list | None, str | None]:
        start_time = time.time()
        if not os.path.isdir(session_folder_path):
            return None, "Session folder does not exist."
        self.cleanup_current_session_temp()
        self.current_session_dir = session_folder_path
        self.image_folder = os.path.join(session_folder_path, "images")
        log_folder = os.path.join(session_folder_path, "logs")
        os.makedirs(self.image_folder, exist_ok=True)
        os.makedirs(log_folder, exist_ok=True)
        timing_file = None
        for f in sorted(os.listdir(session_folder_path), reverse=True):
            if f.lower().endswith(('.xml', '.html', '.json')):
                timing_file = os.path.join(session_folder_path, f)
                if 'refined' in f: break
        if not timing_file:
            return None, "No timing file found in this session."
        self.timing_file_path = timing_file
        if timing_file.lower().endswith(".json"):
            with open(timing_file, 'r', encoding='utf-8') as f: subtitles = json.load(f)
        elif timing_file.lower().endswith(".xml"): subtitles = parse_bdsup2sub_xml(timing_file)
        elif timing_file.lower().endswith(".html"): subtitles = parse_subtitle_edit_html(timing_file)
        else: return None, "Unsupported timing file format."
        if not subtitles: return None, "Error reading timing file."
        self.subtitles = subtitles
        self.settings['last_failed_batches'] = []
        save_settings(self.settings)
        log_files_found = 0
        if os.path.isdir(log_folder):
            for filename in sorted(os.listdir(log_folder)):
                if filename.startswith("batch_") and filename.endswith(".json"):
                    try:
                        batch_start_index = int(filename.replace("batch_", "").replace(".json", ""))
                        with open(os.path.join(log_folder, filename), 'r', encoding='utf-8') as f: results = json.load(f)
                        log_files_found += 1
                        for res in results:
                            absolute_index = batch_start_index + res.get('index', -1)
                            if 0 <= absolute_index < len(self.subtitles):
                                self.subtitles[absolute_index]['text'] = res.get('text', '')
                    except Exception as e:
                        logging.error(f"Error parsing log {filename}: {e}")
        if log_files_found > 0:
            logging.info(f"Session loaded with {log_files_found} OCR batches in {time.time() - start_time:.2f} seconds.")
            return self.subtitles, f"Loaded {log_files_found} batches from logs."
        else:
            logging.info(f"Session loaded in {time.time() - start_time:.2f} seconds.")
            return self.subtitles, "Session loaded."

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
            logging.warning("assets/prompt.txt not found. Using default prompt.")
            return self.settings.get("ocr_prompt", "Extract text from image.")

    def download_video_from_url(self, video_url: str, progress_callback=None) -> tuple[str | None, str | None]:
        start_time = time.time()
        logging.info(f"Starting video download from URL: '{video_url}'")

        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'nocheckcertificate': True, 'extract_flat': 'in_playlist'}) as ydl:
                info = ydl.extract_info(video_url, download=False)
                video_title = info.get('title', 'YTDLP_Download')
        except Exception as e:
            logging.error(f"Failed to extract video info: {e}")
            video_title = "YTDLP_Download"

        session_dir = self._create_new_session_dir(f"HARDSUB_{video_title}")
        self.source_file_is_from_ytdlp = True
        
        def progress_hook(d):
            if d['status'] == 'downloading':
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
                if total_bytes:
                    percentage = (d['downloaded_bytes'] / total_bytes) * 100
                    if progress_callback:
                        self.progress_callback_wrapper(progress_callback, f"Downloading... {percentage:.1f}%", percentage)
            elif d['status'] == 'finished':
                if progress_callback:
                    self.progress_callback_wrapper(progress_callback, "Download finished, processing...", 100)

        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': os.path.join(session_dir, '%(title)s.%(ext)s'),
            'progress_hooks': [progress_hook],
            'nocheckcertificate': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                downloaded_file = ydl.prepare_filename(info)
            
            logging.info(f"Video downloaded successfully to: '{downloaded_file}' in {time.time() - start_time:.2f} seconds.")
            return downloaded_file, None
        except Exception as e:
            logging.error(f"yt-dlp failed to download video: {e}")
            return None, str(e)

    def progress_callback_wrapper(self, callback, message, percentage):
        if callback:
            callback(message, percentage)
