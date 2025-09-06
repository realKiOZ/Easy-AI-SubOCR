import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import logging
import shutil
import subprocess
import os
import re

def check_tools_availability():
    missing_tools = []
    tools = ["ffmpeg", "mkvextract", "java"]
    for tool in tools:
        if not shutil.which(tool):
            missing_tools.append(tool)
    return missing_tools

def parse_bdsup2sub_xml(xml_path: str) -> list | None:
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        events = []
        
        format_tag = root.find('Description/Format')
        frame_rate_str = format_tag.get('FrameRate', '23.976') if format_tag is not None else '23.976'
        frame_rate = float(frame_rate_str)

        for event in root.findall('Events/Event'):
            start_tc = event.get('InTC')
            end_tc = event.get('OutTC')
            graphic_tag = event.find('Graphic')
            
            if graphic_tag is not None and graphic_tag.text:
                events.append({
                    'start_srt': format_time_for_srt(start_tc, frame_rate),
                    'end_srt': format_time_for_srt(end_tc, frame_rate),
                    'image_file': graphic_tag.text.strip()
                })
        return events
    except Exception as e:
        logging.error(f"Error parsing XML file '{xml_path}': {e}")
        return None

def format_time_for_srt(tc: str, frame_rate: float) -> str:
    try:
        parts = tc.split(':')
        h, m, s, f = [int(p) for p in parts]
        ms = int((f / frame_rate) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    except (ValueError, IndexError) as e:
        logging.error(f"Invalid timecode format: {tc}. Error: {e}")
        return "00:00:00,000"

def parse_subtitle_edit_html(html_path: str) -> list | None:
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        soup = BeautifulSoup(content, 'lxml')
        events = []

        rows = soup.find_all('tr')
        if len(rows) > 1:
            for row in rows[1:]:
                cols = row.find_all('td')
                if len(cols) < 5: continue
                time_str = cols[1].text.strip()
                start_srt, end_srt = [t.strip() for t in time_str.split('-->')]
                image_tag = cols[4].find('img')
                if image_tag and image_tag.has_attr('src'):
                    events.append({
                        'start_srt': start_srt,
                        'end_srt': end_srt,
                        'image_file': image_tag['src']
                    })
            return events

        pattern = re.compile(r"#\d+:([\d:.,]+)->([\d:.,]+).*?src='(.*?)'")
        matches = pattern.findall(content)
        
        for start_time, end_time, img_file in matches:
            def normalize_time(t_str: str) -> str:
                t_str = t_str.replace('.', ',')
                parts = t_str.split(':')
                
                if len(parts) == 3:
                    h, m, s_ms = parts
                    s, ms = s_ms.split(',')
                    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms}"
                elif len(parts) == 2:
                    m, s_ms = parts
                    s, ms = s_ms.split(',')
                    return f"00:{int(m):02d}:{int(s):02d},{ms}"
                else:
                    logging.warning(f"Unknown time format: {t_str}")
                    return "00:00:00,000"

            events.append({
                'start_srt': normalize_time(start_time),
                'end_srt': normalize_time(end_time),
                'image_file': img_file
            })
        
        return events

    except Exception as e:
        logging.error(f"Error parsing HTML file '{html_path}': {e}")
        return None

def is_cuda_available():
    try:
        import cv2
        return cv2.cuda.getCudaEnabledDeviceCount() > 0
    except Exception as e:
        logging.warning(f"Could not check for CUDA availability: {e}")
        return False

def srt_time_to_ms(time_str):
    """Converts SRT time format to milliseconds."""
    parts = re.split('[:,]', time_str)
    return int(parts[0]) * 3600000 + int(parts[1]) * 60000 + int(parts[2]) * 1000 + int(parts[3])

def ms_to_srt_time(ms):
    """Converts milliseconds to SRT time format."""
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"

def merge_subtitles(subtitles: list, frame_rate: float) -> list:
    """Merges adjacent subtitles with identical text."""
    if not subtitles:
        return []

    frame_duration_ms = 1000 / frame_rate
    merged_subtitles = []
    
    # Make a copy to avoid modifying the list while iterating
    subs_iterator = iter(subtitles)
    
    current_sub = next(subs_iterator, None)
    if current_sub is None:
        return []

    for next_sub in subs_iterator:
        # Check for identical text content
        if current_sub['text'] == next_sub['text']:
            current_end_ms = srt_time_to_ms(current_sub['end_srt'])
            next_start_ms = srt_time_to_ms(next_sub['start_srt'])
            
            # Check if the time gap is within one frame duration
            if 0 <= (next_start_ms - current_end_ms) <= frame_duration_ms:
                # Merge by extending the end time of the current subtitle
                current_sub['end_srt'] = next_sub['end_srt']
                continue  # Skip adding the current_sub yet, as it might merge with the next one too

        merged_subtitles.append(current_sub)
        current_sub = next_sub
    
    # Add the last subtitle
    if current_sub is not None:
        merged_subtitles.append(current_sub)

    return merged_subtitles
