# src/utils.py

import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import logging
import shutil
import subprocess
import os
from src.localization import EN_TRANSLATIONS
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import re

def check_tools_availability():
    """
    Checks for the availability of required command-line tools (ffmpeg, mkvextract, java).
    Returns a list of missing tools.
    """
    missing_tools = []
    tools = ["ffmpeg", "mkvextract", "java"]
    for tool in tools:
        if not shutil.which(tool):
            missing_tools.append(tool)
    return missing_tools

def parse_bdsup2sub_xml(xml_path: str) -> list | None:
    """Parses an XML file from BDSup2Sub to get timing and image file names."""
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
        logging.error(EN_TRANSLATIONS["log_xml_parse_error"].format(path=xml_path, error=e))
        return None

def format_time_for_srt(tc: str, frame_rate: float) -> str:
    """Converts timecode HH:MM:SS:FF to SRT format HH:MM:SS,ms."""
    try:
        parts = tc.split(':')
        h, m, s, f = [int(p) for p in parts]
        ms = int((f / frame_rate) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    except (ValueError, IndexError) as e:
        logging.error(EN_TRANSLATIONS["log_invalid_timecode_format"].format(timecode=tc, error=e))
        return "00:00:00,000"

def parse_subtitle_edit_html(html_path: str) -> list | None:
    """
    Parses an HTML file from Subtitle Edit to get timing and image file names.
    Supports both table format and body-text format.
    """
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        soup = BeautifulSoup(content, 'lxml')
        events = []

        # Case 1: Check for old table format
        rows = soup.find_all('tr')
        if len(rows) > 1:
            for row in rows[1:]: # Skip header row
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

        # Case 2: If no table, try parsing new body-text format using regex
        pattern = re.compile(r"#\d+:([\d:.,]+)->([\d:.,]+).*?src='(.*?)'")
        matches = pattern.findall(content)
        
        for start_time, end_time, img_file in matches:
            def normalize_time(t_str: str) -> str:
                t_str = t_str.replace('.', ',')
                parts = t_str.split(':')
                
                if len(parts) == 3: # H:MM:SS,ms
                    h, m, s_ms = parts
                    s, ms = s_ms.split(',')
                    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms}"
                elif len(parts) == 2: # M:SS,ms
                    m, s_ms = parts
                    s, ms = s_ms.split(',')
                    return f"00:{int(m):02d}:{int(s):02d},{ms}"
                else:
                    logging.warning(EN_TRANSLATIONS["warning_unknown_time_format"].format(time_string=t_str))
                    return "00:00:00,000"

            events.append({
                'start_srt': normalize_time(start_time),
                'end_srt': normalize_time(end_time),
                'image_file': img_file
            })
        
        return events

    except Exception as e:
        logging.error(EN_TRANSLATIONS["log_html_parse_error"].format(path=html_path, error=e))
        return None
