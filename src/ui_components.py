# src/ui_components.py

import tkinter as tk
from tkinter import ttk

class SubtitleSelectionDialog(tk.Toplevel):
    def __init__(self, parent, streams):
        super().__init__(parent)
        self.title("Select Subtitle Stream")
        self.geometry("400x300")
        self._center_dialog(400, 300)
        self.transient(parent)
        self.grab_set()
        self.selected_stream_index = None
        label = ttk.Label(self, text="Found image subtitle streams:")
        label.pack(pady=10)
        self.listbox = tk.Listbox(self, selectmode=tk.SINGLE)
        for stream in streams:
            self.listbox.insert(tk.END, stream['info'])
        self.listbox.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)
        if streams: self.listbox.selection_set(0)

        button_frame = ttk.Frame(self)
        button_frame.pack(pady=10)

        ok_button = ttk.Button(button_frame, text="OK", command=self.on_ok)
        ok_button.pack(side=tk.LEFT, padx=5)

        cancel_button = ttk.Button(button_frame, text="Cancel", command=self.destroy)
        cancel_button.pack(side=tk.RIGHT, padx=5)

    def _center_dialog(self, width, height):
        self.update_idletasks()
        parent_x = self.master.winfo_x()
        parent_y = self.master.winfo_y()
        parent_width = self.master.winfo_width()
        parent_height = self.master.winfo_height()

        x = parent_x + (parent_width // 2) - (width // 2)
        y = parent_y + (parent_height // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')

    def on_ok(self):
        selection = self.listbox.curselection()
        if selection: self.selected_stream_index = selection[0]
        self.destroy()

class SessionSelectionDialog(tk.Toplevel):
    def __init__(self, parent, sessions):
        super().__init__(parent)
        self.title("Select Session to Reload")
        self.geometry("500x400")
        self._center_dialog(500, 400)
        self.transient(parent)
        self.grab_set()
        self.selected_session = None
        label = ttk.Label(self, text="Saved sessions:")
        label.pack(pady=10)
        self.listbox = tk.Listbox(self, selectmode=tk.SINGLE)
        for session in sessions:
            self.listbox.insert(tk.END, session)
        self.listbox.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)
        if sessions: self.listbox.selection_set(0)
        
        button_frame = ttk.Frame(self)
        button_frame.pack(pady=10)

        ok_button = ttk.Button(button_frame, text="OK", command=self.on_ok)
        ok_button.pack(side=tk.LEFT, padx=5)

        cancel_button = ttk.Button(button_frame, text="Cancel", command=self.destroy)
        cancel_button.pack(side=tk.RIGHT, padx=5)
        
    def on_ok(self):
        selection = self.listbox.curselection()
        if selection:
            self.selected_session = self.listbox.get(selection[0])
        self.destroy()

def create_ocr_controls(parent, gui_instance):
    """Tạo các control chung cho OCR (nút, status, progress bar)."""
    frame = ttk.Frame(parent)
    
    btn_start_ocr = ttk.Button(frame, text="2. Start OCR", command=gui_instance.start_ocr_thread)
    btn_start_ocr.pack(fill=tk.X, pady=2)
    gui_instance.btn_start_ocr = btn_start_ocr

    btn_cancel_ocr = ttk.Button(frame, text="Cancel", command=gui_instance.cancel_ocr)
    btn_cancel_ocr.pack(fill=tk.X, pady=2)
    gui_instance.btn_cancel_ocr = btn_cancel_ocr

    btn_retry_failed = ttk.Button(frame, text="Retry Failed Batches", command=gui_instance.retry_failed_batches)
    btn_retry_failed.pack(fill=tk.X, pady=2)
    gui_instance.btn_retry_failed = btn_retry_failed

    status_frame = ttk.Frame(frame, height=40)
    status_frame.pack(fill=tk.X, pady=5)
    status_frame.pack_propagate(False)
    
    status_label = ttk.Label(status_frame, text="...", wraplength=300, justify=tk.LEFT)
    status_label.pack(fill=tk.BOTH, expand=True)
    gui_instance.status_label = status_label

    progress_bar = ttk.Progressbar(frame, mode='determinate')
    progress_bar.pack(fill=tk.X)
    gui_instance.progress_bar = progress_bar

    return frame

def create_advanced_settings(parent, gui_instance):
    """Tạo frame Cài đặt Nâng cao."""
    adv_frame = ttk.LabelFrame(parent, text="Advanced Settings", padding=10)
    adv_frame.columnconfigure(1, weight=1)
    
    # Batch Size
    ttk.Label(adv_frame, text="Batch Size:").grid(row=0, column=0, sticky="w", pady=2)
    ttk.Spinbox(adv_frame, from_=1, to=500, textvariable=gui_instance.batch_size_var, command=gui_instance.save_advanced_settings, wrap=True, width=5).grid(row=0, column=1, columnspan=2, sticky="ew", padx=5, pady=(5,0))
    
    # Temperature
    ttk.Label(adv_frame, text="Temperature:").grid(row=1, column=0, sticky="w")
    ttk.Scale(adv_frame, from_=0.0, to=1.0, variable=gui_instance.temp_var, command=gui_instance.on_scale_change).grid(row=1, column=1, sticky="ew", padx=5)
    ttk.Label(adv_frame, textvariable=gui_instance.temp_display_var, width=4).grid(row=1, column=2)
    
    # OCR Language
    ttk.Label(adv_frame, text="OCR Language:").grid(row=2, column=0, sticky="w", pady=(5,0))
    ocr_lang_combobox = ttk.Combobox(adv_frame, textvariable=gui_instance.ocr_lang_var)
    ocr_lang_combobox['values'] = ['Auto', 'Vietnamese', 'English', 'Japanese', 'Chinese', 'Korean', 'French', 'German', 'Spanish', 'Italian', 'Russian', 'Portuguese', 'Dutch', 'Polish', 'Turkish', 'Arabic', 'Hindi', 'Thai', 'Indonesian', 'Malay', 'Filipino']
    ocr_lang_combobox.grid(row=2, column=1, columnspan=2, sticky="ew", padx=5, pady=(5,0))
    ocr_lang_combobox.bind("<<ComboboxSelected>>", gui_instance.save_advanced_settings)
    ocr_lang_combobox.bind("<FocusOut>", gui_instance.save_advanced_settings)
    
    return adv_frame
