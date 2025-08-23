# src/ocr.py

import os
import base64
import json
import google.generativeai as genai
from tqdm import tqdm
import time
import re
import logging
import threading

from src.utils import parse_bdsup2sub_xml, parse_subtitle_edit_html
from src.settings import save_settings, load_settings
from src.localization import EN_TRANSLATIONS

def get_available_models(api_key: str) -> tuple[list, str | None]:
    try:
        logging.info(EN_TRANSLATIONS["log_getting_gemini_models"])
        genai.configure(api_key=api_key)
        models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods and "models/gemini" in m.name:
                models.append(m.name.replace("models/", ""))
        if not models:
            logging.warning(EN_TRANSLATIONS["warning_no_gemini_models_found"])
            return [], EN_TRANSLATIONS["error_no_gemini_models_found_check_key"]
        logging.info(EN_TRANSLATIONS["log_compatible_models_found"].format(count=len(models)))
        return sorted(models), None
    except Exception as e:
        logging.error(EN_TRANSLATIONS["log_get_models_api_error"].format(error=e))
        return [], EN_TRANSLATIONS["error_invalid_api_key_connection"].format(error=e)

def process_batch_with_gemini(batch_of_events, image_folder, log_folder, model, batch_start_index, generation_config, safety_settings, ocr_prompt):
    api_request_parts = [ocr_prompt]
    for event in batch_of_events:
        image_path = os.path.join(image_folder, event['image_file'])
        try:
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                api_request_parts.append({"mime_type": "image/png", "data": encoded_string})
        except FileNotFoundError:
            logging.warning(EN_TRANSLATIONS["warning_image_file_not_found"].format(path=image_path))
            continue
    if len(api_request_parts) <= 1: return None, EN_TRANSLATIONS["error_no_images_to_process"]

    try:
        response = model.generate_content(
            api_request_parts,
            generation_config=generation_config,
            safety_settings=safety_settings
        )
        
        # Save raw JSON results to a separate log directory
        log_filename = f"batch_{batch_start_index:04d}.json"
        log_filepath = os.path.join(log_folder, log_filename)
        try:
            json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response.text)
            json_content = json_match.group(1) if json_match else response.text
            parsed_json = json.loads(json_content)
            with open(log_filepath, 'w', encoding='utf-8') as f:
                json.dump(parsed_json, f, indent=4, ensure_ascii=False)
        except (json.JSONDecodeError, AttributeError, IndexError) as log_e:
            logging.error(EN_TRANSLATIONS["log_error_parsing_saving_log"].format(filename=log_filename, error=log_e))
            # Log raw content if parsing fails
            with open(log_filepath.replace('.json', '.txt'), 'w', encoding='utf-8') as f:
                f.write(response.text)
        except Exception as log_e:
            logging.error(EN_TRANSLATIONS["log_unknown_error_saving_log"].format(filename=log_filename, error=log_e))

        if not response.parts:
            reason = EN_TRANSLATIONS["error_api_no_content"]
            if hasattr(response, 'candidates') and response.candidates:
                reason += EN_TRANSLATIONS["error_api_finish_reason"].format(reason=response.candidates[0].finish_reason)
            return None, reason
        
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response.text)
        if json_match:
            json_str = json_match.group(1)
            return json.loads(json_str), None
        else:
            try:
                return json.loads(response.text), None
            except json.JSONDecodeError:
                error_msg = EN_TRANSLATIONS["warning_json_parse_failed"].format(response_text=response.text[:200])
                logging.warning(error_msg)
                return None, error_msg
            
    except genai.types.BlockedPromptException as e:
        return None, EN_TRANSLATIONS["error_prompt_blocked"].format(error=e)
    except genai.types.APIError as e:
        return None, EN_TRANSLATIONS["error_gemini_api"].format(error=e)
    except json.JSONDecodeError as e:
        return None, EN_TRANSLATIONS["error_json_parse_api_response"].format(error=e, response_text=response.text[:200])
    except Exception as e:
        return None, EN_TRANSLATIONS["error_unknown_api_call_json_parse"].format(error=e)

