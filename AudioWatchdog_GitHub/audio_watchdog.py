import time
import asyncio
import threading
import json
import os
import ctypes
from PIL import Image, ImageDraw
import pystray
import customtkinter as ctk
from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager

# Constants & Defaults
AUDIO_THRESHOLD = 0.01 
SILENCE_GRACE_PERIOD = 1.0  # Seconds of silence required before resuming music
DEFAULT_DUCKING_VOLUME = 0.50 

IGNORED_PROCESSES = [
    "audiodg.exe", "system", "idle", 
    "rainmeter.exe", "wallpaper32.exe", "wallpaper64.exe",
    "razerappengine.exe", "razerwdl.exe", "razer_elevation_service.exe",
    "rzappmanager.exe", "rzbtlemanager.exe", "rzchromaconnectmanager.exe",
    "rzchromaconnectserver.exe", "rzchromastreamserver.exe", "rzdevicemanager.exe",
    "rzdevicemanagerex.exe", "rzdiagnosticservice.exe", "rzenginemon.exe",
    "rziotdevicemanager.exe", "rzsdkserver.exe", "rzsdkservice.exe",
    "rzsmartlightingdevicemanager.exe", "rzwdldevicemanager.exe",
    "obs64.exe"
]

# Settings Management
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

CONFIG = {
    "ducking_volume": DEFAULT_DUCKING_VOLUME,
    "main_source": "spotify.exe",
    "default_role": "duck",
    "app_roles": {
        "firefox.exe": "pause"
    }
}

def load_config():
    global CONFIG
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    CONFIG["ducking_volume"] = float(data.get("ducking_volume", DEFAULT_DUCKING_VOLUME))
                    CONFIG["main_source"] = data.get("main_source", "spotify.exe").lower()
                    CONFIG["default_role"] = data.get("default_role", "duck")
                    CONFIG["app_roles"] = data.get("app_roles", {"firefox.exe": "pause"})
        except Exception as e:
            print(f"Error loading config: {e}")

