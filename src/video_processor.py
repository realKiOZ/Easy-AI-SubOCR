# src/video_processor.py

import subprocess
import json
import os
import logging
import re
from src.localization import EN_TRANSLATIONS

def inspect_video_subtitles(video_path: str) -> tuple[list, str | None]:
    """{docstring}"""
    command = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams',
        '-select_streams', 's', video_path
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        data = json.loads(result.stdout)
        subtitle_streams = []
        for stream in data.get('streams', []):
            if stream.get('codec_name') in ['hdmv_pgs_subtitle', 'dvd_subtitle']:
                lang = stream.get('tags', {}).get('language', 'und')
                title = stream.get('tags', {}).get('title', '')
                info = f"Stream #{stream['index']} - {lang.upper()} - {stream['codec_name']}"
                if title: info += f" ({title})"
                subtitle_streams.append({'index': stream['index'], 'info': info})
        if not subtitle_streams:
            return [], EN_TRANSLATIONS["error_no_image_subtitle_streams_found"]
        return subtitle_streams, None
    except FileNotFoundError:
        return [], EN_TRANSLATIONS["error_ffprobe_not_found"]
    except subprocess.CalledProcessError as e:
        return [], EN_TRANSLATIONS["error_video_scan_failed"].format(stderr=e.stderr)
    except Exception as e:
        return [], EN_TRANSLATIONS["error_unknown_video_scan"].format(error=e)

def extract_pgs_subtitles(video_path: str, stream_index: int, session_dir: str, bdsup2sub_path: str, progress_callback=None, cancellation_event=None) -> tuple[str | None, str | None, str | None]:
    """{docstring}"""
    images_output_dir = os.path.join(session_dir, "images")
    os.makedirs(images_output_dir, exist_ok=True)
    
    sup_file_path = os.path.join(images_output_dir, "temp.sup")
    xml_file_path = os.path.join(images_output_dir, "temp.xml")

    track_id = stream_index
    track_spec = f"{track_id}:{sup_file_path}"
    
    mkvextract_command = ['mkvextract', '--gui-mode', video_path, 'tracks', track_spec]
    try:
        logging.info(EN_TRANSLATIONS["log_stage1_extracting_raw_stream"])
        creationflags = 0
        if os.name == 'nt':
            creationflags = subprocess.CREATE_NO_WINDOW

        process = subprocess.Popen(
            mkvextract_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=creationflags
        )

        # With --gui-mode, mkvextract will output progress to stdout as #GUI#progress X%
        progress_found = False
        last_logged_percent = -1
        log_interval = 10  # Log every 10%

        for line in iter(process.stdout.readline, ''):
            if cancellation_event and cancellation_event.is_set():
                logging.info(EN_TRANSLATIONS["log_mkvextract_cancellation_requested"])
                process.terminate()
                break

            stripped_line = line.strip()
            if not stripped_line:
                continue
            
            if stripped_line.startswith("#GUI#progress"):
                try:
                    percent_str = stripped_line.split(" ")[1].replace('%', '')
                    percent = int(percent_str)
                    progress_found = True
                    
                    if progress_callback:
                        progress_callback(percent)

                    # Log progress at intervals to avoid spamming
                    if percent >= last_logged_percent + log_interval:
                        logging.info(EN_TRANSLATIONS["log_stage1_extracting_progress"].format(percent=percent))
                        last_logged_percent = percent

                except (IndexError, ValueError):
                    logging.warning(EN_TRANSLATIONS["warning_cannot_parse_progress_log"].format(line=stripped_line))
            elif stripped_line.startswith("#GUI#error"):
                 logging.error(EN_TRANSLATIONS["error_mkvextract_error_message"].format(message=stripped_line.replace('#GUI#error ', '')))
        
        process.stdout.close()
        process.stderr.close()
        return_code = process.wait()

        if cancellation_event and cancellation_event.is_set():
            return None, None, EN_TRANSLATIONS["error_extraction_cancelled_by_user"]

        if return_code != 0:
            logging.error(EN_TRANSLATIONS["log_mkvextract_exit_code_error"].format(code=return_code))
            return None, None, EN_TRANSLATIONS["error_mkvextract_failed_check_log"]

        # If no Progress line was found and no error, the process might have been too fast
        if not progress_found:
            logging.info(EN_TRANSLATIONS["log_stage1_extraction_fast"])

        logging.info(EN_TRANSLATIONS["log_stage1_complete"])

    except FileNotFoundError:
        return None, None, EN_TRANSLATIONS["error_mkvextract_not_found"]
    except Exception as e:
        logging.error(EN_TRANSLATIONS["error_mkvextract_unexpected"].format(error=e))
        return None, None, EN_TRANSLATIONS["error_mkvextract_details"].format(error=e)

    if not os.path.exists(bdsup2sub_path):
        return None, None, EN_TRANSLATIONS["error_bdsup2sub_file_not_found"].format(path=bdsup2sub_path)
    
    java_command = ['java', '-jar', bdsup2sub_path, sup_file_path, '-o', xml_file_path]
    try:
        logging.info(EN_TRANSLATIONS["log_stage2_converting_subtitles"])
        creationflags = 0
        if os.name == 'nt':
            creationflags = subprocess.CREATE_NO_WINDOW

        process = subprocess.Popen(
            java_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=creationflags
        )

        # Only log important messages, skip per-sub progress
        for line in iter(process.stdout.readline, ''):
            stripped_line = line.strip()
            if not stripped_line:
                continue

            # Keywords indicating important messages
            important_keywords = ["loading", "writing", "detected", "conversion", "warn", "error"]
            
            # Filter out unimportant lines
            if any(keyword in stripped_line.lower() for keyword in important_keywords):
                 if "decoding frame" not in stripped_line.lower() and not stripped_line.startswith("#>"):
                    logging.info(stripped_line)
        
        process.stdout.close()
        return_code = process.wait()

        if return_code != 0:
            logging.error(EN_TRANSLATIONS["log_bdsup2sub_exit_code_error"].format(code=return_code))
            return None, None, EN_TRANSLATIONS["error_bdsup2sub_failed_check_log"]

        logging.info(EN_TRANSLATIONS["log_bdsup2sub_complete_success"])
        if not os.path.exists(xml_file_path):
             return None, None, EN_TRANSLATIONS["error_bdsup2sub_no_xml_created"]
        return images_output_dir, xml_file_path, None
        
    except FileNotFoundError:
        return None, None, EN_TRANSLATIONS["error_java_not_found"]
    except Exception as e:
        logging.error(EN_TRANSLATIONS["error_bdsup2sub_unexpected"].format(error=e))
        return None, None, EN_TRANSLATIONS["error_bdsup2sub_details"].format(error=e)
