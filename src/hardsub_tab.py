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
    top_check = ttk.Checkbutton(hardsub_settings_frame, text="Scan Top Area", variable=gui_instance.hardsub_scan_top_var)
    top_check.grid(row=0, column=0, sticky='w', pady=2)
    bottom_check = ttk.Checkbutton(hardsub_settings_frame, text="Scan Bottom Area", variable=gui_instance.hardsub_scan_bottom_var)
    bottom_check.grid(row=0, column=1, sticky='w', pady=2)

    # Scan Area Height
    ttk.Label(hardsub_settings_frame, text="Scan Area Height:").grid(row=1, column=0, sticky="w")
    ttk.Scale(hardsub_settings_frame, from_=10, to=50, variable=gui_instance.hardsub_scan_area_height_var, command=gui_instance.on_hardsub_settings_change).grid(row=1, column=1, sticky="ew", padx=5)
    ttk.Label(hardsub_settings_frame, textvariable=gui_instance.hardsub_scan_area_height_display_var).grid(row=1, column=2)

    # GPU Acceleration
    gui_instance.hardsub_use_gpu_var = tk.BooleanVar(value=True)
    gui_instance.gpu_check = ttk.Checkbutton(hardsub_settings_frame, text="Use GPU Acceleration (NVIDIA CUDA)", variable=gui_instance.hardsub_use_gpu_var)
    gui_instance.gpu_check.grid(row=2, column=0, columnspan=3, sticky='w', pady=2)

    # Detection Confidence
    ttk.Label(hardsub_settings_frame, text="Detection Confidence:").grid(row=3, column=0, sticky="w")
    ttk.Scale(hardsub_settings_frame, from_=0.1, to=0.9, variable=gui_instance.hardsub_confidence_var, command=gui_instance.on_hardsub_settings_change).grid(row=3, column=1, sticky="ew", padx=5)
    ttk.Label(hardsub_settings_frame, textvariable=gui_instance.hardsub_confidence_display_var).grid(row=3, column=2)

    # Detection Quality
    ttk.Label(hardsub_settings_frame, text="Detection Quality:").grid(row=4, column=0, sticky="w", pady=2)
    quality_combobox = ttk.Combobox(hardsub_settings_frame, textvariable=gui_instance.hardsub_quality_var, state="readonly", width=10)
    quality_combobox['values'] = ['Fast (320px)', 'Balanced (480px)', 'Accurate (640px)']
    quality_combobox.grid(row=4, column=1, columnspan=2, sticky="w", padx=5)
    
    return hardsub_frame
