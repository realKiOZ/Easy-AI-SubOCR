# src/ui_components.py

import tkinter as tk
from tkinter import ttk
from src.localization import EN_TRANSLATIONS

class SubtitleSelectionDialog(tk.Toplevel):
    def __init__(self, parent, streams):
        super().__init__(parent)
        self.title(EN_TRANSLATIONS["select_subtitle_stream_dialog_title"])
        self.geometry("400x300")
        self._center_dialog(400, 300)
        self.transient(parent)
        self.grab_set()
        self.selected_stream_index = None
        label = ttk.Label(self, text=EN_TRANSLATIONS["found_subtitle_streams_label"])
        label.pack(pady=10)
        self.listbox = tk.Listbox(self, selectmode=tk.SINGLE)
        for stream in streams:
            self.listbox.insert(tk.END, stream['info'])
        self.listbox.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)
        if streams: self.listbox.selection_set(0)

        button_frame = ttk.Frame(self)
        button_frame.pack(pady=10)

        ok_button = ttk.Button(button_frame, text=EN_TRANSLATIONS["ok_button"], command=self.on_ok)
        ok_button.pack(side=tk.LEFT, padx=5)

        cancel_button = ttk.Button(button_frame, text=EN_TRANSLATIONS["cancel_button"], command=self.destroy)
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
        self.title(EN_TRANSLATIONS["select_session_dialog_title"])
        self.geometry("500x400")
        self._center_dialog(500, 400)
        self.transient(parent)
        self.grab_set()
        self.selected_session = None
        label = ttk.Label(self, text=EN_TRANSLATIONS["saved_sessions_label"])
        label.pack(pady=10)
        self.listbox = tk.Listbox(self, selectmode=tk.SINGLE)
        for session in sessions:
            self.listbox.insert(tk.END, session)
        self.listbox.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)
        if sessions: self.listbox.selection_set(0)
        
        button_frame = ttk.Frame(self)
        button_frame.pack(pady=10)

        ok_button = ttk.Button(button_frame, text=EN_TRANSLATIONS["ok_button"], command=self.on_ok)
        ok_button.pack(side=tk.LEFT, padx=5)

        cancel_button = ttk.Button(button_frame, text=EN_TRANSLATIONS["cancel_button"], command=self.destroy)
        cancel_button.pack(side=tk.RIGHT, padx=5)
        
    def on_ok(self):
        selection = self.listbox.curselection()
        if selection:
            self.selected_session = self.listbox.get(selection[0])
        self.destroy()
