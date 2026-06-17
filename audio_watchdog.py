import time
import asyncio
import threading
import json
import os
import sys
import ctypes
import winreg
from PIL import Image, ImageDraw
import pystray
import customtkinter as ctk
from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager

# Constants & Defaults
AUDIO_THRESHOLD = 0.01 

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

DEFAULT_PROFILE = {
    "main_source": "spotify.exe",
    "default_role": "duck",
    "grace_period": 1.0,
    "fade_speed": 0.5,
    "global_ducking_volume": 0.5,
    "individual_ducking": False,
    "app_roles": {"firefox.exe": "pause"},
    "app_duck_volumes": {}
}

CONFIG = {
    "run_on_startup": False,
    "current_profile": "Default",
    "profiles": {
        "Default": dict(DEFAULT_PROFILE)
    }
}

def get_profile():
    curr = CONFIG.get("current_profile", "Default")
    if curr not in CONFIG.get("profiles", {}):
        CONFIG["profiles"][curr] = dict(DEFAULT_PROFILE)
    return CONFIG["profiles"][curr]

def load_config():
    global CONFIG
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "profiles" not in data:
                        # Legacy Migration
                        CONFIG["run_on_startup"] = False
                        CONFIG["current_profile"] = "Default"
                        profile = dict(DEFAULT_PROFILE)
                        profile["global_ducking_volume"] = float(data.get("ducking_volume", 0.5))
                        profile["main_source"] = data.get("main_source", "spotify.exe").lower()
                        profile["default_role"] = data.get("default_role", "duck")
                        profile["app_roles"] = data.get("app_roles", {"firefox.exe": "pause"})
                        CONFIG["profiles"] = {"Default": profile}
                    else:
                        CONFIG.update(data)
                    get_profile()
        except Exception as e:
            print(f"Error loading config: {e}")

def save_config():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(CONFIG, f, indent=4)
        rebuild_tray_menu()
    except Exception as e:
        print(f"Error saving config: {e}")

def set_run_on_startup(enable):
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                executable_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
                if not getattr(sys, 'frozen', False):
                    executable_path = f'"{sys.executable}" "{executable_path}"'
                else:
                    executable_path = f'"{executable_path}"'
                winreg.SetValueEx(key, "AudioWatchdog", 0, winreg.REG_SZ, executable_path)
            else:
                try:
                    winreg.DeleteValue(key, "AudioWatchdog")
                except FileNotFoundError:
                    pass
    except Exception as e:
        print(f"Failed to toggle startup: {e}")

