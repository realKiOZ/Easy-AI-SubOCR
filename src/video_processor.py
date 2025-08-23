# src/video_processor.py

import subprocess
import json
import os
import logging
import xml.etree.ElementTree as ET # <-- THÊM DÒNG NÀY
from src.tool_path_manager import get_tool_path

def inspect_video_subtitles(video_path: str) -> tuple[list, str | None]:
    """Uses ffprobe to scan video files and find image subtitle streams."""
    ffprobe_path = get_tool_path('ffprobe')
    command = [
        ffprobe_path, '-v', 'quiet', '-print_format', 'json', '-show_streams',
        '-select_streams', 's', video_path
    ]
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, 
            encoding='utf-8', creationflags=creationflags
        )
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
            return [], "No image subtitle streams (PGS, VobSub) found in this video."
        return subtitle_streams, None
    except FileNotFoundError:
        return [], "Error: `ffprobe` not found. Please check assets/tools."
    except subprocess.CalledProcessError as e:
        return [], f"Error scanning video: {e.stderr}"
    except Exception as e:
        return [], f"Unknown error: {e}"

def extract_pgs_subtitles(video_path: str, stream_index: int, session_dir: str, bdsup2sub_path: str, progress_callback=None, cancellation_event=None) -> tuple[str | None, str | None, str | None]:
    """Uses mkvextract and BDSup2Sub to extract and convert subtitles."""
    images_output_dir = os.path.join(session_dir, "images")
    os.makedirs(images_output_dir, exist_ok=True)
    
    sup_file_path = os.path.join(images_output_dir, "temp.sup")
    xml_file_path = os.path.join(images_output_dir, "temp.xml")

    track_spec = f"{stream_index}:{sup_file_path}"
    
    mkvextract_path = get_tool_path('mkvextract')
    mkvextract_command = [mkvextract_path, '--gui-mode', video_path, 'tracks', track_spec]
    try:
        logging.info("Stage 1/2: Extracting raw subtitle stream from video...")
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

        process = subprocess.Popen(
            mkvextract_command,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding='utf-8', errors='replace', creationflags=creationflags
        )
        
        for line in iter(process.stdout.readline, ''):
            if cancellation_event and cancellation_event.is_set():
                logging.info("Cancellation requested, terminating mkvextract.")
                process.terminate()
                break
            if line.strip().startswith("#GUI#progress"):
                try:
                    percent = int(line.strip().split(" ")[1].replace('%', ''))
                    if progress_callback: progress_callback(percent)
                except (IndexError, ValueError):
                    pass
        
        _, stderr = process.communicate()
        return_code = process.wait()

        if cancellation_event and cancellation_event.is_set():
            return None, None, "Extraction cancelled by user."

        if return_code != 0:
            logging.error(f"mkvextract exited with error code: {return_code}.")
            logging.error(f"mkvextract stderr: {stderr}")
            return None, None, "Error running mkvextract. Please check log."

        logging.info("Stage 1 complete.")
    except FileNotFoundError:
        return None, None, "Error: `mkvextract` not found. Please check assets/tools."
    except Exception as e:
        return None, None, f"Error running mkvextract. Details: {e}"

    if not os.path.exists(bdsup2sub_path):
        return None, None, f"Error: File '{bdsup2sub_path}' not found. Please check settings."
    
    java_path = get_tool_path('java')
    java_command = [java_path, '-jar', bdsup2sub_path, sup_file_path, '-o', xml_file_path]
    try:
        logging.info("Stage 2/2: Converting raw subtitles to images and timing file...")
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        subprocess.run(
            java_command, capture_output=True, text=True, check=True,
            encoding='utf-8', errors='replace', creationflags=creationflags
        )
        
        # --- LOGIC ĐẾM SỐ LƯỢNG BẮT ĐẦU TỪ ĐÂY ---
        if not os.path.exists(xml_file_path):
             return None, None, "Error: BDSup2Sub ran but did not create an XML file."
        
        try:
            # Phân tích file XML để đếm số lượng phụ đề
            tree = ET.parse(xml_file_path)
            root = tree.getroot()
            subtitle_count = len(root.findall('Events/Event'))
            logging.info(f"BDSup2Sub completed successfully. Found {subtitle_count} subtitles.")
        except ET.ParseError as e:
            # Nếu không parse được XML, ghi log cảnh báo và dùng thông báo cũ
            logging.warning(f"Could not parse XML to get subtitle count, but file was created. Error: {e}")
            logging.info("BDSup2Sub completed successfully.")

        return images_output_dir, xml_file_path, None
        
    except FileNotFoundError:
        return None, None, f"Error: `java` not found. Please check assets/tools. Expected at: {java_path}"
    except subprocess.CalledProcessError as e:
        logging.error(f"BDSup2Sub exited with error code: {e.returncode}. Please check log for details.")
        logging.error(f"--- BDSup2Sub Full Output (Error) ---\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}")
        return None, None, "Error running BDSup2Sub. Please check log for details."
    except Exception as e:
        logging.error(f"Unexpected error running BDSup2Sub: {e}")
        return None, None, f"Error running BDSup2Sub. Details: {e}"
