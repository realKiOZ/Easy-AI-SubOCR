# src/vsf_settings_component.py
import tkinter as tk
from tkinter import ttk

def create_vsf_advanced_settings_frame(parent, gui_instance):
    """Creates and returns a frame for VSF advanced .cfg settings."""
    vsf_adv_frame = ttk.LabelFrame(parent, text="VSF Advanced Settings", padding=10)
    vsf_adv_frame.columnconfigure(1, weight=1)

    # --- Moderate Threshold ---
    ttk.Label(vsf_adv_frame, text="Moderate Threshold:").grid(row=0, column=0, sticky="w", pady=2)
    moderate_thresh_scale = ttk.Scale(
        vsf_adv_frame, 
        from_=0.01, 
        to=1.0, 
        variable=gui_instance.vsf_moderate_threshold_var, 
        command=lambda e: gui_instance.vsf_moderate_threshold_display_var.set(f"{gui_instance.vsf_moderate_threshold_var.get():.2f}")
    )
    moderate_thresh_scale.grid(row=0, column=1, sticky="ew", padx=5)
    moderate_thresh_scale.bind("<ButtonRelease-1>", gui_instance.log_vsf_settings)
    ttk.Label(vsf_adv_frame, textvariable=gui_instance.vsf_moderate_threshold_display_var, width=4).grid(row=0, column=2)

    # --- Moderate Threshold for Scaled ---
    ttk.Label(vsf_adv_frame, text="Moderate Threshold (Scaled):").grid(row=1, column=0, sticky="w", pady=2)
    moderate_thresh_scaled_scale = ttk.Scale(
        vsf_adv_frame, 
        from_=0.01, 
        to=1.0, 
        variable=gui_instance.vsf_moderate_threshold_scaled_var,
        command=lambda e: gui_instance.vsf_moderate_threshold_scaled_display_var.set(f"{gui_instance.vsf_moderate_threshold_scaled_var.get():.2f}")
    )
    moderate_thresh_scaled_scale.grid(row=1, column=1, sticky="ew", padx=5)
    moderate_thresh_scaled_scale.bind("<ButtonRelease-1>", gui_instance.log_vsf_settings)
    ttk.Label(vsf_adv_frame, textvariable=gui_instance.vsf_moderate_threshold_scaled_display_var, width=4).grid(row=1, column=2)

    # --- Image Scale ---
    ttk.Label(vsf_adv_frame, text="Image Scale:").grid(row=2, column=0, sticky="w", pady=2)
    image_scale_scale = ttk.Scale(
        vsf_adv_frame, 
        from_=1, 
        to=10, 
        variable=gui_instance.vsf_image_scale_var,
        command=lambda e: gui_instance.vsf_image_scale_display_var.set(f"{gui_instance.vsf_image_scale_var.get():.0f}")
    )
    image_scale_scale.grid(row=2, column=1, sticky="ew", padx=5)
    image_scale_scale.bind("<ButtonRelease-1>", gui_instance.log_vsf_settings)
    ttk.Label(vsf_adv_frame, textvariable=gui_instance.vsf_image_scale_display_var, width=2).grid(row=2, column=2)

    return vsf_adv_frame