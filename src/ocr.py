import os
import base64
import json
import google.generativeai as genai
import time
import re
import logging
import threading
from itertools import compress

from src.settings import save_settings, load_settings
from src.utils import merge_subtitles

def get_available_models(api_key: str) -> tuple[list, str | None]:
    try:
        logging.info("Fetching available Gemini models...")
        genai.configure(api_key=api_key)
        models = [m.name.replace("models/", "") for m in genai.list_models() if 'generateContent' in m.supported_generation_methods and "models/gemini" in m.name]
        if not models:
            logging.warning("No compatible Gemini models found.")
            return [], "No Gemini models found. Please check API key and permissions."
        logging.info(f"Found {len(models)} compatible models.")
        return sorted(models), None
    except Exception as e:
        logging.error(f"Error fetching model list: {e}")
        return [], f"Invalid API Key or connection error: {e}"

def process_batch_with_gemini(batch_of_events, image_folder, log_folder, model, batch_start_index, generation_config, safety_settings, ocr_prompt):
    api_request_parts = [ocr_prompt]
    for event in batch_of_events:
        image_path = os.path.join(image_folder, event['image_file'])
        try:
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                api_request_parts.append({"mime_type": "image/png", "data": encoded_string})
        except FileNotFoundError:
            logging.warning(f"Image file not found: '{event['image_file']}'. Skipping.")
            continue
    if len(api_request_parts) <= 1: return None, "No images to process in batch."

    try:
        response = model.generate_content(
            api_request_parts,
            generation_config=generation_config,
            safety_settings=safety_settings
        )
        
        log_filename = f"batch_{batch_start_index:04d}.json"
        log_filepath = os.path.join(log_folder, log_filename)
        json_content = response.text
        try:
            json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response.text)
            if json_match: json_content = json_match.group(1)
            parsed_json = json.loads(json_content)
            with open(log_filepath, 'w', encoding='utf-8') as f:
                json.dump(parsed_json, f, indent=4, ensure_ascii=False)
        except Exception as log_e:
            logging.error(f"Error parsing or saving log '{log_filename}': {log_e}. Raw response saved to .txt.")
            with open(log_filepath.replace('.json', '.txt'), 'w', encoding='utf-8') as f:
                f.write(response.text)

        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response.text)
        if json_match:
            return json.loads(json_match.group(1)), None
        else:
            return json.loads(response.text), None
    except Exception as e:
        return None, str(e)

def run_ocr_pipeline(subtitles: list, image_folder: str, log_folder: str, api_key: str, model_name: str, generation_config: dict, safety_settings: list, batch_size: int, max_retries: int, ocr_prompt: str, cancellation_event: threading.Event, frame_rate: float, progress_callback=None, indices_to_process=None) -> tuple[list | None, str]:
    logging.info("Starting OCR process...")
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
    except Exception as e:
        return None, f"API or model configuration error: {e}"

    if not subtitles: return None, "No subtitles to process."

    process_mask = [True] * len(subtitles) if indices_to_process is None else [i in indices_to_process for i in range(len(subtitles))]
    all_failed_indices = set(load_settings().get('last_failed_batches', []))
    total_subs_to_process = sum(process_mask)
    processed_count = 0

    for i in range(0, len(subtitles), batch_size):
        if cancellation_event.is_set(): return None, "Operation cancelled by user."
        
        batch_mask = process_mask[i:i + batch_size]
        if not any(batch_mask): continue

        batch_to_process = list(compress(subtitles[i:i + batch_size], batch_mask))
        original_indices_in_batch = [idx for idx, process in enumerate(batch_mask) if process]

        results, error_message = None, ""
        for attempt in range(max_retries):
            if cancellation_event.is_set(): return None, "Operation cancelled by user."
            results, error_message = process_batch_with_gemini(batch_to_process, image_folder, log_folder, model, i, generation_config, safety_settings, ocr_prompt)
            if results is not None:
                all_failed_indices.discard(i)
                break
            else:
                # Log a concise warning for the user, full details to debug
                logging.warning(f"Batch {i} failed (attempt {attempt+1}/{max_retries}). Retrying...")
                logging.debug(f"Full error for batch {i}: {error_message}")
                time.sleep(2 ** attempt)
        
        if results is not None:
            if isinstance(results, list):
                for res in results:
                    try:
                        relative_index = res['index']
                        text = res.get('text', '')
                        original_relative_index = original_indices_in_batch[relative_index]
                        absolute_index = i + original_relative_index
                        if 0 <= absolute_index < len(subtitles):
                            subtitles[absolute_index]['text'] = text
                    except (TypeError, KeyError, IndexError) as e:
                        logging.error(f"Error processing result item in batch {i}: {e}. Result: {res}")
            else:
                 all_failed_indices.add(i)
        else:
            all_failed_indices.add(i)

        processed_count += len(batch_to_process)
        if progress_callback:
            progress_percentage = (processed_count / total_subs_to_process) * 100 if total_subs_to_process > 0 else 0
            progress_callback(f"OCR: {processed_count}/{total_subs_to_process}", progress_percentage)

    settings = load_settings()
    settings['last_failed_batches'] = sorted(list(all_failed_indices))
    save_settings(settings)
    
    if not all_failed_indices:
        initial_count = len(subtitles)
        filtered_subtitles = [sub for sub in subtitles if sub.get('text', '').strip()]
        removed_count = initial_count - len(filtered_subtitles)
        if removed_count > 0:
            logging.info(f"Removed {removed_count} empty subtitle entries.")

        if frame_rate > 0:
            logging.info("Merging identical adjacent subtitles...")
            merged_count_before = len(filtered_subtitles)
            filtered_subtitles = merge_subtitles(filtered_subtitles, frame_rate)
            merged_count_after = len(filtered_subtitles)
            if merged_count_before > merged_count_after:
                logging.info(f"Merged {merged_count_before - merged_count_after} subtitle entries.")
        else:
            logging.warning("Frame rate is 0, skipping subtitle merge.")
        
        return filtered_subtitles, "OCR process completed."
    else:
        logging.warning(f"OCR process completed with {len(all_failed_indices)} failed batches. Please check the logs for details. Empty lines were not removed.")
        return subtitles, "OCR process completed with some failed batches."
