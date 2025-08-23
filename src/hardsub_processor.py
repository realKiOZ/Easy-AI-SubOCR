# src/hardsub_processor.py
import cv2
import numpy as np
import os
import logging
from datetime import timedelta

EAST_MODEL_PATH = os.path.join("assets", "tools", "frozen_east_text_detection.pb")

def seconds_to_srt_time(seconds):
    """Chuyển đổi giây sang định dạng thời gian SRT."""
    if seconds < 0: seconds = 0
    td = timedelta(seconds=seconds)
    minutes, seconds = divmod(td.seconds, 60)
    hours, minutes = divmod(minutes, 60)
    milliseconds = td.microseconds // 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def smart_resize(image, target_size):
    """Thay đổi kích thước ảnh về kích thước mục tiêu mà không làm méo, thêm padding nếu cần."""
    h, w = image.shape[:2]
    target_w, target_h = target_size

    # Tính toán tỷ lệ resize và kích thước mới
    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    
    # Resize ảnh
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)

    # Tạo một ảnh nền và đặt ảnh đã resize vào giữa
    delta_w = target_w - new_w
    delta_h = target_h - new_h
    top, bottom = delta_h // 2, delta_h - (delta_h // 2)
    left, right = delta_w // 2, delta_w - (delta_w // 2)
    
    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=[0, 0, 0])
    return padded

def detect_text_with_east(frame_area, net, confidence, quality):
    """Sử dụng mô hình EAST để phát hiện sự hiện diện của văn bản trong một vùng ảnh."""
    if frame_area is None or frame_area.shape[0] < 32 or frame_area.shape[1] < 32:
        return False

    # Kích thước mới phải là bội số của 32
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
                return True # Tìm thấy văn bản có độ tin cậy đủ cao
    return False

def process_subtitle_channel(has_text, current_event, frame_time_sec, all_events, frame_idx):
    """Xử lý trạng thái cho một kênh phụ đề (trên hoặc dưới)."""
    if has_text:
        if current_event["start_time"] is None:
            # Bắt đầu một sự kiện mới
            current_event["start_time"] = frame_time_sec
            current_event["start_frame"] = frame_idx
        # Cập nhật thời gian kết thúc liên tục
        current_event["end_time"] = frame_time_sec
        current_event["end_frame"] = frame_idx
    elif current_event["start_time"] is not None:
        # Kết thúc sự kiện hiện tại, không còn kiểm tra thời gian tối thiểu
        all_events.append(current_event.copy())
        # Reset lại sự kiện
        current_event["start_time"] = None
        current_event["start_frame"] = None
        current_event["end_time"] = None
        current_event["end_frame"] = None

def run_hardsub_pipeline(video_path, output_image_folder, options, progress_callback=None, cancellation_event=None):
    if not os.path.exists(video_path): return None, "Video file not found."
    if not os.path.exists(EAST_MODEL_PATH): return None, "EAST text detection model not found."

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened(): return None, "Could not open video file."

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0: return None, "Could not determine video FPS."

    # Lấy các tùy chọn
    use_gpu = options.get("use_gpu", True)
    confidence = options.get("confidence", 0.5)
    quality = options.get("quality", 320)
    scan_area_height_percent = options.get("scan_area_height", 30) / 100.0

    logging.info("Loading EAST text detection model...")
    net = cv2.dnn.readNet(EAST_MODEL_PATH)
    
    if use_gpu:
        # Giả định rằng GUI đã kiểm tra và xác nhận CUDA có sẵn
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
        logging.info("EAST model is set to run on GPU (CUDA).")
    else:
        logging.info("EAST model is set to run on CPU.")

    subtitles = []
    sub_count = 0
    
    top_event = {"start_time": None, "end_time": None, "start_frame": None, "end_frame": None}
    bottom_event = {"start_time": None, "end_time": None, "start_frame": None, "end_frame": None}
    
    all_top_events = []
    all_bottom_events = []

    frame_idx = 0
    logging.info("Starting hardsub pipeline (EAST detection)...")

    while cap.isOpened():
        if cancellation_event and cancellation_event.is_set():
            logging.info("Hardsub pipeline cancelled by user.")
            break
            
        ret, frame = cap.read()
        if not ret: break

        frame_time_sec = frame_idx / fps
        
        if progress_callback and frame_idx % int(fps) == 0:
            percentage = (frame_idx / total_frames) * 100
            progress_callback(f"Scanning video: {seconds_to_srt_time(frame_time_sec)}", percentage)

        height, _, _ = frame.shape
        scan_area_height = int(height * scan_area_height_percent)

        scan_top = options.get("scan_top", True)
        scan_bottom = options.get("scan_bottom", True)

        if scan_bottom:
            bottom_area = frame[height - scan_area_height:height, :]
            has_bottom_text = detect_text_with_east(bottom_area, net, confidence, quality)
            process_subtitle_channel(has_bottom_text, bottom_event, frame_time_sec, all_bottom_events, frame_idx)

        if scan_top:
            top_area = frame[0:scan_area_height, :]
            has_top_text = detect_text_with_east(top_area, net, confidence, quality)
            process_subtitle_channel(has_top_text, top_event, frame_time_sec, all_top_events, frame_idx)
        
        frame_idx += 1

    # Xử lý các sự kiện cuối cùng nếu video kết thúc mà chúng chưa được đóng
    if top_event["start_time"] is not None: all_top_events.append(top_event)
    if bottom_event["start_time"] is not None: all_bottom_events.append(bottom_event)

    cap.release()

    # Giai đoạn 2: Trích xuất ảnh đại diện từ các sự kiện đã được xác định
    logging.info(f"Found {len(all_top_events)} top events and {len(all_bottom_events)} bottom events.")
    logging.info("Extracting representative images...")

    all_events = [("top", event) for event in all_top_events] + [("bottom", event) for event in all_bottom_events]
    
    cap = cv2.VideoCapture(video_path) # Mở lại video để đọc frame

    for channel, event in all_events:
        middle_frame_idx = (event["start_frame"] + event["end_frame"]) // 2
        cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame_idx)
        ret, frame = cap.read()
        
        if ret:
            height, _, _ = frame.shape
            scan_area_height = int(height * scan_area_height_percent)
            
            if channel == "top":
                crop_img = frame[0:scan_area_height, :]
            else: # bottom
                crop_img = frame[height - scan_area_height:height, :]

            sub_count += 1
            image_filename = f"hardsub_{sub_count:05d}.png"
            cv2.imwrite(os.path.join(output_image_folder, image_filename), crop_img)
            
            subtitles.append({
                "start_srt": seconds_to_srt_time(event["start_time"]),
                "end_srt": seconds_to_srt_time(event["end_time"]),
                "image_file": image_filename,
                "channel": channel # Thêm thông tin kênh
            })

    cap.release()
    logging.info(f"Hardsub pipeline finished. Extracted {len(subtitles)} potential subtitles.")
    return subtitles, None