# Settings GUI
class SettingsWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Audio Watchdog Settings")
        self.geometry("650x780")
        self.resizable(False, False)
        
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")
        
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # Profile Header
        header = ctk.CTkFrame(self)
        header.pack(fill="x", padx=15, pady=15)
        
        ctk.CTkLabel(header, text="Profile:", font=("Segoe UI", 14, "bold")).pack(side="left", padx=10)
        self.prof_var = ctk.StringVar(value=CONFIG.get("current_profile", "Default"))
        self.prof_dropdown = ctk.CTkOptionMenu(header, values=list(CONFIG["profiles"].keys()), variable=self.prof_var, command=self.on_profile_change)
        self.prof_dropdown.pack(side="left", padx=10)
        
        ctk.CTkButton(header, text="New", width=60, command=self.new_profile).pack(side="left", padx=5)
        ctk.CTkButton(header, text="Delete", width=60, fg_color="#e74c3c", hover_color="#c0392b", command=self.del_profile).pack(side="left", padx=5)
        
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=15, pady=10)
        
        self.tab_general = self.tabview.add("General")
        self.tab_live = self.tabview.add("Live Streams")
        
        self.stream_widgets = {}
        
        self.build_general_tab()
        self.build_live_tab()
        self.refresh_all()
        
        self.after(1000, self.refresh_live_streams)

    def new_profile(self):
        dialog = ctk.CTkInputDialog(text="Enter new profile name:", title="New Profile")
        name = dialog.get_input()
        if name and name not in CONFIG["profiles"]:
            CONFIG["profiles"][name] = dict(DEFAULT_PROFILE)
            CONFIG["current_profile"] = name
            save_config()
            self.prof_dropdown.configure(values=list(CONFIG["profiles"].keys()))
            self.prof_var.set(name)
            self.refresh_all()

    def del_profile(self):
        name = self.prof_var.get()
        if name != "Default" and name in CONFIG["profiles"]:
            del CONFIG["profiles"][name]
            CONFIG["current_profile"] = "Default"
            save_config()
            self.prof_dropdown.configure(values=list(CONFIG["profiles"].keys()))
            self.prof_var.set("Default")
            self.refresh_all()

    def on_profile_change(self, name):
        CONFIG["current_profile"] = name
        save_config()
        self.refresh_all()

    def build_general_tab(self):
        self.tab_general.grid_columnconfigure(0, weight=1)
        
        # Startup Toggle
        self.startup_var = ctk.BooleanVar()
        ctk.CTkSwitch(self.tab_general, text="Run on Windows Startup", font=("Segoe UI", 12, "bold"), variable=self.startup_var, command=self.save_startup_setting).pack(anchor="w", padx=10, pady=10)
        
        # Main Source
        ms_frame = ctk.CTkFrame(self.tab_general)
        ms_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(ms_frame, text="Main Source App (e.g. spotify.exe):", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=5)
        self.ms_entry = ctk.CTkEntry(ms_frame)
        self.ms_entry.pack(fill="x", padx=10, pady=5)
        self.ms_entry.bind("<KeyRelease>", lambda e: self.save_general_settings())
        
        # Default Role
        dr_frame = ctk.CTkFrame(self.tab_general)
        dr_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(dr_frame, text="Default Role for Unclassified Apps:", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=5)
        self.dr_var = ctk.StringVar()
        self.dr_dropdown = ctk.CTkOptionMenu(dr_frame, values=["Duck Trigger", "Ignore"], variable=self.dr_var, command=self.save_general_settings)
        self.dr_dropdown.pack(anchor="w", padx=10, pady=5)
        
        # Grace Period
        gp_frame = ctk.CTkFrame(self.tab_general)
        gp_frame.pack(fill="x", padx=10, pady=5)
        self.gp_label = ctk.CTkLabel(gp_frame, text="Pause Grace Period:", font=("Segoe UI", 12, "bold"))
        self.gp_label.pack(anchor="w", padx=10, pady=5)
        self.gp_slider = ctk.CTkSlider(gp_frame, from_=0.0, to=10.0, number_of_steps=100, command=self.update_gp_label)
        self.gp_slider.pack(fill="x", padx=10, pady=5)
        
        # Fade Speed
        fs_frame = ctk.CTkFrame(self.tab_general)
        fs_frame.pack(fill="x", padx=10, pady=5)
        self.fs_label = ctk.CTkLabel(fs_frame, text="Volume Fade Speed:", font=("Segoe UI", 12, "bold"))
        self.fs_label.pack(anchor="w", padx=10, pady=5)
        self.fs_slider = ctk.CTkSlider(fs_frame, from_=0.0, to=1.0, command=self.update_fs_label)
        self.fs_slider.pack(fill="x", padx=10, pady=5)

        # Global Volume
        vol_frame = ctk.CTkFrame(self.tab_general)
        vol_frame.pack(fill="x", padx=10, pady=5)
        self.volume_label = ctk.CTkLabel(vol_frame, text="Global Ducking Volume:", font=("Segoe UI", 12, "bold"))
        self.volume_label.pack(anchor="w", padx=10, pady=5)
        self.volume_slider = ctk.CTkSlider(vol_frame, from_=0.0, to=1.0, command=self.update_volume_label)
        self.volume_slider.pack(fill="x", padx=10, pady=5)
        
        # Individual Ducking
        self.ind_duck_var = ctk.BooleanVar()
        ctk.CTkSwitch(self.tab_general, text="Enable Individual App Ducking Volumes", font=("Segoe UI", 12, "bold"), variable=self.ind_duck_var, command=self.save_general_settings).pack(anchor="w", padx=10, pady=10)

    def refresh_all(self):
        self.startup_var.set(CONFIG.get("run_on_startup", False))
        
        profile = get_profile()
        self.ms_entry.delete(0, 'end')
        self.ms_entry.insert(0, profile.get("main_source", "spotify.exe"))
        
        self.dr_var.set("Duck Trigger" if profile.get("default_role") == "duck" else "Ignore")
        
        gp = profile.get("grace_period", 1.0)
        self.gp_slider.set(gp)
        self.gp_label.configure(text=f"Pause Grace Period: {gp:.1f}s")
        
        fs = profile.get("fade_speed", 0.5)
        self.fs_slider.set(fs)
        self.update_fs_label(fs)
        
        vol = profile.get("global_ducking_volume", 0.5)
        self.volume_slider.set(vol)
        self.volume_label.configure(text=f"Global Ducking Volume: {int(vol*100)}%")
        
        self.ind_duck_var.set(profile.get("individual_ducking", False))
        
        self.refresh_dropdown_states()

    def update_gp_label(self, val):
        self.gp_label.configure(text=f"Pause Grace Period: {val:.1f}s")
        self.save_general_settings()

    def update_fs_label(self, val):
        speed = "Slow" if val < 0.3 else "Medium" if val < 0.7 else "Fast"
        if val > 0.95: speed = "Instant"
        self.fs_label.configure(text=f"Volume Fade Speed: {speed}")
        self.save_general_settings()

    def update_volume_label(self, val):
        self.volume_label.configure(text=f"Global Ducking Volume: {int(val*100)}%")
        self.save_general_settings()

    def save_startup_setting(self):
        CONFIG["run_on_startup"] = self.startup_var.get()
        set_run_on_startup(CONFIG["run_on_startup"])
        save_config()

    def save_general_settings(self, *args):
        profile = get_profile()
        profile["main_source"] = self.ms_entry.get().strip().lower()
        profile["default_role"] = "duck" if self.dr_var.get() == "Duck Trigger" else "ignore"
        profile["grace_period"] = float(self.gp_slider.get())
        profile["fade_speed"] = float(self.fs_slider.get())
        profile["global_ducking_volume"] = float(self.volume_slider.get())
        
        ind_was = profile.get("individual_ducking", False)
        ind_now = self.ind_duck_var.get()
        profile["individual_ducking"] = ind_now
        
        save_config()
        if ind_was != ind_now:
            self.refresh_dropdown_states()

    def build_live_tab(self):
        self.scrollable_frame = ctk.CTkScrollableFrame(self.tab_live)
        self.scrollable_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        header = ctk.CTkFrame(self.scrollable_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(header, text="App", width=120, anchor="w", font=("Segoe UI", 12, "bold")).pack(side="left", padx=5)
        ctk.CTkLabel(header, text="Activity", width=70, anchor="w", font=("Segoe UI", 12, "bold")).pack(side="left", padx=5)
        ctk.CTkLabel(header, text="Role", width=110, anchor="w", font=("Segoe UI", 12, "bold")).pack(side="left", padx=5)
        ctk.CTkLabel(header, text="Volume", width=100, anchor="center", font=("Segoe UI", 12, "bold")).pack(side="left", padx=25)

    def refresh_live_streams(self):
        try:
            sessions = AudioUtilities.GetAllSessions()
            active_processes = set()
            for session in sessions:
                if session.Process:
                    proc_name = session.Process.name().lower()
                    active_processes.add(proc_name)
                    
                    meter = session._ctl.QueryInterface(IAudioMeterInformation)
                    is_active = meter.GetPeakValue() > AUDIO_THRESHOLD
                    
                    if proc_name not in self.stream_widgets:
                        self.create_stream_row(proc_name)
                    
                    self.stream_widgets[proc_name]["status"].configure(
                        text="🔊 Playing" if is_active else "🔇 Silent",
                        text_color="#2ecc71" if is_active else "gray"
                    )
                    
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
        
        display_name = proc_name if len(proc_name) <= 15 else proc_name[:12] + "..."
        lbl_name = ctk.CTkLabel(row_frame, text=display_name, width=120, anchor="w")
        lbl_name.pack(side="left", padx=5)
        
        lbl_status = ctk.CTkLabel(row_frame, text="🔇 Silent", width=70, anchor="w")
        lbl_status.pack(side="left", padx=5)
        
        current_role = self.determine_role(proc_name)
        role_var = ctk.StringVar(value=current_role)
        dropdown = ctk.CTkOptionMenu(
            row_frame, 
            values=["Main Source", "Pause Trigger", "Duck Trigger", "Ignore", "Default"],
            variable=role_var,
            width=110,
            command=lambda v, p=proc_name: self.on_role_change(p, v)
        )
        dropdown.pack(side="left", padx=5)
        
        profile = get_profile()
        vol = profile.get("app_duck_volumes", {}).get(proc_name, profile.get("global_ducking_volume", 0.5))
        
        vol_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        vol_frame.pack(side="left", padx=5, fill="both", expand=True)
        
        vol_slider = ctk.CTkSlider(vol_frame, from_=0.0, to=1.0, width=100)
        vol_slider.set(vol)
        
        vol_lbl = ctk.CTkLabel(vol_frame, text=f"{int(vol*100)}%", width=40)
        
        def on_slide(v, p=proc_name, lbl=vol_lbl):
            lbl.configure(text=f"{int(v*100)}%")
            self.on_ind_vol_change(p, v)
            
        vol_slider.configure(command=on_slide)
        
        vol_slider.pack(side="left", padx=5)
        vol_lbl.pack(side="left")
        
        self.stream_widgets[proc_name] = {
            "frame": row_frame,
            "status": lbl_status,
            "dropdown": dropdown,
            "vol_frame": vol_frame,
            "slider": vol_slider,
            "vol_lbl": vol_lbl
        }
        self.update_row_visibility(proc_name)

    def determine_role(self, proc_name):
        profile = get_profile()
        if proc_name == profile.get("main_source"): return "Main Source"
        elif proc_name in profile.get("app_roles", {}):
            role = profile["app_roles"][proc_name]
            if role == "pause": return "Pause Trigger"
            if role == "duck": return "Duck Trigger"
            if role == "ignore": return "Ignore"
        else:
            if proc_name in IGNORED_PROCESSES: return "Ignore"
        return "Default"

    def on_role_change(self, proc_name, new_role):
        profile = get_profile()
        if new_role == "Main Source":
            profile["main_source"] = proc_name
            self.ms_entry.delete(0, 'end')
            self.ms_entry.insert(0, proc_name)
            if proc_name in profile.get("app_roles", {}):
                del profile["app_roles"][proc_name]
        else:
            if new_role == "Pause Trigger":
                profile.setdefault("app_roles", {})[proc_name] = "pause"
            elif new_role == "Duck Trigger":
                profile.setdefault("app_roles", {})[proc_name] = "duck"
            elif new_role == "Ignore":
                profile.setdefault("app_roles", {})[proc_name] = "ignore"
            elif new_role == "Default":
                if proc_name in profile.get("app_roles", {}):
                    del profile["app_roles"][proc_name]
        save_config()
        self.refresh_dropdown_states()

    def on_ind_vol_change(self, proc_name, val):
        profile = get_profile()
        profile.setdefault("app_duck_volumes", {})[proc_name] = float(val)
        save_config()

    def update_row_visibility(self, proc_name):
        if proc_name not in self.stream_widgets: return
        w = self.stream_widgets[proc_name]
        profile = get_profile()
        role = self.determine_role(proc_name)
        
        if profile.get("individual_ducking", False) and role == "Duck Trigger":
            w["vol_frame"].pack(side="left", padx=5, fill="both", expand=True)
            vol = profile.get("app_duck_volumes", {}).get(proc_name, profile.get("global_ducking_volume", 0.5))
            w["slider"].set(vol)
            w["vol_lbl"].configure(text=f"{int(vol*100)}%")
        else:
            w["vol_frame"].pack_forget()

    def refresh_dropdown_states(self):
        for proc_name, widgets in self.stream_widgets.items():
            widgets["dropdown"].set(self.determine_role(proc_name))
            self.update_row_visibility(proc_name)


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


running = True
tray_icon = None

def create_tray_image():
    image = Image.new('RGBA', (32, 32), color=(0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    dc.rectangle([6, 11, 11, 21], fill=(52, 152, 219, 255))
    dc.polygon([(11, 11), (18, 5), (18, 27), (11, 21)], fill=(52, 152, 219, 255))
    dc.arc([10, 10, 22, 22], start=-45, end=45, fill=(255, 255, 255, 255), width=2)
    dc.arc([4, 4, 28, 28], start=-45, end=45, fill=(255, 255, 255, 255), width=2)
    return image

def on_exit(icon, item):
    global running, settings_window
    running = False
    icon.stop()
    if settings_window is not None:
        try: settings_window.destroy()
        except Exception: pass

def rebuild_tray_menu():
    global tray_icon
    if not tray_icon: return
    
    profiles = list(CONFIG.get("profiles", {}).keys())
    
    def set_profile(icon, item):
        CONFIG["current_profile"] = item.text
        save_config()
        if settings_window:
            settings_window.refresh_all()

    def make_menu_item(prof_name):
        return pystray.MenuItem(
            prof_name,
            set_profile,
            radio=True,
            checked=lambda item: CONFIG.get("current_profile") == item.text
        )
        
    profile_items = [make_menu_item(p) for p in profiles]
    
    menu = pystray.Menu(
        pystray.MenuItem("Settings", open_settings_gui),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Profiles", pystray.Menu(*profile_items)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", on_exit)
    )
    tray_icon.menu = menu

def run_tray():
    global tray_icon
    image = create_tray_image()
    tray_icon = pystray.Icon("audio_watchdog", image, "Audio Ducking Watchdog")
    rebuild_tray_menu()
    
    def setup(icon):
        icon.visible = True
        
    tray_icon.run(setup=setup)


async def get_smtc_playing_apps():
    playing_apps = set()
    try:
        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        sessions = manager.get_sessions()
        for session in sessions:
            app_id = session.source_app_user_model_id
            if app_id:
                info = session.get_playback_info()
                if info and info.playback_status == 4: # PLAYING
                    playing_apps.add(app_id.lower())
    except Exception:
        pass
    return playing_apps

async def send_media_command(command, target_app_exe):
    try:
        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        sessions = manager.get_sessions()
        target_app = target_app_exe.lower().replace(".exe", "")
        for session in sessions:
            app_id = session.source_app_user_model_id
            if app_id and target_app in app_id.lower():
                if command == "play":
                    await session.try_play_async()
                elif command == "pause":
                    await session.try_pause_async()
                return True
    except Exception:
        pass
    return False

def get_audio_state(smtc_playing_apps):
    sessions = AudioUtilities.GetAllSessions()
    
    pause_active = False
    duck_active = False
    target_lowest_vol = 1.0
    target_volume_ctrls = []
    target_is_playing = False
    
    profile = get_profile()
    main_source = profile.get("main_source", "spotify.exe").lower()
    app_roles = profile.get("app_roles", {})
    default_role = profile.get("default_role", "duck")
    ind_ducking = profile.get("individual_ducking", False)
    app_vols = profile.get("app_duck_volumes", {})
    global_vol = profile.get("global_ducking_volume", 0.5)
    
    for session in sessions:
        if session.Process:
            proc_name = session.Process.name().lower()
            meter = session._ctl.QueryInterface(IAudioMeterInformation)
            
            is_playing = False
            proc_no_exe = proc_name.replace(".exe", "")
            for smtc_app in smtc_playing_apps:
                if proc_no_exe in smtc_app:
                    is_playing = True
                    break
            
            if not is_playing:
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
                        if ind_ducking:
                            vol = app_vols.get(proc_name, global_vol)
                            if vol < target_lowest_vol:
                                target_lowest_vol = vol
                        else:
                            target_lowest_vol = global_vol

    return pause_active, duck_active, target_lowest_vol, target_volume_ctrls, target_is_playing


def watchdog_loop():
    ctypes.windll.ole32.CoInitializeEx(None, 0)
    
    was_playing_before_pause = False
    is_paused = False
    last_pause_audio_time = 0
    current_volume = 1.0
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        while running:
            try:
                smtc_apps = loop.run_until_complete(get_smtc_playing_apps())
                pause_active, duck_active, target_duck_vol, target_volume_ctrls, target_is_playing = get_audio_state(smtc_apps)

                profile = get_profile()
                grace_period = profile.get("grace_period", 1.0)
                fade_speed = profile.get("fade_speed", 0.5)

                if pause_active:
                    last_pause_audio_time = time.time()
                    current_pause_state = True
                else:
                    time_since_audio = time.time() - last_pause_audio_time
                    current_pause_state = time_since_audio < grace_period

                if target_volume_ctrls:
                    if current_pause_state and not is_paused:
                        if target_is_playing:
                            was_playing_before_pause = True
                            loop.run_until_complete(send_media_command("pause", profile.get("main_source")))
                        is_paused = True

                    elif not current_pause_state and is_paused:
                        if was_playing_before_pause:
                            loop.run_until_complete(send_media_command("play", profile.get("main_source")))
                            was_playing_before_pause = False
                        is_paused = False

                    if not current_pause_state:
                        target_vol = target_duck_vol if duck_active else 1.0
                    else:
                        target_vol = 1.0 
                        
                    factor = 0.05 + (fade_speed * 0.95) 
                    
                    if abs(current_volume - target_vol) > 0.01:
                        current_volume += (target_vol - current_volume) * factor
                    else:
                        current_volume = target_vol
                        
                    for ctrl in target_volume_ctrls:
                        ctrl.SetMasterVolume(current_volume, None)

            except Exception:
                pass 
            time.sleep(0.1)
    finally:
        loop.close()
        ctypes.windll.ole32.CoUninitialize()


def main():
    print("Starting Perfected Audio Watchdog with Advanced Features...")
    load_config()
    set_run_on_startup(CONFIG.get("run_on_startup", False))
    
    t_watchdog = threading.Thread(target=watchdog_loop, daemon=True)
    t_watchdog.start()
    
    run_tray()

if __name__ == "__main__":
    main()