def save_config():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(CONFIG, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")

# Settings GUI
class SettingsWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Audio Watchdog Settings")
        self.geometry("500x600")
        self.resizable(False, False)
        
        # Center the window on screen
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")
        
        # Appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # Tabview
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.tab_general = self.tabview.add("General")
        self.tab_live = self.tabview.add("Live Streams")
        
        self.stream_widgets = {}
        
        self.build_general_tab()
        self.build_live_tab()
        
        # Start Live Stream refresh loop
        self.after(1000, self.refresh_live_streams)
        
    def build_general_tab(self):
        self.tab_general.grid_columnconfigure(0, weight=1)
        
        # Volume
        vol_frame = ctk.CTkFrame(self.tab_general)
        vol_frame.pack(fill="x", padx=10, pady=10)
        self.volume_label = ctk.CTkLabel(vol_frame, text=f"Ducking Volume: {int(CONFIG['ducking_volume']*100)}%", font=("Segoe UI", 14, "bold"))
        self.volume_label.pack(anchor="w", padx=10, pady=5)
        self.volume_slider = ctk.CTkSlider(vol_frame, from_=0.0, to=1.0, command=self.update_volume_label)
        self.volume_slider.set(CONFIG["ducking_volume"])
        self.volume_slider.pack(fill="x", padx=10, pady=5)
        
        # Main Source
        ms_frame = ctk.CTkFrame(self.tab_general)
        ms_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(ms_frame, text="Main Source App (e.g. spotify.exe):", font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=10, pady=5)
        self.ms_entry = ctk.CTkEntry(ms_frame)
        self.ms_entry.insert(0, CONFIG.get("main_source", "spotify.exe"))
        self.ms_entry.pack(fill="x", padx=10, pady=5)
        
        # Default Role
        dr_frame = ctk.CTkFrame(self.tab_general)
        dr_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(dr_frame, text="Default Role for Unclassified Apps:", font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=10, pady=5)
        self.dr_var = ctk.StringVar(value="Duck Trigger" if CONFIG.get("default_role") == "duck" else "Ignore")
        self.dr_dropdown = ctk.CTkOptionMenu(dr_frame, values=["Duck Trigger", "Ignore"], variable=self.dr_var)
        self.dr_dropdown.pack(anchor="w", padx=10, pady=5)
        
        # Save Button
        ctk.CTkButton(self.tab_general, text="Save Settings", command=self.save_general_settings, fg_color="#2ecc71", hover_color="#27ae60", font=("Segoe UI", 14, "bold")).pack(pady=20)

    def update_volume_label(self, val):
        self.volume_label.configure(text=f"Ducking Volume: {int(val*100)}%")
        
    def save_general_settings(self):
        CONFIG["ducking_volume"] = self.volume_slider.get()
        CONFIG["main_source"] = self.ms_entry.get().strip().lower()
        val = self.dr_var.get()
        CONFIG["default_role"] = "duck" if val == "Duck Trigger" else "ignore"
        save_config()
        self.refresh_dropdown_states()

    def build_live_tab(self):
        self.scrollable_frame = ctk.CTkScrollableFrame(self.tab_live)
        self.scrollable_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Header
        header = ctk.CTkFrame(self.scrollable_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(header, text="Application", width=140, anchor="w", font=("Segoe UI", 12, "bold")).pack(side="left", padx=5)
        ctk.CTkLabel(header, text="Activity", width=80, anchor="w", font=("Segoe UI", 12, "bold")).pack(side="left", padx=5)
        ctk.CTkLabel(header, text="Role Assignment", width=120, anchor="w", font=("Segoe UI", 12, "bold")).pack(side="right", padx=5)

    def refresh_live_streams(self):
        try:
            sessions = AudioUtilities.GetAllSessions()
            active_processes = set()
            
            for session in sessions:
                if session.Process:
                    proc_name = session.Process.name().lower()
                    active_processes.add(proc_name)
                    
                    meter = session._ctl.QueryInterface(IAudioMeterInformation)
                    peak = meter.GetPeakValue()
                    is_active = peak > AUDIO_THRESHOLD
                    
                    # Check if we have a widget for it
                    if proc_name not in self.stream_widgets:
                        self.create_stream_row(proc_name)
                    
                    # Update status
                    self.stream_widgets[proc_name]["status"].configure(
                        text="🔊 Playing" if is_active else "🔇 Silent",
                        text_color="#2ecc71" if is_active else "gray"
                    )
                    
            # Remove widgets for dead processes
            for proc in list(self.stream_widgets.keys()):
                if proc not in active_processes:
                    self.stream_widgets[proc]["frame"].destroy()
                    del self.stream_widgets[proc]
        except Exception:
            pass
            
        self.after(1000, self.refresh_live_streams)

    def create_stream_row(self, proc_name):
        row_frame = ctk.CTkFrame(self.scrollable_frame)
        row_frame.pack(fill="x", pady=2, padx=2)
        
        # Shorten name if too long
        display_name = proc_name if len(proc_name) <= 18 else proc_name[:15] + "..."
        lbl_name = ctk.CTkLabel(row_frame, text=display_name, width=140, anchor="w")
        lbl_name.pack(side="left", padx=5)
        
        lbl_status = ctk.CTkLabel(row_frame, text="🔇 Silent", width=80, anchor="w")
        lbl_status.pack(side="left", padx=5)
        
        current_role = self.determine_role(proc_name)
        role_var = ctk.StringVar(value=current_role)
        dropdown = ctk.CTkOptionMenu(
            row_frame, 
            values=["Main Source", "Pause Trigger", "Duck Trigger", "Ignore", "Default"],
            variable=role_var,
            width=120,
            command=lambda v, p=proc_name: self.on_role_change(p, v)
        )
        dropdown.pack(side="right", padx=5)
        
        self.stream_widgets[proc_name] = {
            "frame": row_frame,
            "status": lbl_status,
            "dropdown": dropdown
        }

    def determine_role(self, proc_name):
        if proc_name == CONFIG.get("main_source"):
            return "Main Source"
        elif proc_name in CONFIG.get("app_roles", {}):
            role = CONFIG["app_roles"][proc_name]
            if role == "pause": return "Pause Trigger"
            if role == "duck": return "Duck Trigger"
            if role == "ignore": return "Ignore"
        else:
            if proc_name in IGNORED_PROCESSES:
                return "Ignore"
        return "Default"

    def on_role_change(self, proc_name, new_role):
        if new_role == "Main Source":
            CONFIG["main_source"] = proc_name
            self.ms_entry.delete(0, 'end')
            self.ms_entry.insert(0, proc_name)
            if proc_name in CONFIG["app_roles"]:
                del CONFIG["app_roles"][proc_name]
        else:
            if new_role == "Pause Trigger":
                CONFIG["app_roles"][proc_name] = "pause"
            elif new_role == "Duck Trigger":
                CONFIG["app_roles"][proc_name] = "duck"
            elif new_role == "Ignore":
                CONFIG["app_roles"][proc_name] = "ignore"
            elif new_role == "Default":
                if proc_name in CONFIG["app_roles"]:
                    del CONFIG["app_roles"][proc_name]
        save_config()
        self.refresh_dropdown_states()

    def refresh_dropdown_states(self):
        for proc_name, widgets in self.stream_widgets.items():
            widgets["dropdown"].set(self.determine_role(proc_name))

# GUI Thread Safety Manager
settings_window = None
focus_requested = False

def open_settings_gui(icon=None, item=None):
    global settings_window, focus_requested
    
    if settings_window is not None:
        focus_requested = True
        return
        
    def thread_func():
        global settings_window, focus_requested
        app = SettingsWindow()
        settings_window = app
        
        def check_focus():
            global focus_requested
            if focus_requested:
                focus_requested = False
                app.deiconify()
                app.focus()
            app.after(200, check_focus)
            
        app.after(200, check_focus)
        
        def on_closing():
            global settings_window
            settings_window = None
            app.destroy()
            
        app.protocol("WM_DELETE_WINDOW", on_closing)
        app.mainloop()
        
    t = threading.Thread(target=thread_func, daemon=True)
    t.start()

# System Tray Management
running = True
tray_icon = None

def create_tray_image():
    # 32x32 size is standard for Windows High-DPI tray icons
    image = Image.new('RGBA', (32, 32), color=(0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    
    # Speaker body: rectangle [6, 11, 11, 21]
    dc.rectangle([6, 11, 11, 21], fill=(52, 152, 219, 255)) # Light Blue
    dc.polygon([(11, 11), (18, 5), (18, 27), (11, 21)], fill=(52, 152, 219, 255))
    
    # Wave arcs: white
    dc.arc([10, 10, 22, 22], start=-45, end=45, fill=(255, 255, 255, 255), width=2)
    dc.arc([4, 4, 28, 28], start=-45, end=45, fill=(255, 255, 255, 255), width=2)
    
    return image

def on_exit(icon, item):
    global running, settings_window
    running = False
    icon.stop()
    if settings_window is not None:
        try:
            settings_window.destroy()
        except Exception:
            pass

def run_tray():
    global tray_icon
    image = create_tray_image()
    menu = pystray.Menu(
        pystray.MenuItem("Settings", open_settings_gui),
        pystray.MenuItem("Exit", on_exit)
    )
    tray_icon = pystray.Icon("audio_watchdog", image, "Audio Ducking Watchdog", menu)
    
    # Explicitly set visibility to True in the setup function to ensure
    # Windows notification area refreshes and displays the icon correctly.
    def setup(icon):
        icon.visible = True
        
    tray_icon.run(setup=setup)

# Media Controls & Audio State Scan
async def list_smtc_sessions():
    try:
        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        sessions = manager.get_sessions()
        print("--- Windows Media Controls Scan ---")
        target_app = CONFIG.get("main_source", "spotify.exe").lower().replace(".exe", "")
        found_target = False
        for session in sessions:
            app_id = session.source_app_user_model_id
            if app_id:
                print(f" - Found Media App: {app_id}")
                if target_app in app_id.lower():
                    found_target = True
        
        if not found_target:
            print(f" ⚠️ WARNING: Windows cannot see {target_app}!")
        print("-----------------------------------")
    except Exception as e:
        print(f"SMTC scan error: {e}")

async def send_media_command(command="play"):
    try:
        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        sessions = manager.get_sessions()
        target_app = CONFIG.get("main_source", "spotify.exe").lower().replace(".exe", "")
        for session in sessions:
            app_id = session.source_app_user_model_id
            if app_id and target_app in app_id.lower():
                if command == "play":
                    await session.try_play_async()
                elif command == "pause":
                    await session.try_pause_async()
                print(f"  [>] Successfully sent '{command}' command to {target_app} via API.")
                return True
    except Exception as e:
        print(f"SMTC command error: {e}")
    return False

def get_audio_state():
    sessions = AudioUtilities.GetAllSessions()
    
    pause_active = False
    duck_active = False
    target_volume_ctrls = []
    target_is_playing = False
    
    main_source = CONFIG.get("main_source", "spotify.exe").lower()
    app_roles = CONFIG.get("app_roles", {})
    default_role = CONFIG.get("default_role", "duck")
    
    for session in sessions:
        if session.Process:
            proc_name = session.Process.name().lower()
            meter = session._ctl.QueryInterface(IAudioMeterInformation)
            is_playing = meter.GetPeakValue() > AUDIO_THRESHOLD
            
            if proc_name == main_source:
                target_volume_ctrls.append(session.SimpleAudioVolume)
                if is_playing:
                    target_is_playing = True
            else:
                role = "ignore"
                if proc_name in app_roles:
                    role = app_roles[proc_name]
                elif proc_name not in IGNORED_PROCESSES:
                    role = default_role
                
                if is_playing:
                    if role == "pause":
                        pause_active = True
                    elif role == "duck":
                        duck_active = True

    return pause_active, duck_active, target_volume_ctrls, target_is_playing

def watchdog_loop():
    # Initialize COM for this thread
    ctypes.windll.ole32.CoInitializeEx(None, 0)
    
    try:
        asyncio.run(list_smtc_sessions())
        
        was_playing_before_pause = False
        is_paused = False
        last_pause_audio_time = 0

        while running:
            try:
                pause_active, duck_active, target_volume_ctrls, target_is_playing = get_audio_state()

                # --- GRACE PERIOD LOGIC ---
                if pause_active:
                    last_pause_audio_time = time.time()
                    current_pause_state = True
                else:
                    time_since_audio = time.time() - last_pause_audio_time
                    current_pause_state = time_since_audio < SILENCE_GRACE_PERIOD

                # Apply volume and playback logic to ALL sessions of the main source
                if target_volume_ctrls:
                    if current_pause_state and not is_paused:
                        if target_is_playing:
                            was_playing_before_pause = True
                            target_app = CONFIG.get("main_source", "spotify.exe")
                            print(f"\nPause Trigger detected! Pausing {target_app}...")
                            asyncio.run(send_media_command("pause"))
                        is_paused = True

                    elif not current_pause_state and is_paused:
                        if was_playing_before_pause:
                            target_app = CONFIG.get("main_source", "spotify.exe")
                            print(f"\nPause Trigger silent. Resuming {target_app}...")
                            asyncio.run(send_media_command("play"))
                            was_playing_before_pause = False
                        is_paused = False

                    # Audio Ducking logic
                    if not current_pause_state:
                        if duck_active:
                            ducking_vol = CONFIG.get("ducking_volume", DEFAULT_DUCKING_VOLUME)
                            for ctrl in target_volume_ctrls:
                                ctrl.SetMasterVolume(ducking_vol, None)
                        else:
                            for ctrl in target_volume_ctrls:
                                ctrl.SetMasterVolume(1.0, None)

            except Exception:
                pass 

            time.sleep(0.5)
    finally:
        ctypes.windll.ole32.CoUninitialize()

def main():
    print("Starting Perfected Audio Watchdog with System Tray support...")
    load_config()
    
    # Start the watchdog loop in a background thread
    t_watchdog = threading.Thread(target=watchdog_loop, daemon=True)
    t_watchdog.start()
    
    # Run pystray on the main thread (blocking call)
    run_tray()

if __name__ == "__main__":
    main()