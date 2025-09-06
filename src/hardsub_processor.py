import cv2
import numpy as np
import os
import logging
import subprocess
import re
import shutil
import uuid
import threading
import time

from src.settings import APP_TEMP_PATH, load_settings
from src.tool_path_manager import resource_path

EAST_MODEL_PATH = os.path.join("assets", "tools", "frozen_east_text_detection.pb")

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
        logging.error(f"Failed to parse VSF filename time: {time_str}")
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

def run_hardsub_pipeline(video_path, output_image_folder, options, run_id, progress_callback=None, cancellation_event=None):
    start_time = time.time()
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
        logging.info("EAST model: GPU acceleration enabled (CUDA).")
    else:
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        logging.info("EAST model: Running on CPU.")

    east_subtitles = []
    top_event, bottom_event = {}, {}
    all_top_events, all_bottom_events = [], []
    frame_idx = 0
    # Removed: logging.info("Starting EAST text detection...")

    while cap.isOpened():
        if cancellation_event and cancellation_event.is_set():
            logging.info("EAST detection cancelled by user.")
            cap.release()
            return [], "Cancelled by user.", None
        ret, frame = cap.read()
        if not ret: break
        frame_time_sec = frame_idx / fps
        if progress_callback and frame_idx % int(fps*2) == 0:
            percentage = (frame_idx / total_frames) * 100
            progress_callback(f"Scanning video for text: {seconds_to_srt_time(frame_time_sec)}", percentage)
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
    logging.info(f"EAST detection complete. Found {len(all_top_events) + len(all_bottom_events)} potential subtitle events in {time.time() - start_time:.2f} seconds.")

    flag_file = None
    settings = load_settings()
    vsf_cli_filename = settings["hardsub_settings"].get("vsf_cli_executable", "videosubfinder-cli-cpu.exe")
    
    if options.get("use_gpu", True):
        vsf_cli_filename = "videosubfinder-cli-gpu-cuda.exe"
    else:
        vsf_cli_filename = "videosubfinder-cli-cpu.exe"
        
    VSF_EXECUTABLE_PATH_CLI = resource_path(os.path.join("assets", "tools", "vsf-cli", vsf_cli_filename))

    if not os.path.exists(VSF_EXECUTABLE_PATH_CLI):
        logging.warning(f"VSF CLI executable not found at '{VSF_EXECUTABLE_PATH_CLI}'. Skipping refinement step.")
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
        return east_subtitles, "VSF CLI executable not found.", None
    
    if os.path.exists(VSF_EXECUTABLE_PATH_CLI):
        master_event_list = [('top', event) for event in all_top_events] + [('bottom', event) for event in all_bottom_events]
        master_event_list.sort(key=lambda x: x[1]['start_time'])
        
        if master_event_list:
            total_events = len(master_event_list)
            use_gpu_option = options.get("use_gpu", True)

            exe_path_norm = VSF_EXECUTABLE_PATH_CLI.replace('/', '\\')
            vsf_dir_norm = os.path.dirname(exe_path_norm)
            video_path_norm = os.path.abspath(video_path).replace('/', '\\')

            flag_file = os.path.join(APP_TEMP_PATH, f"vsf_running_{uuid.uuid4()}.flag")
            with open(flag_file, "w") as f: f.write("running")

            def vsf_worker():
                creationflags = 0
                if os.name == 'nt':
                    creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS

                try:
                    for i, (channel, event) in enumerate(master_event_list):
                        if cancellation_event and cancellation_event.is_set():
                            logging.info("VSF refinement cancelled by user.")
                            break
                        
                        progress_message = f"Refining subtitles (VSF): Event {i+1}/{total_events} ({channel} @ {seconds_to_srt_time(event['start_time'])})"
                        if progress_callback:
                            percentage = 50 + ((i / total_events) * 50)
                            progress_callback(progress_message, percentage)

                        event_temp_dir = os.path.join(APP_TEMP_PATH, f"vsf_event_{run_id}_{channel}_{event.get('start_frame', 0)}_{event.get('end_frame', 0)}")
                        if os.path.exists(event_temp_dir): shutil.rmtree(event_temp_dir)
                        os.makedirs(event_temp_dir, exist_ok=True)
                        output_dir_norm = os.path.abspath(event_temp_dir).replace('/', '\\')

                        command_parts = [
                            exe_path_norm, '-c', '-r', '-ovocv',
                            '-s', seconds_to_vsf_time(event["start_time"]),
                            '-e', seconds_to_vsf_time(event["end_time"]),
                            '-i', video_path_norm,
                            '-o', output_dir_norm
                        ]
                        if use_gpu_option: command_parts.append('-uc')
                        
                        scan_val = scan_area_height_percent
                        if channel == 'top':
                            bottom_end_param = 1.0 - scan_val
                            top_end_param = 1.0
                        else: # bottom
                            bottom_end_param = 0.0
                            top_end_param = scan_val

                        command_parts.extend([
                            '-be', f'{bottom_end_param:.6f}',
                            '-te', f'{top_end_param:.6f}',
                        ])
                        
                        logging.debug(f"Running VSF command: {' '.join(command_parts)}")
                        p = subprocess.Popen(
                            command_parts, 
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.PIPE, 
                            text=True, 
                            encoding='utf-8',
                            cwd=vsf_dir_norm
                        )
                        stdout, stderr = p.communicate()

                        if p.returncode != 0:
                            logging.error(f"VSF process for event {i+1} failed with return code {p.returncode}.")
                            if stderr:
                                logging.error(f"VSF Stderr:\n{stderr}")
                        if stdout:
                            logging.debug(f"VSF Stdout for event {i+1}:\n{stdout}")

                finally:
                    if os.path.exists(flag_file):
                        try:
                            os.remove(flag_file)
                            logging.info("VSF flag file removed.")
                        except OSError as e:
                            logging.error(f"Error removing VSF flag file: {e}")
                    logging.info("VSF refinement thread finished.")

            logging.info(f"Starting VSF refinement for {total_events} events...")
            thread = threading.Thread(target=vsf_worker)
            thread.daemon = True
            thread.start()
    else:
        logging.warning("VideoSubFinder CLI not found. Skipping refinement step.")
    
    return [], None, flag_file

