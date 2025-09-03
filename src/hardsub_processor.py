# src/hardsub_processor.py
import cv2
import numpy as np
import os
import logging
from datetime import timedelta
import subprocess
import re
import shutil
import tempfile
import uuid

from src.settings import APP_TEMP_PATH

EAST_MODEL_PATH = os.path.join("assets", "tools", "frozen_east_text_detection.pb")
VSF_EXECUTABLE_PATH = os.path.abspath(os.path.join("assets", "tools", "videosubfinder", "Release_x64", "VideoSubFinderWXW.exe"))

# --- Các hàm helper ---
def seconds_to_srt_time(seconds):
    if seconds < 0: seconds = 0
    total_seconds = int(seconds)
    milliseconds = int((seconds - total_seconds) * 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def seconds_to_vsf_time(seconds):
    if seconds < 0: seconds = 0
    total_seconds = int(seconds)
    milliseconds = int((seconds - total_seconds) * 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"

def vsf_time_to_seconds(time_str):
    try:
        parts = time_str.split('_')
        h, m, s, ms = map(int, parts)
        return h * 3600 + m * 60 + s + ms / 1000.0
    except (ValueError, IndexError):
        logging.error(f"Could not parse VSF filename time: {time_str}")
        return 0

def smart_resize(image, target_size):
    h, w = image.shape[:2]
    target_w, target_h = target_size
    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    delta_w = target_w - new_w
    delta_h = target_h - new_h
    top, bottom = delta_h // 2, delta_h - (delta_h // 2)
    left, right = delta_w // 2, delta_w - (delta_w // 2)
    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=[0, 0, 0])
    return padded

def detect_text_with_east(frame_area, net, confidence, quality):
    if frame_area is None or frame_area.shape[0] < 32 or frame_area.shape[1] < 32: return False
    new_w = (quality // 32) * 32
    new_h = (quality // 32) * 32
    resized_frame = smart_resize(frame_area, (new_w, new_h))
    blob = cv2.dnn.blobFromImage(resized_frame, 1.0, (new_w, new_h), (123.68, 116.78, 103.94), swapRB=True, crop=False)
    net.setInput(blob)
    layer_names = ["feature_fusion/Conv_7/Sigmoid", "feature_fusion/concat_3"]
    scores, geometry = net.forward(layer_names)
    num_rows, num_cols = scores.shape[2:4]
    for y in range(num_rows):
        scores_data = scores[0, 0, y]
        for x in range(num_cols):
            if scores_data[x] > confidence:
                return True
    return False

def process_subtitle_channel(has_text, current_event, frame_time_sec, all_events, frame_idx):
    if has_text:
        if current_event.get("start_time") is None:
            current_event["start_time"] = frame_time_sec
            current_event["start_frame"] = frame_idx
        current_event["end_time"] = frame_time_sec
        current_event["end_frame"] = frame_idx
    elif current_event.get("start_time") is not None:
        all_events.append(current_event.copy())
        current_event["start_time"] = None
        current_event["start_frame"] = None
        current_event["end_time"] = None
        current_event["end_frame"] = None

def run_hardsub_pipeline(video_path, output_image_folder, options, progress_callback=None, cancellation_event=None):
    if not os.path.exists(video_path): return None, "Video file not found.", None
    if not os.path.exists(EAST_MODEL_PATH): return None, "EAST text detection model not found.", None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened(): return None, "Could not open video file.", None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0: return None, "Could not determine video FPS.", None

    use_gpu = options.get("use_gpu", True)
    confidence = options.get("confidence", 0.5)
    quality = options.get("quality", 320)
    scan_area_height_percent = options.get("scan_area_height", 30) / 100.0

    logging.info("Loading EAST text detection model...")
    net = cv2.dnn.readNet(EAST_MODEL_PATH)
    if use_gpu:
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
        logging.info("EAST model is set to run on GPU (CUDA).")
    else:
        logging.info("EAST model is set to run on CPU.")

    east_subtitles = []
    top_event, bottom_event = {}, {}
    all_top_events, all_bottom_events = [], []
    frame_idx = 0
    logging.info("Starting hardsub pipeline (EAST detection)...")

    while cap.isOpened():
        if cancellation_event and cancellation_event.is_set():
            logging.info("Hardsub pipeline cancelled by user.")
            cap.release()
            return [], "Cancelled by user.", None
        ret, frame = cap.read()
        if not ret: break
        frame_time_sec = frame_idx / fps
        if progress_callback and frame_idx % int(fps*2) == 0:
            percentage = (frame_idx / total_frames) * 100
            progress_callback(f"Scanning video: {seconds_to_srt_time(frame_time_sec)}", percentage)
        height, _, _ = frame.shape
        scan_area_height = int(height * scan_area_height_percent)
        scan_top = options.get("scan_top", True)
        scan_bottom = options.get("scan_bottom", True)
        if scan_bottom:
            has_bottom_text = detect_text_with_east(frame[height - scan_area_height:height, :], net, confidence, quality)
            process_subtitle_channel(has_bottom_text, bottom_event, frame_time_sec, all_bottom_events, frame_idx)
        if scan_top:
            has_top_text = detect_text_with_east(frame[0:scan_area_height, :], net, confidence, quality)
            process_subtitle_channel(has_top_text, top_event, frame_time_sec, all_top_events, frame_idx)
        frame_idx += 1

    if top_event.get("start_time") is not None: all_top_events.append(top_event)
    if bottom_event.get("start_time") is not None: all_bottom_events.append(bottom_event)
    cap.release()

    flag_file = None
    if os.path.exists(VSF_EXECUTABLE_PATH):
        master_event_list = [('top', event) for event in all_top_events] + [('bottom', event) for event in all_bottom_events]
        master_event_list.sort(key=lambda x: x[1]['start_time'])
        
        if master_event_list:
            total_events = len(master_event_list)
            use_gpu_option = options.get("use_gpu", True)
            
            exe_path_norm = VSF_EXECUTABLE_PATH.replace('/', '\\')
            vsf_dir_norm = os.path.dirname(exe_path_norm)
            video_path_norm = os.path.abspath(video_path).replace('/', '\\')
            
            batch_content = ["@echo off", f'cd /d "{vsf_dir_norm}"', ""]
            
            for i, (channel, event) in enumerate(master_event_list):
                event_temp_dir = os.path.join(APP_TEMP_PATH, f"vsf_event_{channel}_{event.get('start_frame', 0)}_{event.get('end_frame', 0)}")
                if os.path.exists(event_temp_dir): shutil.rmtree(event_temp_dir)
                os.makedirs(event_temp_dir)
                output_dir_norm = os.path.abspath(event_temp_dir).replace('/', '\\')

                command_parts = [ f'"{exe_path_norm}"', '--clear_dirs', '--run_search', '--open_video_opencv',
                                  f'--start_time {seconds_to_vsf_time(event["start_time"])}', f'--end_time {seconds_to_vsf_time(event["end_time"])}',
                                  f'--input_video "{video_path_norm}"', f'--output_dir "{output_dir_norm}"' ]
                if use_gpu_option: command_parts.append('--use_cuda')
                scan_val = scan_area_height_percent
                bottom_start, top_end = (1.0 - scan_val, 1.0) if channel == 'top' else (0.0, scan_val)
                command_parts.extend([f'--bottom_video_image_percent_end {bottom_start:.6f}', f'--top_video_image_percent_end {top_end:.6f}'])
                command_parts.extend(['/moderate_threshold 0.25', '/image_scale_for_clear_image 4'])

                batch_content.append(f"echo --- Processing event {i+1}/{total_events} ({channel} @ {seconds_to_srt_time(event['start_time'])}) ---")
                batch_content.append(" ".join(command_parts))
                batch_content.append("")
                
            # Tạo file cờ ngay trước khi chạy batch
            flag_file = os.path.join(APP_TEMP_PATH, f"vsf_running_{uuid.uuid4()}.flag")
            with open(flag_file, "w") as f: f.write("running")

            # Thêm lệnh xóa file cờ vào cuối file batch
            batch_content.extend([f"del \"{flag_file}\"", "exit"])
            
            batch_file = os.path.join(APP_TEMP_PATH, f"vsf_master_{uuid.uuid4()}.bat")
            with open(batch_file, "w") as f: f.write("\n".join(batch_content))

            logging.info(f"Launching master VSF batch file for {total_events} events...")
            # Chạy 1 lần duy nhất, không đợi, nhưng có thể theo dõi qua file cờ
            subprocess.Popen(f'start "VSF Runner" /min /low "{batch_file}"', shell=True)
    else:
        logging.warning("VideoSubFinder not found. Skipping refinement step.")
    
    # Trả về kết quả thô của EAST để hiển thị tạm thời
    cap = cv2.VideoCapture(video_path)
    all_events_tmp = [("top", event) for event in all_top_events] + [("bottom", event) for event in all_bottom_events]
    for channel, event in all_events_tmp:
        middle_frame_idx = (event.get("start_frame", 0) + event.get("end_frame", 0)) // 2
        cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame_idx)
        ret, frame = cap.read()
        if ret:
            height, _, _ = frame.shape
            scan_area_h = int(height * scan_area_height_percent)
            crop_img = frame[0:scan_area_h, :] if channel == "top" else frame[height - scan_area_h:height, :]
            image_filename = f"hardsub_tmp_{len(east_subtitles):05d}.png"
            cv2.imwrite(os.path.join(output_image_folder, image_filename), crop_img)
            east_subtitles.append({"start_srt": seconds_to_srt_time(event["start_time"]), "end_srt": seconds_to_srt_time(event["end_time"]), "image_file": image_filename, "channel": channel})
    cap.release()
    
    return east_subtitles, None, flag_file