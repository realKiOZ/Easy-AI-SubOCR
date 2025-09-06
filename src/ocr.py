import os
import base64
import json
import google.generativeai as genai
import time
import re
import logging
import threading
from itertools import compress
from queue import Queue, Empty

from src.settings import save_settings, load_settings
from src.utils import merge_subtitles

def get_available_models(api_key: str) -> tuple[list, str | None]:
    try:
        logging.info("Fetching available AI models...")
        genai.configure(api_key=api_key)
        models = [m.name.replace("models/", "") for m in genai.list_models() if 'generateContent' in m.supported_generation_methods and "models/gemini" in m.name]
        if not models:
            logging.warning("No compatible AI models found. Please check API key and permissions.")
            return [], "No Gemini models found. Please check API key and permissions."
        logging.info(f"Found {len(models)} compatible AI models.")
        return sorted(models), None
    except Exception as e:
        logging.error(f"Error fetching AI model list: {e}")
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
    
    received_indices = sorted([item['index'] for item in response_data])
    expected_indices = list(range(expected_count))

    if received_indices != expected_indices:
        return f"Validation failed: Received indices {received_indices} do not match expected sequential indices {expected_indices}."
            
    return None

def process_batch_with_gemini(batch_of_events_with_indices, image_folder, log_folder, model, batch_start_index, generation_config, safety_settings, ocr_prompt, language):
    
    batch_of_events = [event for _, event in batch_of_events_with_indices]

    valid_image_events = []
    for event in batch_of_events:
        image_path = os.path.join(image_folder, event['image_file'])
        ext = os.path.splitext(image_path)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.webp'] and os.path.exists(image_path):
            valid_image_events.append(event)
        else:
            logging.warning(f"Skipping invalid or non-existent image for OCR: {event['image_file']}")

    if not valid_image_events:
        return None, "No valid images to process in batch.", "SKIPPED"
        
    image_count = len(valid_image_events)
    
    formatted_prompt = ocr_prompt.format(image_count=image_count, language=language)
    api_request_parts = [formatted_prompt]

    for event in valid_image_events:
        image_path = os.path.join(image_folder, event['image_file'])
        try:
            ext = os.path.splitext(image_path)[1].lower()
            mime_type = f'image/{ext.replace(".", "")}'
            if ext not in ['.jpeg', '.jpg', '.png', '.webp']:
                logging.warning(f"Unsupported image format '{ext}' for file '{event['image_file']}'. Skipping OCR for this image.")
                continue

            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                api_request_parts.append({"mime_type": mime_type, "data": encoded_string})
        except FileNotFoundError:
            logging.warning(f"Image file not found: '{event['image_file']}'. Skipping OCR for this image.")
            continue
    
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
            if json_match: 
                json_content = json_match.group(1)
            
            parsed_json = json.loads(json_content)
            
            expected_image_count = len(valid_image_events)
            validation_error = validate_gemini_response(parsed_json, expected_image_count)
            if validation_error:
                logging.error(f"OCR response validation failed for batch {batch_start_index}: {validation_error}")
                with open(log_filepath.replace('.json', '.txt'), 'w', encoding='utf-8') as f:
                    f.write(response.text)
                return None, validation_error, "VALIDATION_ERROR"

            with open(log_filepath, 'w', encoding='utf-8') as f:
                json.dump(parsed_json, f, indent=4, ensure_ascii=False)
            
            return parsed_json, None, None

        except json.JSONDecodeError as json_e:
            logging.error(f"Error parsing AI response for batch {batch_start_index}: {json_e}. Raw response saved to .txt.")
            with open(log_filepath.replace('.json', '.txt'), 'w', encoding='utf-8') as f:
                f.write(response.text)
            return None, f"JSON Decode Error: {json_e}", "JSON_ERROR"
            
    except Exception as e:
        error_str = str(e)
        logging.warning(f"Full API Error: {error_str}")
        error_type = "GENERAL_API_ERROR"
        if "resource exhausted" in error_str.lower() or "userRateLimitExceeded" in error_str or "429" in error_str:
            error_type = "RATE_LIMIT"
        return None, error_str, error_type