def run_vsf_only_pipeline(video_path, output_image_folder, options, run_id, progress_callback=None, cancellation_event=None):
    start_time = time.time()
    if not os.path.exists(video_path):
        return None, "Video file not found.", None

    vsf_cli_filename = "videosubfinder-cli-cpu.exe"
    VSF_EXECUTABLE_PATH_CLI = resource_path(os.path.join("assets", "tools", "vsf-cli", vsf_cli_filename))

    if not os.path.exists(VSF_EXECUTABLE_PATH_CLI):
        logging.error(f"VSF CLI executable not found at '{VSF_EXECUTABLE_PATH_CLI}'.")
        return None, f"VSF CLI not found: {vsf_cli_filename}", None

    try:
        default_cfg_path = resource_path(os.path.join("assets", "tools", "vsf-cli", "Settings", "general.cfg"))
        with open(default_cfg_path, 'r', encoding='utf-8') as f:
            cfg_content = f.read()
        
        moderate_val = f"{options.get('moderate_threshold', 0.25):.2f}"
        cfg_content = re.sub(
            r"^(moderate_threshold\s*=\s*)\S+", 
            lambda m: m.group(1) + moderate_val, 
            cfg_content, 
            flags=re.MULTILINE
        )

        moderate_scaled_val = f"{options.get('moderate_threshold_scaled', 0.25):.2f}"
        cfg_content = re.sub(
            r"^(moderate_threshold_for_scaled_image\s*=\s*)\S+", 
            lambda m: m.group(1) + moderate_scaled_val, 
            cfg_content, 
            flags=re.MULTILINE
        )

        image_scale_val = f"{options.get('image_scale', 4)}"
        cfg_content = re.sub(
            r"^(image_scale_for_clear_image\s*=\s*)\S+", 
            lambda m: m.group(1) + image_scale_val, 
            cfg_content, 
            flags=re.MULTILINE
        )

        min_sum_color_diff_val = f"{options.get('min_sum_color_diff', 300)}"
        cfg_content = re.sub(
            r"^(min_sum_color_diff\s*=\s*)\S+",
            lambda m: m.group(1) + min_sum_color_diff_val,
            cfg_content,
            flags=re.MULTILINE
        )

        vedges_points_line_error_val = f"{options.get('vedges_points_line_error', 0.3):.2f}"
        cfg_content = re.sub(
            r"^(vedges_points_line_error\s*=\s*)\S+",
            lambda m: m.group(1) + vedges_points_line_error_val,
            cfg_content,
            flags=re.MULTILINE
        )
        
        safe_output_path = APP_TEMP_PATH.replace('\\', '/')
        lines = cfg_content.split('\n')
        for i, line in enumerate(lines):
            if line.strip().startswith("output_path"):
                lines[i] = f"output_path = {safe_output_path}"
                break
        cfg_content = '\n'.join(lines)

        temp_cfg_path = os.path.join(APP_TEMP_PATH, f"temp_vsf_settings_{uuid.uuid4()}.cfg")
        with open(temp_cfg_path, 'w', encoding='utf-8') as f:
            f.write(cfg_content)
        # Removed: logging.info(f"Temporary VSF config created at: '{os.path.basename(temp_cfg_path)}'")
    except Exception as e:
        logging.error(f"Failed to create temporary VSF config file: {e}", exc_info=True)
        return None, f"Failed to create temporary VSF config file: {e}", None

    scan_jobs = []
    if options.get("scan_top", False):
        scan_jobs.append("top")
    if options.get("scan_bottom", True):
        scan_jobs.append("bottom")

    if not scan_jobs:
        return [], "No scan area selected (top/bottom).", None

    flag_file = os.path.join(APP_TEMP_PATH, f"vsf_running_{uuid.uuid4()}.flag")
    with open(flag_file, "w") as f: f.write("running")

    def vsf_worker():
        creationflags = 0
        if os.name == 'nt':
            creationflags = subprocess.CREATE_NO_WINDOW
        
        try:
            total_jobs = len(scan_jobs)
            for i, job in enumerate(scan_jobs):
                if cancellation_event and cancellation_event.is_set():
                    logging.info("VSF-Only process cancelled by user.")
                    break
                
                initial_message = f"Running VSF-Only ({job}) [{i+1}/{total_jobs}]..."
                if progress_callback:
                    progress_callback(initial_message, -1)

                run_temp_dir = os.path.join(APP_TEMP_PATH, f"vsf_run_{run_id}_{job}_{uuid.uuid4().hex[:8]}")
                os.makedirs(run_temp_dir, exist_ok=True)

                exe_path_norm = VSF_EXECUTABLE_PATH_CLI.replace('/', '\\')
                vsf_dir_norm = os.path.dirname(exe_path_norm)
                video_path_norm = os.path.abspath(video_path).replace('/', '\\')
                output_dir_norm = os.path.abspath(run_temp_dir).replace('/', '\\')
                temp_cfg_path_norm = os.path.abspath(temp_cfg_path).replace('/', '\\')

                command_parts = [
                    exe_path_norm, '-c', '-r', '-ovocv',
                    '-i', video_path_norm,
                    '-o', output_dir_norm,
                    '-gs', temp_cfg_path_norm
                ]

                scan_area_height_percent = options.get("scan_area_height", 30) / 100.0
                if job == 'top':
                    be, te = 1.0 - scan_area_height_percent, 1.0
                else: # bottom
                    be, te = 0.0, scan_area_height_percent
                
                command_parts.extend(['-be', f'{be:.6f}', '-te', f'{te:.6f}'])

                # Removed: logging.info(f"Running VSF-Only command for '{job}'...")
                
                p = subprocess.Popen(
                    command_parts, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    text=True, 
                    encoding='utf-8',
                    errors='replace',
                    cwd=vsf_dir_norm, 
                    creationflags=creationflags
                )
                
                stdout, stderr = p.communicate()

                if cancellation_event and cancellation_event.is_set():
                    logging.info(f"VSF-Only process for '{job}' was cancelled.")
                    try:
                        p.terminate()
                    except OSError:
                        pass
                    break 

                if p.returncode != 0:
                    logging.error(f"VSF-Only process for '{job}' failed with return code {p.returncode}.")
                    if stderr:
                        logging.error(f"VSF-Only Stderr:\n{stderr}")
                if stdout:
                    last_lines = stdout.strip().split('\n')[-10:]
                    logging.debug(f"VSF-Only Stdout for '{job}' (last 10 lines):\n" + "\n".join(last_lines))

        finally:
            if os.path.exists(flag_file):
                try: os.remove(flag_file)
                except OSError as e: logging.error(f"Error removing VSF-Only flag file: {e}")
            if os.path.exists(temp_cfg_path):
                try: os.remove(temp_cfg_path)
                except OSError as e: logging.error(f"Error removing temp VSF config: {e}")
            logging.info(f"VSF-Only processing thread finished in {time.time() - start_time:.2f} seconds.")

    thread = threading.Thread(target=vsf_worker)
    thread.daemon = True
    thread.start()

    return [], None, flag_file
