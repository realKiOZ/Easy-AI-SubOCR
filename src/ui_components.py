# src/ui_components.py

import tkinter as tk
from tkinter import ttk
from src.localization import EN_TRANSLATIONS

class SubtitleSelectionDialog(tk.Toplevel):
    def __init__(self, parent, streams):
        super().__init__(parent)
        self.title(EN_TRANSLATIONS["select_subtitle_stream_dialog_title"])
        self.geometry("400x300")
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
        ok_button = ttk.Button(self, text=EN_TRANSLATIONS["ok_button"], command=self.on_ok)
        ok_button.pack(pady=10)
    def on_ok(self):
        selection = self.listbox.curselection()
        if selection: self.selected_stream_index = selection[0]
        self.destroy()

class SessionSelectionDialog(tk.Toplevel):
    def __init__(self, parent, sessions):
        super().__init__(parent)
        self.title(EN_TRANSLATIONS["select_session_dialog_title"])
        self.geometry("500x400")
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
        ok_button = ttk.Button(self, text=EN_TRANSLATIONS["ok_button"], command=self.on_ok)
        ok_button.pack(pady=10)
    def on_ok(self):
        selection = self.listbox.curselection()
        if selection:
            self.selected_session = self.listbox.get(selection[0])
        self.destroy()