def run_ocr_pipeline(timing_file_path: str, image_folder: str, log_folder: str, api_key: str, model_name: str, generation_config: dict, safety_settings: list, batch_size: int, max_retries: int, ocr_prompt: str, cancellation_event: threading.Event, progress_callback=None) -> tuple[list | None, str]:
    logging.info(EN_TRANSLATIONS["log_starting_ocr_process"])
    try:
        logging.info(EN_TRANSLATIONS["log_configuring_model"].format(model_name=model_name))
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
    except Exception as e:
        logging.error(EN_TRANSLATIONS["error_api_model_config"].format(error=e))
        return None, EN_TRANSLATIONS["error_api_model_config"].format(error=e)

    if timing_file_path.lower().endswith(".xml"):
        subtitles = parse_bdsup2sub_xml(timing_file_path)
    elif timing_file_path.lower().endswith(".html"):
        subtitles = parse_subtitle_edit_html(timing_file_path)
    else:
        return None, EN_TRANSLATIONS["error_unsupported_timing_file_format"]
    if not subtitles:
        return None, EN_TRANSLATIONS["log_timing_file_read_error_corrupt_empty"]

    failed_batches = []
    total_batches = (len(subtitles) + batch_size - 1) // batch_size
    for i in tqdm(range(0, len(subtitles), batch_size), desc="OCR Batches", total=total_batches):
        if cancellation_event.is_set():
            return None, EN_TRANSLATIONS["status_ocr_cancelled"]

        if progress_callback:
            progress_percentage = (i // batch_size) / total_batches * 100
            progress_callback(f"OCR Batches: {i//batch_size}/{total_batches} ({progress_percentage:.0f}%)")

        batch = subtitles[i:i + batch_size]
        results = None
        error_message = ""
        for attempt in range(max_retries):
            if cancellation_event.is_set():
                return None, EN_TRANSLATIONS["status_ocr_cancelled"]
            
            results, error_message = process_batch_with_gemini(
                batch, image_folder, log_folder, model, 
                batch_start_index=i, 
                generation_config=generation_config, 
                safety_settings=safety_settings,
                ocr_prompt=ocr_prompt
            )
            if results is not None:
                break
            else:
                wait_time = 2 ** attempt # Exponential backoff
                logging.warning(EN_TRANSLATIONS["warning_batch_processing_error_retry"].format(index=i, attempt=attempt + 1, max_retries=max_retries, wait_time=wait_time, error_message=error_message))
                time.sleep(wait_time)
        if results is not None:
            # With the new prompt, we expect 'results' to always be a list of dicts
            if not isinstance(results, list):
                logging.error(EN_TRANSLATIONS["error_api_result_not_list"].format(index=i))
                continue # Skip this batch if the format is incorrect

            for res in results:
                try:
                    if not isinstance(res, dict) or 'index' not in res or 'text' not in res:
                        logging.warning(EN_TRANSLATIONS["warning_invalid_result_item_in_batch"].format(index=i, result=res))
                        continue
                    
                    relative_index = res['index']
                    text = res.get('text', '')
                    absolute_index = i + relative_index

                    if 0 <= absolute_index < len(subtitles):
                        subtitles[absolute_index]['text'] = text
                    else:
                        logging.warning(EN_TRANSLATIONS["warning_absolute_index_out_of_range"].format(absolute_index=absolute_index, index=i))

                except (TypeError, KeyError, ValueError) as e:
                    logging.error(EN_TRANSLATIONS["error_processing_result_item_in_batch"].format(index=i, error=e, result=res))
        else:
            logging.error(EN_TRANSLATIONS["error_batch_failed_after_retries"].format(index=i, max_retries=max_retries, error_message=error_message))
            failed_batches.append(i)
    if failed_batches:
        settings = load_settings()
        settings['last_failed_batches'] = failed_batches
        save_settings(settings)
        logging.info(EN_TRANSLATIONS["log_failed_batches_recorded"].format(failed_batches=failed_batches))
    return subtitles, EN_TRANSLATIONS["ocr_complete_message"]
