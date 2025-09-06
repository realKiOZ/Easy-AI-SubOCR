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

def validate_gemini_response(response_data, expected_count):
    if not isinstance(response_data, list):
        return f"Validation failed: Response is not a list, but {type(response_data).__name__}."
    
    if len(response_data) != expected_count:
        return f"Validation failed: Expected {expected_count} items, but got {len(response_data)}."

    for i, item in enumerate(response_data):
        if not isinstance(item, dict):
            return f"Validation failed: Item at index {i} is not a dictionary."
        if 'index' not in item or 'text' not in item:
            return f"Validation failed: Item at index {i} is missing 'index' or 'text' key."
        if not isinstance(item['index'], int):
            return f"Validation failed: 'index' at item {i} is not an integer."
        if not isinstance(item['text'], str):
            return f"Validation failed: 'text' at item {i} is not a string."
    
    # Validate indices are unique and sequential
    received_indices = sorted([item['index'] for item in response_data])
    expected_indices = list(range(expected_count))

    if received_indices != expected_indices:
        return f"Validation failed: Received indices {received_indices} do not match expected sequential indices {expected_indices}."
            
    return None

def process_batch_with_gemini(batch_of_events, image_folder, log_folder, model, batch_start_index, generation_config, safety_settings, ocr_prompt):
    api_request_parts = [ocr_prompt]
    for event in batch_of_events:
        image_path = os.path.join(image_folder, event['image_file'])
        try:
            # Determine MIME type based on file extension
            ext = os.path.splitext(image_path)[1].lower()
            if ext in ['.jpg', '.jpeg']:
                mime_type = 'image/jpeg'
            elif ext == '.png':
                mime_type = 'image/png'
            elif ext == '.webp':
                mime_type = 'image/webp'
            else:
                logging.warning(f"Unsupported image format '{ext}' for file '{event['image_file']}'. Skipping.")
                continue

            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                api_request_parts.append({"mime_type": mime_type, "data": encoded_string})
        except FileNotFoundError:
            logging.warning(f"Image file not found: '{event['image_file']}'. Skipping.")
            continue
    
    if len(api_request_parts) <= 1: 
        return None, "No images to process in batch.", "SKIPPED"

    try:
        # NOTE: The 'thinking_config' feature was removed due to incompatibility with the installed SDK version.
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
            if json_match: 
                json_content = json_match.group(1)
            
            parsed_json = json.loads(json_content)
            
            # --- Start Validation ---
            expected_image_count = len(api_request_parts) - 1
            validation_error = validate_gemini_response(parsed_json, expected_image_count)
            if validation_error:
                logging.error(f"Batch {batch_start_index} validation failed: {validation_error}")
                # Save raw response for debugging
                with open(log_filepath.replace('.json', '.txt'), 'w', encoding='utf-8') as f:
                    f.write(response.text)
                return None, validation_error, "VALIDATION_ERROR"
            # --- End Validation ---

            with open(log_filepath, 'w', encoding='utf-8') as f:
                json.dump(parsed_json, f, indent=4, ensure_ascii=False)
            
            return parsed_json, None, None

        except json.JSONDecodeError as json_e:
            logging.error(f"Error parsing JSON for batch {batch_start_index}: {json_e}. Raw response saved to .txt.")
            with open(log_filepath.replace('.json', '.txt'), 'w', encoding='utf-8') as f:
                f.write(response.text)
            return None, f"JSON Decode Error: {json_e}", "JSON_ERROR"
            
    except Exception as e:
        error_str = str(e)
        logging.warning(f"Full API Error: {error_str}") # Log the full error for debugging
        error_type = "GENERAL_API_ERROR"
        if "resource exhausted" in error_str.lower() or "userRateLimitExceeded" in error_str or "429" in error_str:
            error_type = "RATE_LIMIT"
        return None, error_str, error_type

def run_ocr_pipeline(subtitles: list, image_folder: str, log_folder: str, api_keys: list, model_name: str, generation_config: dict, safety_settings: list, batch_size: int, ocr_prompt: str, cancellation_event: threading.Event, frame_rate: float, progress_callback=None, indices_to_process=None) -> tuple[list | None, str]:
    logging.info("Starting OCR process...")
    
    if not api_keys:
        return None, "No API keys provided."
    
    model = genai.GenerativeModel(model_name)

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

        results, error_message, error_type = None, "", None
        key_index = 0
        batch_successful = False
        
        while not batch_successful:
            if cancellation_event.is_set():
                logging.warning(f"OCR cancelled by user during batch {i}.")
                all_failed_indices.add(i)
                break 

            current_key = api_keys[key_index]
            logging.info(f"Processing batch {i} with API Key #{key_index + 1}...")
            
            try:
                genai.configure(api_key=current_key)
            except Exception as e:
                logging.error(f"Failed to configure API Key #{key_index + 1}: {e}")
                key_index = (key_index + 1) % len(api_keys)
                time.sleep(1)
                continue

            for attempt in range(3): # Retry 3 times per key
                if cancellation_event.is_set():
                    break

                results, error_message, error_type = process_batch_with_gemini(batch_to_process, image_folder, log_folder, model, i, generation_config, safety_settings, ocr_prompt)
                
                if results is not None:
                    all_failed_indices.discard(i)
                    batch_successful = True
                    break
                else:
                    logging.warning(f"Batch {i} failed on Key #{key_index + 1} (attempt {attempt+1}/3). Retrying...")
                    logging.debug(f"Full error for batch {i}: {error_message}")
                    
                    wait_time = 9 if error_type == "RATE_LIMIT" else 5
                    if error_type == "RATE_LIMIT":
                        logging.info(f"Rate limit detected. Waiting for {wait_time} seconds...")
                    else:
                        logging.info(f"An error occurred. Waiting for {wait_time} seconds before retrying...")
                    
                    time.sleep(wait_time)
            
            if cancellation_event.is_set():
                logging.warning(f"OCR cancelled by user during batch {i}.")
                all_failed_indices.add(i)
                break

            if not batch_successful:
                logging.warning(f"Batch {i} failed on all 3 attempts with Key #{key_index + 1}. Switching to next key.")
                key_index = (key_index + 1) % len(api_keys)
            
        if results is not None:
            # This block runs if the batch was successful
            for res in results:
                try:
                    relative_index = res['index']
                    text = res.get('text', '')
                    # Find the original subtitle this result corresponds to
                    original_relative_index = original_indices_in_batch[relative_index]
                    absolute_index = i + original_relative_index
                    if 0 <= absolute_index < len(subtitles):
                        subtitles[absolute_index]['text'] = text
                except (TypeError, KeyError, IndexError) as e:
                    logging.error(f"Error processing result item in batch {i}: {e}. Result: {res}")

        processed_count += len(batch_to_process)
        if progress_callback:
            progress_percentage = (processed_count / total_subs_to_process) * 100 if total_subs_to_process > 0 else 0
            progress_callback(f"OCR: {processed_count}/{total_subs_to_process}", progress_percentage)

    settings = load_settings()
    settings['last_failed_batches'] = sorted(list(all_failed_indices))
    save_settings(settings)
    
    if not all_failed_indices:
        initial_count = len(subtitles)
        # Filter out subtitles that are empty OR still have the failure message
        filtered_subtitles = [
            sub for sub in subtitles 
            if sub.get('text', '').strip() and not sub.get('text', '').startswith("[OCR FAILED")
        ]
        removed_count = initial_count - len(filtered_subtitles)
        if removed_count > 0:
            logging.info(f"Removed {removed_count} empty or failed subtitle entries.")

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
