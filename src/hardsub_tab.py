# src/hardsub_tab.py
import tkinter as tk
from tkinter import ttk

def create_hardsub_tab(parent, gui_instance):
    """
    Tạo và điền nội dung cho tab Hardsub.
    """
    hardsub_frame = ttk.Frame(parent, padding=10)
    
    # Process Frame
    control_frame = ttk.LabelFrame(hardsub_frame, text="Hardsub Process", padding=10)
    control_frame.pack(fill=tk.X, expand=False, pady=(0, 10))
    
    btn_select_hardsub_video = ttk.Button(
        control_frame,
        text="1. Select Video for Hardsub OCR",
        command=gui_instance.select_hardsub_video
    )
    btn_select_hardsub_video.pack(fill=tk.X, pady=2)
    gui_instance.btn_select_hardsub_video = btn_select_hardsub_video
    
    # Hardsub-specific settings
    hardsub_settings_frame = ttk.LabelFrame(hardsub_frame, text="Hardsub Detection Settings", padding=10)
    hardsub_settings_frame.pack(fill=tk.X, expand=False, pady=(0, 10))
    hardsub_settings_frame.columnconfigure(1, weight=1)

    # Scan Areas
    gui_instance.hardsub_scan_top_var = tk.BooleanVar(value=True)
    gui_instance.hardsub_scan_bottom_var = tk.BooleanVar(value=True)
    top_check = ttk.Checkbutton(hardsub_settings_frame, text="Scan Top Area", variable=gui_instance.hardsub_scan_top_var, command=gui_instance.log_hardsub_settings)
    top_check.grid(row=0, column=0, sticky='w', pady=2)
    bottom_check = ttk.Checkbutton(hardsub_settings_frame, text="Scan Bottom Area", variable=gui_instance.hardsub_scan_bottom_var, command=gui_instance.log_hardsub_settings)
    bottom_check.grid(row=0, column=1, sticky='w', pady=2)

    # Scan Area Height
    ttk.Label(hardsub_settings_frame, text="Scan Area Height:").grid(row=1, column=0, sticky="w")
    scan_area_scale = ttk.Scale(hardsub_settings_frame, from_=10, to=50, variable=gui_instance.hardsub_scan_area_height_var, command=gui_instance.on_hardsub_settings_change)
    scan_area_scale.grid(row=1, column=1, sticky="ew", padx=5)
    scan_area_scale.bind("<ButtonRelease-1>", gui_instance.log_hardsub_settings)
    ttk.Label(hardsub_settings_frame, textvariable=gui_instance.hardsub_scan_area_height_display_var).grid(row=1, column=2)

    # GPU Acceleration
    gui_instance.hardsub_use_gpu_var = tk.BooleanVar(value=True)
    gui_instance.gpu_check = ttk.Checkbutton(hardsub_settings_frame, text="Use GPU Acceleration (NVIDIA CUDA)", variable=gui_instance.hardsub_use_gpu_var, command=gui_instance.log_hardsub_settings)
    gui_instance.gpu_check.grid(row=2, column=0, columnspan=3, sticky='w', pady=2)

    # Detection Confidence
    ttk.Label(hardsub_settings_frame, text="Detection Confidence:").grid(row=3, column=0, sticky="w")
    confidence_scale = ttk.Scale(hardsub_settings_frame, from_=0.1, to=0.9, variable=gui_instance.hardsub_confidence_var, command=gui_instance.on_hardsub_settings_change)
    confidence_scale.grid(row=3, column=1, sticky="ew", padx=5)
    confidence_scale.bind("<ButtonRelease-1>", gui_instance.log_hardsub_settings)
    ttk.Label(hardsub_settings_frame, textvariable=gui_instance.hardsub_confidence_display_var).grid(row=3, column=2)

    # Detection Quality
    ttk.Label(hardsub_settings_frame, text="Detection Quality:").grid(row=4, column=0, sticky="w", pady=2)
    quality_combobox = ttk.Combobox(hardsub_settings_frame, textvariable=gui_instance.hardsub_quality_var, state="readonly", width=10)
    quality_combobox['values'] = ['320px', '480px']
    quality_combobox.grid(row=4, column=1, columnspan=2, sticky="w", padx=5)
    quality_combobox.bind("<<ComboboxSelected>>", gui_instance.log_hardsub_settings)

    btn_detect_hardsub = ttk.Button(
        hardsub_settings_frame, # Moved to hardsub_settings_frame
        text="2. Detect Subtitles",
        command=gui_instance.start_hardsub_detection_thread
    )
    btn_detect_hardsub.grid(row=5, column=0, columnspan=3, sticky="ew", pady=5) # Placed below settings
    gui_instance.btn_detect_hardsub = btn_detect_hardsub

    return hardsub_frame