def ocr_worker(
    worker_id, api_key, job_queue, results_queue, failed_indices_set,
    image_folder, log_folder, model_name, generation_config, safety_settings, ocr_prompt, language,
    cancellation_event, progress_lock, total_batches, processed_batches, progress_callback
):
    MAX_RETRIES = 6
    RETRY_DELAY = 5
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        logging.info(f"OCR Worker-{worker_id} initialized with API Key.")
    except Exception as e:
        logging.error(f"OCR Worker-{worker_id} failed to initialize with API Key: {e}")
        return

    while not cancellation_event.is_set():
        try:
            batch_start_index, batch_with_indices = job_queue.get(timeout=1)
        except Empty:
            # Queue is empty and timeout occurred, worker can exit.
            break

        logging.info(f"OCR Worker-{worker_id} picked up batch {batch_start_index}.")
        
        batch_results = None
        for attempt in range(MAX_RETRIES):
            if cancellation_event.is_set():
                break

            results, error_message, error_type = process_batch_with_gemini(
                batch_with_indices, image_folder, log_folder, model, batch_start_index,
                generation_config, safety_settings, ocr_prompt, language
            )

            if results is not None:
                logging.info(f"OCR Worker-{worker_id} successfully processed batch {batch_start_index} on attempt {attempt + 1}.")
                # Pair results with their original absolute indices
                for res in results:
                    try:
                        # The index from Gemini (0, 1, 2...) corresponds to the order in batch_with_indices
                        original_absolute_index = batch_with_indices[res['index']][0]
                        text = res.get('text', '')
                        results_queue.put((original_absolute_index, text))
                    except (IndexError, KeyError) as e:
                        logging.error(f"OCR Worker-{worker_id} encountered an error matching result to index for batch {batch_start_index}: {e}")
                batch_results = results
                break
            else:
                logging.warning(f"OCR Worker-{worker_id} failed batch {batch_start_index} on attempt {attempt + 1}: {error_type} - {error_message}. Retrying...")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
        
        if batch_results is None:
            logging.error(f"OCR Worker-{worker_id} failed batch {batch_start_index} after {MAX_RETRIES} attempts. Skipping this batch.")
            failed_indices_set.add(batch_start_index)

        with progress_lock:
            processed_batches[0] += 1
            if progress_callback:
                percentage = (processed_batches[0] / total_batches) * 100
                progress_callback(f"OCR: {processed_batches[0]}/{total_batches} batches", percentage)
        
        job_queue.task_done()

def run_ocr_pipeline(subtitles: list, image_folder: str, log_folder: str, api_keys: list, model_name: str, generation_config: dict, safety_settings: list, batch_size: int, ocr_prompt: str, language: str, cancellation_event: threading.Event, frame_rate: float, progress_callback=None, indices_to_process=None) -> tuple[list | None, str]:
    if not api_keys: return None, "No API keys provided."
    if not subtitles: return None, "No subtitles to process."

    if indices_to_process is not None:
        all_indices_to_process = set()
        for start_index in indices_to_process:
            all_indices_to_process.update(range(start_index, min(start_index + batch_size, len(subtitles))))
        process_mask = [i in all_indices_to_process for i in range(len(subtitles))]
    else:
        process_mask = [True] * len(subtitles)

    job_queue = Queue()
    total_batches = 0
    for i in range(0, len(subtitles), batch_size):
        batch_mask = process_mask[i:i + batch_size]
        if not any(batch_mask):
            continue
        
        # Create a list of tuples: (absolute_index, event_dictionary)
        batch_with_indices = [
            (i + idx, subtitles[i + idx]) 
            for idx, process in enumerate(batch_mask) if process
        ]
        
        if batch_with_indices:
            job_queue.put((i, batch_with_indices))
            total_batches += 1

    if total_batches == 0:
        return subtitles, "No subtitles needed processing."

    logging.info(f"Starting parallel OCR process with {len(api_keys)} API key(s) across {total_batches} batches.")

    results_queue = Queue()
    failed_indices_set = set()
    progress_lock = threading.Lock()
    processed_batches = [0]

    threads = []
    for i in range(len(api_keys)):
        worker = threading.Thread(
            target=ocr_worker,
            args=(
                i + 1, api_keys[i], job_queue, results_queue, failed_indices_set,
                image_folder, log_folder, model_name, generation_config, safety_settings, ocr_prompt, language,
                cancellation_event, progress_lock, total_batches, processed_batches, progress_callback
            )
        )
        threads.append(worker)
        worker.start()

    job_queue.join()
    
    for t in threads:
        t.join()

    if cancellation_event.is_set():
        return None, "OCR process cancelled by user."

    # Process results from the queue
    while not results_queue.empty():
        absolute_index, text = results_queue.get()
        if 0 <= absolute_index < len(subtitles):
            subtitles[absolute_index]['text'] = text

    settings = load_settings()
    existing_failed = set(settings.get('last_failed_batches', []))
    all_failed_indices = existing_failed.union(failed_indices_set)
    settings['last_failed_batches'] = sorted(list(all_failed_indices))
    save_settings(settings)
    
    if not all_failed_indices:
        # Return the original subtitles list populated with OCR results.
        # Filtering and merging are disabled as per user request.
        logging.info("OCR process completed. Subtitle filtering and merging are currently disabled.")
        logging.info(f"[DEBUG] ocr.py: Returning {len(subtitles)} subtitles to app_context.")
        return subtitles, "OCR process completed."
    else:
        logging.warning(f"OCR process completed with {len(all_failed_indices)} failed batches. Please review the logs for more details.")
        return subtitles, "OCR process completed with some failed batches."
