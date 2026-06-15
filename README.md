# Audio Watchdog

Audio Watchdog is a lightweight, dynamic Windows utility that automatically manages your audio streams in real-time. Whether you want to completely pause your music when watching a YouTube video, or just duck (lower) the volume when you receive a Discord notification, Audio Watchdog handles it automatically.

## Features
- **Dynamic Live Streams GUI:** View all currently active audio processes on your PC in real-time.
- **Customizable Roles:** Assign roles to your apps on the fly right from the system tray:
  - **Main Source:** The primary music or media app you want to control (e.g. Spotify, Chrome).
  - **Pause Trigger:** Apps that will completely pause your Main Source when they make sound.
  - **Duck Trigger:** Apps that will seamlessly lower the volume of your Main Source when they make sound.
  - **Ignore:** Apps whose audio is completely ignored.
- **Smart Grace Period:** Configurable silence grace period before resuming your music.
- **Multi-Session Support:** Reliably ducks volume even for apps like Chrome and Spotify that spawn multiple hidden audio sessions.

## Installation

### Using the Executable
1. Download `audio_watchdog.exe` from the [Releases](https://github.com/) page.
2. Double click to run it! It will run quietly in your system tray.
3. Right-click the system tray icon (blue speaker) and click "Settings" to assign your apps.

### Running from Source
1. Clone this repository.
2. Install the required dependencies: `pip install -r requirements.txt`
3. Run the script: `python audio_watchdog.py`

## Technologies Used
- Python 3
- `pycaw` (Python Core Audio Windows Library)
- `customtkinter` (Modern UI)
- `winrt` (Windows Runtime Media Controls)
- `pystray` (System Tray integration)
