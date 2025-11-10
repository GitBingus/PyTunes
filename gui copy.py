import customtkinter as ctk
import getUserData as gud
import os
import threading
import time
import logging as lg
from pathlib import Path
import shutil
import sys
import uuid
import io
from tkinter import Menu, filedialog
import importlib
import pygame
PygameAvailable = True

from tinytag import TinyTag as tt

NAME = 'PyTunes'
__version__ = '1.0b3d2'


"""
Naming convention for __version__:
    if build is stable:
        x.+1 where x is the previous stable version max = 15

        STABLE BUILD BETA AND DEV NUMBERS MUST BE 0 TO BE STABLE i.e v2.0, -v1.1b0d0 (not ideal), v1.1 is better-

        eg. new stable release from 1.5 will be 1.6
            new stable release from 1.1b5 will be 1.2.0 -- beta build count reset upon new stable build
            new stable release from 1.1b2d7 will be 1.2.0 -- dev build count reset


    if build is beta:
        x.ybz where x.y is the previous beta or stable build max = 25
        
        eg. new beta release from 1.5b5 will 1.5b6
            new beta release from 1.0b25 will be 1.1b1 -- beta marker overflows at 25, adding 1 to minor release number
            new beta release from 1.9b25 will be 2.0b1

    
    if build is dev:
        x.ybxdx where x.y is major and minor, bx is beta and dx is dev max = 25

        eg. new dev release from 1.0b1d1 will be 1.0b1d2
            new dev release from 1.5b25d25 will be 1.6
            new beta build from 2.0b10d5 will be 2.0b11d0 -- dev counter resets when an upper-heirarchical release occurs

"""

__requirements__ = [
    'customtkinter',
    'logging',
    'tkinter',
    'pygame',
    'tinytag',
    'mutagen',
]

l = lg.getLogger('PyTunes')
lg.basicConfig(level=lg.DEBUG)

streamHandler = lg.StreamHandler()
streamHandler.setLevel(l.level)
streamHandler.setFormatter(lg.Formatter("%(asctime)s - %(levelname)s - %(name)s - Line %(lineno)s - %(message)s"))

l.addHandler(streamHandler)

def safe_import_pil():
    """Retry-import Pillow if it fails the first time (e.g., venv race condition)."""
    for attempt in range(2):
        try:
            from PIL import Image, ImageOps, ImageTk

            return True
        except Exception as e:
            l.warning(f"PIL import failed (attempt {attempt+1}): {e}")
            time.sleep(0.5)
            importlib.invalidate_caches()

    return False


try:
    # only import lightweight PIL pieces to test availability
    if not safe_import_pil():
        PIL_AVAILABLE = False
        l.warning("⚠️ Pillow still unavailable — continuing without album art.")

    else:
        from PIL import Image, ImageOps, ImageTk

        PIL_AVAILABLE = True
        l.debug("Pillow is available.")

except Exception as e:
    PIL_AVAILABLE = False
    l.warning("Pillow not available; album art disabled. (%s)", e)

# Mutagen is optional; try to import
try:
    from mutagen import File as MutagenFile  # type: ignore

except Exception:
    l.warning("Mutagen not available; album art disabled. (%s)")
    MutagenFile = None


global skeleton
skeleton = {}


def get_local_image_dir() -> Path:
    """
    Return the local 'Images' folder beside gui.py.
    Creates it if missing.
    """
    base_dir = Path(__file__).resolve().parent
    img_dir = base_dir / "Images"
    img_dir.mkdir(exist_ok=True)
    return img_dir


class TickingFrame(ctk.CTkFrame):
    def refresh_tick(self):
        pass



class AudioBackend:
    """Threaded pygame audio backend."""
    def __init__(self):
        if not PygameAvailable:
            raise RuntimeError("pygame is required for playback. pip install pygame")
        
        pygame.mixer.init()
        
        self._current_path = None
        self._is_playing = False
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._stop_poll = threading.Event()
        self.position_callback = None
        self._poll_thread.start()

    def is_playing(self) -> bool:
        return bool(self._is_playing)

    def load(self, path):
        self._current_path = path
        pygame.mixer.music.load(path)

    def play(self):
        if not self._current_path:
            return
        pygame.mixer.music.play()
        self._is_playing = True

    def pause(self):
        pygame.mixer.music.pause()
        self._is_playing = False

    def unpause(self):
        pygame.mixer.music.unpause()
        self._is_playing = True

    def stop(self):
        pygame.mixer.music.stop()
        self._is_playing = False

    def set_volume(self, vol):
        pygame.mixer.music.set_volume(max(0.0, min(1.0, vol)))

    def get_pos_seconds(self):
        pos = pygame.mixer.music.get_pos()
        return max(0.0, pos/1000.0)

    def _poll_loop(self):
        while not self._stop_poll.is_set():
            if self._is_playing and self.position_callback:
                self.position_callback(self.get_pos_seconds())
            time.sleep(0.1)

    def close(self):
        self._stop_poll.set()
        pygame.mixer.quit()


def getAudioData(file):
    return tt.get(file)


def load_album_art(path: str, size: int = 96):
    """
    Return a CTkImage for the embedded cover art or a fallback image.
    Works across Pillow versions (safe Resampling fallback).
    """
    if not PIL_AVAILABLE:
        return None
    
    try:
        from customtkinter import CTkImage  # local import to avoid top-level CTkImage import

    except Exception as e:
        l.error("CTkImage import failed even though Pillow exists: %s", e)
        return None

    img = None

    try:
        audio = MutagenFile(path) # pyright: ignore[reportOptionalCall, reportPossiblyUnboundVariable]
        if audio:
            # MP3 ID3 APIC
            try:
                if hasattr(audio, "tags") and hasattr(audio.tags, "getall"):
                    apics = audio.tags.getall("APIC")
                    if apics:
                        art = apics[0].data
                        img = Image.open(io.BytesIO(art)).convert("RGBA") # pyright: ignore[reportOptionalMemberAccess, reportOptionalCall, reportPossiblyUnboundVariable]
            except Exception:
                img = img or None

            # MP4 / M4A covr
            if img is None:
                try:
                    if hasattr(audio, "tags") and audio.tags:
                        covr = audio.tags.get("covr")
                        if covr:
                            # covr entry may be MP4Cover or bytes
                            art = covr[0]
                            if hasattr(art, "data"):
                                art = art.data
                            img = Image.open(io.BytesIO(art)).convert("RGBA") # pyright: ignore[reportOptionalMemberAccess, reportPossiblyUnboundVariable]
                except Exception:
                    img = img or None

            # FLAC pictures
            if img is None:
                try:
                    pics = getattr(audio, "pictures", None)
                    if pics:
                        art = pics[0].data
                        img = Image.open(io.BytesIO(art)).convert("RGBA") # pyright: ignore[reportOptionalMemberAccess, reportPossiblyUnboundVariable]
                except Exception:
                    img = img or None
    except Exception:
        img = None

    # Fallback to cover.jpg/folder.jpg next to the file
    if img is None and path:
        try:
            parent = Path(path).parent
            for name in ("cover.jpg", "folder.jpg", "cover.png", "folder.png"):
                candidate = parent / name
                if candidate.exists():
                    img = Image.open(candidate).convert("RGBA") # pyright: ignore[reportOptionalMemberAccess, reportPossiblyUnboundVariable]
                    break
        except Exception:
            img = None

    # Final placeholder: use RGB to avoid typing issues with RGBA tuples
    if img is None:
        img = Image.new("RGB", (size, size), (50, 50, 50)) # pyright: ignore[reportOptionalMemberAccess, reportPossiblyUnboundVariable]

    # Choose resampling filter compatibly across Pillow versions
    try:
        resample = Image.Resampling.LANCZOS  # Pillow >= 9.1 # pyright: ignore[reportOptionalMemberAccess, reportPossiblyUnboundVariable]
    except Exception:
        # fallback for older Pillow
        resample = getattr(Image, "LANCZOS", Image.ANTIALIAS) # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue, reportPossiblyUnboundVariable]

    # Fit/crop to square thumbnail consistently
    try:
        img_thumb = ImageOps.fit(img, (size, size), method=resample) # pyright: ignore[reportOptionalMemberAccess, reportPossiblyUnboundVariable]
    except TypeError:
        # older ImageOps might expect 'method' positional name 'resample' — try both
        try:
            img_thumb = ImageOps.fit(img, (size, size), resample=resample) # pyright: ignore[reportOptionalMemberAccess, reportCallIssue, reportPossiblyUnboundVariable]
        except Exception:
            # final fallback: simple resize
            img_thumb = img.resize((size, size), resample)

    # Return CTkImage (works for both light and dark modes)
    return CTkImage(light_image=img_thumb, dark_image=img_thumb, size=(size, size))




class SettingsDialog(ctk.CTkToplevel):
    """Modal settings window to change appearance, shuffle, loop and volume."""
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Settings")
        self.geometry("420x320")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # read current saved settings (safe defaults)
        data = gud.getUserData()
        saved = {}
        if data and isinstance(data, list):
            saved = data[0].get("settings", {}) or {}

        current_mode = "dark" if str(("dark" if saved['darkMode'] else "light")) else "light"
        self.appearance_var = ctk.StringVar(value=current_mode)
        self.shuffle_var = ctk.BooleanVar(value=bool(saved.get("shuffle", parent.shuffle_state)))
        self.loop_var = ctk.BooleanVar(value=bool(saved.get("loop", parent.loop_state)))
        self.volume_var = ctk.IntVar(value=int(saved.get("volume", parent.volume_level)))

        # Layout
        pad = dict(padx=16, pady=8, anchor="w")
        ctk.CTkLabel(self, text="Appearance", font=("Helvetica", 14, "bold")).pack(**pad)
        ap_frame = ctk.CTkFrame(self, fg_color="transparent")
        ap_frame.pack(fill="x", padx=16)
        ctk.CTkRadioButton(ap_frame, text="Dark", variable=self.appearance_var, value="dark").pack(side="left", padx=(0,10), pady=10)
        ctk.CTkRadioButton(ap_frame, text="Light", variable=self.appearance_var, value="light").pack(side="left", pady=10)

        ctk.CTkLabel(self, text="Playback", font=("Helvetica", 14, "bold")).pack(**pad)
        pb_frame = ctk.CTkFrame(self, fg_color="transparent")
        pb_frame.pack(fill="x", padx=16)
        ctk.CTkCheckBox(pb_frame, text="Shuffle", variable=self.shuffle_var).pack(side="left", padx=(0,10))
        ctk.CTkCheckBox(pb_frame, text="Loop", variable=self.loop_var).pack(side="left")

        ctk.CTkLabel(self, text="Volume", font=("Helvetica", 14, "bold")).pack(**pad)
        self.volume_slider = ctk.CTkSlider(self, from_=0, to=100, orientation="horizontal", variable=self.volume_var, number_of_steps=100)
        self.volume_slider.pack(fill="x", padx=16, pady=(0,12))

        # Save / Cancel
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(btn_frame, text="Save", width=100, command=self.on_save).pack(side="right", padx=(6,0))
        ctk.CTkButton(btn_frame, text="Cancel", width=100, command=self.destroy).pack(side="right")

    def on_save(self):
        # gather new settings
        new_settings = {
            "darkMode": (self.appearance_var.get() == "dark"),
            "shuffle": bool(self.shuffle_var.get()),
            "loop": bool(self.loop_var.get()),
            "volume": int(self.volume_var.get()),
            # preserve muted flag if controller had it
            "muted": getattr(self.parent, "muted_state", False)
        }

        # persist to user data (merges into existing structure using your gud helper)
        try:
            gud.addUserData({"settings": new_settings})
        except Exception as e:
            # non-fatal; log and proceed (your logger is 'l')
            l.error("Failed to save settings: %s", e)

        # apply changes live
        try:
            # appearance mode
            ctk.set_appearance_mode("Dark" if new_settings["darkMode"] else "Light")
        except Exception:
            pass

        try:
            # update parent attributes and volume
            self.parent.shuffle_state = new_settings["shuffle"]
            self.parent.loop_state = new_settings["loop"]
            self.parent.volume_level = new_settings["volume"]
            if not getattr(self.parent, "muted_state", False):
                self.parent.audio.set_volume(self.parent.volume_level / 100.0)
            # update UI toggles if you have references (best-effort)
            # (e.g. update shuffle/loop button colors if they exist)
            try:
                # safe attempt to update shuffle/loop button visuals
                for name in ("shuffle_btn", "loop_btn"):
                    btn = getattr(self.parent, name, None)
                    if btn:
                        state = (self.parent.shuffle_state if name == "shuffle_btn" else self.parent.loop_state)
                        btn.configure(fg_color=("#2b8a3e" if state else "#444"))
            except Exception:
                pass
        except Exception:
            pass

        self.destroy()


class createMainWindow(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.grid_columnconfigure(0, weight=1)


class createSideWindow(ctk.CTkFrame):
    def __init__(self, master, controller, **kwargs):
        super().__init__(master, **kwargs)
        self.controller = controller

        # Configure overall grid
        self.grid_rowconfigure(0, weight=1)  # top frame (buttons)
        self.grid_rowconfigure(1, weight=1)  # main content / playlists
        self.grid_rowconfigure(2, weight=0)  # bottom frame (optional)
        self.grid_columnconfigure(0, weight=1)

        # Top frame for buttons
        self.top_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.top_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.top_frame.grid_columnconfigure(0, weight=1)  # ensure buttons stretch

        # Main frame for dynamic content
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)

        # Bottom frame if needed
        #self.bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        #self.bottom_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=10)

        """bottom_frame IS CURRENTLY BROKEN"""

        # --- dynamic area state ---
        self._playlist_btns = []
        self._pl_cache = None  # list of (pid, name) to detect changes

        # a tiny clock to prove the heartbeat runs
        self._clock_label = ctk.CTkLabel(self.main_frame, text="")
        self._clock_label.grid(row=0, column=0, sticky="sw", pady=(6,0))

        # Buttons — parented to top_frame (static controls)
        self.newPlaylistButton = ctk.CTkButton(
            self.top_frame,
            text="+ Create New Playlist",
            fg_color='#333333',
            hover_color='#555555',
            corner_radius=10,
            font=('Helvetica', 16, 'bold'),
            command=lambda: createNewPlaylist()
        )
        self.newPlaylistButton.grid(row=0, column=0, sticky="ew", pady=10, ipady=10)

        self.gotoLibrary = ctk.CTkButton(
            self.top_frame,
            text="Library",
            fg_color='#333333',
            hover_color='#555555',
            corner_radius=10,
            font=('Helvetica', 16),
            command=lambda: controller.show_frame(showLibrary)
        )
        self.gotoLibrary.grid(row=1, column=0, sticky="ew", pady=10, ipady=10)


    def refresh_tick(self):
        """Called every ~100ms by App._heartbeat."""
        # update the little clock so you can see it moving
        try:
            # show seconds only to avoid flicker
            self._clock_label.configure(text=time.strftime("%H:%M:%S"))
        except Exception:
            pass

        # check playlists; rebuild only on change
        try:
            self._refresh_playlists()
        except Exception:
            pass


    def _refresh_playlists(self, force=False):
        """Rebuild playlist buttons when user data changes."""
        userdata = gud.getUserData()
        if not userdata or not isinstance(userdata, list):
            return

        playlists = userdata[0].get('playlists', {}) or {}
        songs_data = userdata[0].get('songs', {}) or {}

        # stable signature for change detection
        current = sorted(
            [(pid, (pdata or {}).get('name', '')) for pid, pdata in playlists.items()],
            key=lambda x: (x[1] or "").lower()
        )

        if not force and current == self._pl_cache:
            return  # nothing changed

        # destroy old
        for b in self._playlist_btns:
            try:
                b.grid_forget()
                b.destroy()
            except Exception:
                pass
        self._playlist_btns.clear()

        # recreate playlist buttons starting *below* your static controls
        next_row = max(child.grid_info().get("row", 0) for child in self.top_frame.winfo_children()) + 1 if self.top_frame.winfo_children() else 2

        for pid, name in current:
            btn = ctk.CTkButton(
                self.top_frame,
                text=name or "Untitled",
                fg_color='#333333',
                hover_color='#555555',
                corner_radius=10,
                font=('Helvetica', 16),
                command=lambda pid=pid, pdata=playlists[pid]: self.controller.show_playlist(pid, pdata, songs_data)
            )
            btn.grid(row=next_row, column=0, sticky="ew", pady=5, ipady=10)
            self._playlist_btns.append(btn)
            next_row += 1

        self._pl_cache = current



    
class createWelcome(ctk.CTkToplevel):
    def __init__(self, parent, controller):
        super().__init__(parent)

        self.geometry('500x400')
        self.title("Welcome to PyTunes")

        self.attributes('-topmost', True)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.pagesContainer = ctk.CTkFrame(self)
        self.pagesContainer.grid(row=0, column=0, sticky='nsew')

        self.pagesContainer.grid_rowconfigure(0, weight=1)
        self.pagesContainer.grid_columnconfigure(0, weight=1)

        self.pages = {}

        for P in (pageStart, pageAddMusic):
            page_name = P.__name__
            page = P(parent=self.pagesContainer, controller=self)
            self.pages[page_name] = page
            page.grid(row=0, column=0, sticky="nsew")

        self.current_page = self.pages['pageStart']
        self.current_page.lift()


        self.show_page("pageStart")


    def show_page(self, page_name):
        page = self.pages[page_name]
        page.tkraise()


    def __animate_page_change(self, target_name, dir='right'):
        nextPage = self.pages[target_name]
        width = self.winfo_width()

        if dir == 'right':
            nextPage.place(x=width, y=0, relwidth=1, relheight=1)
            step = -20

        else:
            nextPage.place(x=width, y=0, relwidth=1, relheight=1)
            step = 20


        nextPage.lift()


        def slide():
            nonlocal width
            xCurr = nextPage.winfo_x()

            if (dir == "right" and xCurr > 0) or (dir == "left" and xCurr < 0):
                self.current_page.place_configure(x=xCurr + step)
                nextPage.place_configure(x=xCurr + step)
                self.after(10, slide)

            else:
                self.current_page.place_forget()
                nextPage.place(x=0, y=0, relwidth=1, relheight=1)
                self.current_page = nextPage

        slide()

    
    def next_page(self, name):
        self.__animate_page_change(name, dir='right')

    
    def prev_page(self, name):
        self.__animate_page_change(name, dir='left')


class pageStart(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)

        welcomeLabel = ctk.CTkLabel(self, text="Welcome to PyTunes!", font=("Helvetica", 24, 'bold'))
        welcomeLabel.pack(fill=None, anchor='center', pady=20)

        nextButton = ctk.CTkButton(self, text="Next", command=lambda: controller.show_page("pageAddMusic"))
        nextButton.pack()



class pageAddMusic(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)

        self.controller = controller
        self.skeleton = skeleton if skeleton else {}

        label = ctk.CTkLabel(self, text="Welcome to PyTunes!", font=("Helvetica", 24, "bold"))
        label.pack(fill=None, anchor='center', pady=20)

        navFrame = ctk.CTkFrame(self, fg_color='transparent')
        navFrame.pack(pady=20)

        prevButton = ctk.CTkButton(navFrame, text="Previous", font=("Helvetica", 14),
                                   command=lambda: controller.prev_page("pageBasicDetails"))
        
        
        prevButton.pack(anchor='center', padx=10, pady=15)

        self.add_songs_to_playlist()

        close_button = ctk.CTkButton(
            self, text="Finish",
            fg_color="green",
            command=self.controller.destroy
        )

        
        close_button.pack(pady=20)


    def add_songs_to_playlist(self):
        """
        Scan Music/ and add files to the in-memory skeleton, then persist via gud.addUserData().
        Robust against an empty `skeleton` or missing keys in a fresh user.json.
        """
        # ensure skeleton has the expected shape
        global skeleton
        if not isinstance(skeleton, dict):
            skeleton = {}

        skeleton.setdefault('playlists', skeleton.get('playlists', {}) or {})
        skeleton.setdefault('songs', skeleton.get('songs', {}) or {})
        skeleton.setdefault('settings', skeleton.get('settings', {
            'darkMode': True,
            'shuffle': False,
            'loop': False,
        }))

        # find all files in Music folder
        paths = [str(p.resolve()) for p in Path('Music').rglob('*') if p.is_file()]

        # If there are no paths, still persist the (possibly-defaulted) skeleton and return
        if not paths:
            try:
                gud.addUserData(skeleton)
            except Exception as e:
                l.error("Failed to save skeleton for empty music folder: %s", e)
            return

        # Determine starting index for new song ids (avoid clobbering existing keys)
        existing = skeleton.get('songs', {}) or {}
        # collect numeric suffixes from existing keys like 'song0', 'song12'
        max_idx = -1
        import re
        for k in existing.keys():
            m = re.fullmatch(r"song(\d+)", k)
            if m:
                try:
                    idx = int(m.group(1))
                    if idx > max_idx:
                        max_idx = idx
                except Exception:
                 pass
        start_idx = max_idx + 1

        # Add paths into skeleton['songs'] with stable keys
        try:
            for offset, p in enumerate(paths):
                idx = start_idx + offset
                name_part = os.path.splitext(os.path.basename(p))[0]
                skeleton['songs'][f"song{idx}"] = {
                    'name': name_part,
                    'loc': os.path.abspath(p)
                }

            # persist the skeleton
            try:
                gud.addUserData(skeleton)
            except Exception as e:
                l.error("Failed to write user data after adding songs: %s", e)

        except Exception as e:
            l.exception("Unexpected error while adding songs to skeleton: %s", e)

            try:
                gud.addUserData(skeleton)

            except Exception as e2:
                l.error("Failed to save skeleton after exception: %s", e2)


    def on_finish_clicked(self):
        self.controller.setup_complete()


class createNewPlaylist(ctk.CTkToplevel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.title("New Playlist")
        self.geometry("420x420")

        # will hold a Tk-compatible image reference so it isn't GC'd
        self.current_image = None
        # path to the user-selected icon (saved with playlist)
        self.selected_icon_path = None

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 6))

        # small canvas to preview chosen image
        self.chooseUserPlaylistImage = ctk.CTkCanvas(top, width=100, height=100, bg='#333333', highlightthickness=0)
        self.chooseUserPlaylistImage.pack(side='left', fill='none', expand=True)

        # optional: text next to image
        label_frame = ctk.CTkFrame(top, fg_color="transparent")
        label_frame.pack(side="left", fill="both", expand=True, padx=(8,0))
        ctk.CTkLabel(label_frame, text="Playlist name").pack(anchor="w")
        self.playlistName = ctk.StringVar()
        self.npName = ctk.CTkEntry(label_frame, textvariable=self.playlistName, corner_radius=10)
        self.npName.pack(fill="x", pady=6)

        # rest of UI ...
        self.checkboxFrame = ctk.CTkScrollableFrame(self, label_text='Select songs to add')
        self.checkboxFrame.pack(fill="both", expand=True, padx=(0, 12), pady=6)

        data = gud.getUserData()
        self.songs: dict = (data[0].get('songs', {}) if data and isinstance(data, list) else {})
        self.checkboxVars: dict[str, ctk.BooleanVar] = {}

        for song_id, meta in self.songs.items():
            name = meta.get("name", "Untitled")
            var = ctk.BooleanVar(value=False)
            cb = ctk.CTkCheckBox (
                self.checkboxFrame,
                text=name,
                corner_radius=15,
                variable=var
            )
            cb.pack(anchor="w", padx=10, pady=4)
            self.checkboxVars[song_id] = var

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=12, pady=(6, 12))

        def toggle_all(state: bool):
            for v in self.checkboxVars.values():
                v.set(state)
            update_add_button()

        self.filetypes = [
            ("Image files", ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.tiff")),
            ("All files", "*.*")
        ]

        # Add Image button -> now calls improved writer
        ctk.CTkButton(top, text='Add Image', corner_radius=15, command=self.writePlaylistImage).pack(side='left', padx=(0, 6))
        ctk.CTkButton(footer, text="Select All", corner_radius=15, command=lambda: toggle_all(True)).pack(side="left", padx=(0, 6))
        ctk.CTkButton(footer, text="Clear", corner_radius=15, command=lambda: toggle_all(False)).pack(side="left", padx=(0, 6))

        self.addPLButton = ctk.CTkButton(
            footer,
            state='disabled',
            corner_radius=15,
            text="Add Playlist",
            command=self._save_new_playlist
        )
        self.addPLButton.pack(side="right")

        def update_add_button(*_):
            name_ok = bool(self.playlistName.get().strip())
            any_checked = any(v.get() for v in self.checkboxVars.values())
            self.addPLButton.configure(
                state=("normal" if (name_ok and any_checked) else "disabled"),
                text=("Add Playlist" if name_ok else "Name required"),
                text_color=("white" if name_ok else "red")
            )

        self.playlistName.trace_add("write", update_add_button)
        for v in self.checkboxVars.values():
            v.trace_add("write", update_add_button)


    def writePlaylistImage(self):
        """Prompt user to choose an image, show thumbnail and remember the path for saving."""
        path = filedialog.askopenfilename(title="Select an image", filetypes=self.filetypes)
        if not path:
            return

        try:
            # open and make a square thumbnail (preserve aspect)
            img = Image.open(path)  # type: ignore # requires `from PIL import Image, ImageOps, ImageTk`
            # choose resample compatibly
            try:
                resample = Image.Resampling.LANCZOS # type: ignore
            except Exception:
                resample = getattr(Image, "LANCZOS", Image.ANTIALIAS) # pyright: ignore[reportPossiblyUnboundVariable, reportAttributeAccessIssue]
            # fit/resize to 100x100
            try:
                from PIL import ImageOps
                thumb = ImageOps.fit(img.convert("RGBA"), (100, 100), method=resample)
            except Exception:
                thumb = img.copy().resize((100, 100), resample)

            # Convert to a Tk image and keep a reference so GC doesn't clear it
            self.current_image = ImageTk.PhotoImage(thumb) # type: ignore
            # clear existing preview and draw centered at 50,50
            try:
                self.chooseUserPlaylistImage.delete("all")
            except Exception:
                pass
            self.chooseUserPlaylistImage.create_image(50, 50, image=self.current_image)
            self.chooseUserPlaylistImage.update()

            # remember the path to save with the playlist later
            self.selected_icon_path = os.path.abspath(path)

        except Exception as e:
            l.error("Failed to open image for playlist icon: %s", e)
            # keep UI responsive; do nothing else


    def _next_playlist_id(self, playlists: dict) -> str:
        """Return a new unique playlist id like 'pl3'."""
        import re
        nums = []
        for k in playlists.keys():
            m = re.fullmatch(r"pl(?:aylist)?(\d+)", k) or re.fullmatch(r"pl(\d+)", k)
            if m:
                nums.append(int(m.group(1)))
        nxt = (max(nums) + 1) if nums else len(playlists)
        return f"playlist{nxt}"

    def _save_new_playlist(self):
        playlist_name = self.playlistName.get().strip()
        if not playlist_name:
            return

        # collect selected song IDs
        selected_ids = [sid for sid, var in self.checkboxVars.items() if var.get()]
        if not selected_ids:
            self.addPLButton.configure(text="Pick at least one song", text_color="red")
            return

        data = gud.getUserData()
        if not data or not isinstance(data, list):
            self.addPLButton.configure(text="No user data found", text_color="red", state="disabled")
            return

        user = data[0]
        playlists = user.get("playlists", {}) or {}

        # prevent duplicate playlist names
        existing_names = {pl.get('name', '') for pl in playlists.values()}
        if playlist_name in existing_names:
            self.addPLButton.configure(text="Playlist already exists!", text_color="red")
            return

        # create new playlist id and payload
        new_pid = self._next_playlist_id(playlists)
        new_entry = {
            "name": playlist_name,
            "songs": selected_ids,
        }

        # --- copy chosen icon into local ./Images folder ---
        src_icon = getattr(self, "selected_icon_path", None)
        if src_icon:
            try:
                src_path = Path(src_icon)
                ext = src_path.suffix or ".png"
                img_dir = get_local_image_dir()
                target_path = img_dir / f"{new_pid}{ext}"

                # if collision, append random uuid
                if target_path.exists():
                    target_path = img_dir / f"{new_pid}_{uuid.uuid4().hex}{ext}"

                shutil.copy2(str(src_path), str(target_path))
                new_entry["icon"] = str(target_path.resolve())

            except Exception as e:
                l.error("Failed to copy playlist icon into local Images folder: %s", e)
                # fallback: still store original path
                new_entry["icon"] = src_icon

        payload = {"playlists": {new_pid: new_entry}}

        try:
            gud.addUserData(payload)
        except Exception as e:
            l.error(e)
            self.addPLButton.configure(text="Save failed", text_color="red")
            return

        self.addPLButton.configure(text="Playlist added!", text_color="green", state="disabled")
        self.after(800, self.destroy)



class showLibrary(ctk.CTkFrame):
    """
    Library view: header + rows aligned using a shared grid.
    Column widths controlled by `column_weights` to keep Title centered under header.
    """

    ROW_BG = "#2b2b2b"
    ROW_HOVER_BG = "#3a3a3a"
    ROW_ACTIVE_BG = "#696969"
    ROW_HEIGHT = 40

    column_weights = (6, 40, 20, 28, 6)

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.audio = getattr(self.controller, "audio", None)
        
        self._songs_sig = None
        self._last_rebuild_ms = 0

        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.outer_padx = (20, 20)

        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=self.outer_padx, pady=(12, 6))


        ctk.CTkLabel(self.header_frame, text='Library', font=('Helvetica', 32, 'bold')).pack()
        num_songs = len(gud.getUserData()[0].get("songs", [])) # type: ignore
        hours, minutes = self.get_library_duration()
        info_text = f"{num_songs} Songs • {hours}hrs {minutes}mins"

        self.duration_label = ctk.CTkLabel(
            self.header_frame,
            text=info_text,
            font=("Helvetica", 16),
            text_color="#bbbbbb"
        )

        self.duration_label.pack(anchor="w", pady=(4, 0))

        self.separator = ctk.CTkFrame(self, fg_color="#444444", height=5)
        self.separator.grid(row=1, column=0, sticky="ew", padx=self.outer_padx, pady=(0, 6))

        self.scroll_area = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_area.grid(row=2, column=0, sticky="nsew", padx=self.outer_padx, pady=(0, 12))
        self.scroll_area.grid_rowconfigure(0, weight=1)
        self.scroll_area.grid_columnconfigure(0, weight=1)

        self.list_container = ctk.CTkFrame(self.scroll_area, fg_color="transparent")
        self.list_container.grid(row=0, column=0, sticky="nsew")

        for col, w in enumerate(self.column_weights):
            self.list_container.grid_columnconfigure(col, weight=w)

        # bookkeeping
        self.row_bg_frames = []
        self.row_widgets = []
        self.table_index = {}
        self.selected_index = None

        # initial build
        self._try_build_from_userdata()


    def get_library_duration(self) -> tuple[int, int]:
        """
        Return (hours, minutes) total duration for the given playlist.
        """

        from mutagen import _file as MutaFile

        data = gud.getUserData()[0] # type: ignore

        song_data = data.get('songs', {})

        total_seconds = 0

        for sid in song_data: # type: ignore
            song = song_data.get(sid) # type: ignore
            length = MutaFile.File(song.get('loc', None)).info.length # type: ignore

            if not song:
                continue

            if not length:
                continue

            total_seconds += int(length)

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return hours, minutes

    # ----- helpers -----
    def _songs_signature(self, songs: dict) -> tuple:
        items = []
        for sid, sdata in songs.items():
            name = (sdata or {}).get("name", "")
            loc = (sdata or {}).get("loc", "")
            items.append((sid, name, loc))
        items.sort(key=lambda x: (str(x[1]).lower(), str(x[0])))
        return tuple(items)

    def _now_ms(self):
        return int(time.monotonic() * 1000)

    def refresh_tick(self):
        self._try_build_from_userdata()

    def on_setup_changed(self):
        self._try_build_from_userdata(force=True)

    def _try_build_from_userdata(self, force: bool = False):
        try:
            data = gud.getUserData()
        except Exception:
            data = None

        songs = {}
        if data and isinstance(data, (list, tuple)) and len(data) > 0:
            songs = data[0].get("songs", {}) or {}

        new_sig = self._songs_signature(songs)
        now_ms = self._now_ms()

        if not force and self._songs_sig is not None:
            if new_sig == self._songs_sig:
                return
            if now_ms - self._last_rebuild_ms < 150:
                return

        self._songs_sig = new_sig
        self._last_rebuild_ms = now_ms
        self._build_rows(songs)

    def _build_rows(self, songs: dict):
        for child in list(self.list_container.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass
        self.row_bg_frames.clear()
        self.row_widgets.clear()
        self.table_index.clear()
        self.selected_index = None

        if not songs:
            placeholder = ctk.CTkLabel(self.list_container, text="No songs in library.", font=("Helvetica", 16))
            placeholder.grid(row=0, column=0, columnspan=len(self.column_weights), sticky="n", padx=8, pady=22)
            return

        from mutagen import _file as MutaFile
        row_font = ("Helvetica", 16)

        for i, (song_id, song_data) in enumerate(songs.items(), start=1):
            title = song_data.get("name", "Untitled")
            path = song_data.get("loc", "")
            artist = "Unknown"
            album = "Unknown"
            length = "00:00"

            try:
                mf = MutaFile.File(path)
                if mf and getattr(mf, "info", None):
                    secs = int(round(float(mf.info.length)))
                    length = f"{secs//60:02}:{secs%60:02}"
                tags = getattr(mf, "tags", {}) or {}
                if "TPE1" in tags:
                    a = tags.get("TPE1")
                    artist = a[0] if isinstance(a, (list, tuple)) and a else str(a)
                elif "artist" in tags:
                    artist = tags.get("artist")
                if "TALB" in tags:
                    al = tags.get("TALB")
                    album = al[0] if isinstance(al, (list, tuple)) and al else str(al)
                elif "album" in tags:
                    album = tags.get("album")
            except Exception:
                pass

            self.table_index[i] = {"id": song_id, "title": title, "artist": artist, "album": album, "length": length, "path": path}

            bg = ctk.CTkFrame(self.list_container, fg_color=self.ROW_BG, corner_radius=6, height=self.ROW_HEIGHT)
            bg.grid(row=i - 1, column=0, columnspan=len(self.column_weights), sticky="ew", padx=0, pady=(1, 1))
            
            self.list_container.grid_rowconfigure(i - 1, minsize=self.ROW_HEIGHT)

            label_padx = (8, 6)
            
            idx_lbl = ctk.CTkLabel(self.list_container, text=str(i), font=row_font, fg_color=self.ROW_BG, corner_radius=0)
            idx_lbl.grid(row=i - 1, column=0, sticky="w", padx=label_padx, pady=0)

            title_lbl = ctk.CTkLabel(self.list_container, text=title, font=row_font, fg_color=self.ROW_BG, corner_radius=0)
            title_lbl.grid(row=i - 1, column=1, sticky="w", padx=label_padx, pady=0)

            artist_lbl = ctk.CTkLabel(self.list_container, text=artist, font=row_font, fg_color=self.ROW_BG, corner_radius=0) # type: ignore
            artist_lbl.grid(row=i - 1, column=2, sticky="w", padx=label_padx, pady=0)

            album_lbl = ctk.CTkLabel(self.list_container, text=album, font=row_font, fg_color=self.ROW_BG, corner_radius=0) # type: ignore
            album_lbl.grid(row=i - 1, column=3, sticky="w", padx=label_padx, pady=0)

            length_lbl = ctk.CTkLabel(self.list_container, text=length, font=row_font, fg_color=self.ROW_BG, corner_radius=0)
            length_lbl.grid(row=i - 1, column=4, sticky="w", padx=label_padx, pady=0)

            def _make_on_click(idx=i, p=path, t=title):
                def _on_click(event=None):
                    self._select_row(idx)
                    try:
                        self.controller.play_song(p, t)
                    except Exception:
                        pass
                return _on_click

            bg.bind("<Button-1>", _make_on_click())
            for w in (idx_lbl, title_lbl, artist_lbl, album_lbl, length_lbl):
                w.bind("<Button-1>", _make_on_click())

            def _make_on_rclick(sid=song_id, name=title):
                def _on_rclick(event):
                    if hasattr(self.controller, "show_context_menu"):
                        try:
                            self.controller.show_context_menu(event, {"sid": sid, "name": name})
                        except Exception:
                            pass
                return _on_rclick

            bg.bind("<Button-3>", _make_on_rclick())
            for w in (idx_lbl, title_lbl, artist_lbl, album_lbl, length_lbl):
                w.bind("<Button-3>", _make_on_rclick())

            def _make_on_enter(frame_bg=bg, idx=i, widgets=(idx_lbl, title_lbl, artist_lbl, album_lbl, length_lbl)):
                def _on_enter(e):
                    if self.selected_index != idx:
                        try:
                            frame_bg.configure(fg_color=self.ROW_HOVER_BG)
                            for w in widgets:
                                w.configure(fg_color=self.ROW_HOVER_BG)
                        except Exception:
                            pass
                return _on_enter

            def _make_on_leave(frame_bg=bg, idx=i, widgets=(idx_lbl, title_lbl, artist_lbl, album_lbl, length_lbl)):
                def _on_leave(e):
                    if self.selected_index != idx:
                        try:
                            frame_bg.configure(fg_color=self.ROW_BG)
                            for w in widgets:
                                w.configure(fg_color=self.ROW_BG)
                        except Exception:
                            pass
                return _on_leave

            bg.bind("<Enter>", _make_on_enter()) # type: ignore
            bg.bind("<Leave>", _make_on_leave()) # type: ignore
            for w in (idx_lbl, title_lbl, artist_lbl, album_lbl, length_lbl):
                w.bind("<Enter>", _make_on_enter())
                w.bind("<Leave>", _make_on_leave())

            # store refs
            self.row_bg_frames.append(bg)
            self.row_widgets.append({"idx": idx_lbl, "title": title_lbl, "artist": artist_lbl, "album": album_lbl, "length": length_lbl})

        # layout settle
        self.list_container.update_idletasks()


    def set_playing_row(self, index):
        """Visually highlight the given row as the currently playing song."""
        try:
            # Reset previous "playing" highlight if any
            if hasattr(self, "_playing_index") and self._playing_index is not None:
                prev_bg = self.row_bg_frames[self._playing_index - 1]
                prev_bg.configure(fg_color=self.ROW_BG)
                prev_widgets = self.row_widgets[self._playing_index - 1]
                for key in ("idx", "title", "artist", "album", "length"):
                    prev_widgets[key].configure(fg_color=self.ROW_BG)
        except Exception:
            pass

        try:
            if 1 <= index <= len(self.row_bg_frames):
                bg = self.row_bg_frames[index - 1]
                bg.configure(fg_color=self.ROW_ACTIVE_BG)
                widgets = self.row_widgets[index - 1]
                for key in ("idx", "title", "artist", "album", "length"):
                    widgets[key].configure(fg_color=self.ROW_ACTIVE_BG)
                self._playing_index = index
        except Exception:
            pass


    def _select_row(self, index):
        try:
            if self.selected_index is not None and 1 <= self.selected_index <= len(self.row_bg_frames):
                prev_bg = self.row_bg_frames[self.selected_index - 1]
                prev_bg.configure(fg_color=self.ROW_BG)
                prev_widgets = self.row_widgets[self.selected_index - 1]
                for key in ("idx", "title", "artist", "album", "length"):
                    try:
                        prev_widgets[key].configure(fg_color=self.ROW_BG)
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            if 1 <= index <= len(self.row_bg_frames):
                bg = self.row_bg_frames[index - 1]
                bg.configure(fg_color=self.ROW_ACTIVE_BG)
                widgets = self.row_widgets[index - 1]
                for key in ("idx", "title", "artist", "album", "length"):
                    try:
                        widgets[key].configure(fg_color=self.ROW_ACTIVE_BG)
                    except Exception:
                        pass
                self.selected_index = index
        except Exception:
            pass


class showPlaylist(TickingFrame):
    playlist_icon_size = (256, 256)

    def __init__(self, parent, controller, playlist_id, playlist_data, songs_data):
        super().__init__(parent, fg_color='transparent')
        self.controller = controller
        self.playlist_id = playlist_id
        self.playlist_data = playlist_data or {}
        self.songs_data = songs_data or {}
        self.audio = getattr(self.controller, "audio", None)

        # layout grid (title, header, separator, list)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)

        # --- playlist title (big) ---
        pname = self.playlist_data.get("name", f"Playlist {self.playlist_id}")

        header_container = ctk.CTkFrame(self, fg_color="transparent")
        header_container.grid(row=0, column=0, sticky="nw", padx=(20,20), pady=(8,4))

        header_container.grid_columnconfigure(0, weight=0)  # icon column
        header_container.grid_columnconfigure(1, weight=1)  # title column
        header_container.grid_columnconfigure(2, weight=1)  # info column

        self._playlist_icon_ctkimage = None
        icon_path = None
        try:
            icon_path = self.playlist_data.get("icon")
        except Exception:
            icon_path = None

        if icon_path and PIL_AVAILABLE:
            try:
                from PIL import Image, ImageOps
                
                try:
                    from customtkinter import CTkImage
                except Exception:
                    CTkImage = None

                p = Path(icon_path)
                if p.exists() and CTkImage is not None:
                    try:
                        resample = Image.Resampling.LANCZOS
                    except Exception:
                        resample = getattr(Image, "LANCZOS", Image.ANTIALIAS) # type: ignore

                    img = Image.open(str(p)).convert("RGBA")

                    try:
                        contained = ImageOps.contain(img, self.playlist_icon_size, method=resample)

                    except TypeError:
                        contained = ImageOps.contain(img, self.playlist_icon_size)

                    thumb = Image.new("RGBA", self.playlist_icon_size, (0, 0, 0, 0))
                    x = (self.playlist_icon_size[0] - contained.width) // 2
                    y = (self.playlist_icon_size[1] - contained.height) // 2
                    thumb.paste(contained, (x, y), contained)

                    self._playlist_icon_ctkimage = CTkImage(light_image=thumb, dark_image=thumb, size=self.playlist_icon_size)

            except Exception:
                self._playlist_icon_ctkimage = None

        if self._playlist_icon_ctkimage:
            icon_lbl = ctk.CTkLabel(header_container, image=self._playlist_icon_ctkimage, text="")
            icon_lbl.grid(row=0, column=0, sticky="nw", padx=(0, 12))

        else:
            spacer = ctk.CTkFrame(header_container, width=128, height=128, fg_color="transparent")
            spacer.grid(row=0, column=0, sticky="nw", padx=(0, 12))


        if getattr(self, "_playlist_icon_ctkimage", None):
            icon_lbl = ctk.CTkLabel(header_container, image=self._playlist_icon_ctkimage, text="")
            icon_lbl.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 16))

        else:
            spacer = ctk.CTkFrame(header_container, width=128, height=128, fg_color="transparent")
            spacer.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 16))

        text_frame = ctk.CTkFrame(header_container, fg_color="transparent")
        text_frame.grid(row=0, column=1, sticky="nw")

        self.title_label = ctk.CTkLabel(
            text_frame,
            text=pname,
            font=("Helvetica", 34, "bold"),
        )
        self.title_label.pack(anchor="center", pady=(20, 5))

        num_songs = len(self.playlist_data.get("songs", []))
        hours, minutes = self.get_playlist_duration()
        info_text = f"{num_songs} Songs • {hours}hrs {minutes}mins"

        self.duration_label = ctk.CTkLabel(
            text_frame,
            text=info_text,
            font=("Helvetica", 16),
            text_color="#bbbbbb"
        )

        self.duration_label.pack(anchor="w", pady=(4, 0))

        self._embedded_lib = showLibrary(parent=self, controller=self.controller)
        self._embedded_lib.configure(fg_color="transparent")

        try:
            if hasattr(self._embedded_lib, "header_frame"):
                self._embedded_lib.header_frame.grid_forget()
            if hasattr(self._embedded_lib, "separator"):
                self._embedded_lib.separator.grid_forget()
        except Exception:
            pass


        self._embedded_lib.grid_configure(sticky="nsew", padx=(0,0), pady=(0,0))


        if hasattr(self._embedded_lib, "column_weights"):
            self.column_weights = tuple(self._embedded_lib.column_weights)
        else:
            self.column_weights = (6, 40, 20, 28, 6)

        if hasattr(self._embedded_lib, "outer_padx"):
            self.outer_padx = self._embedded_lib.outer_padx
        else:
            self.outer_padx = (20, 20)

        hdr_font = ("Helvetica", 12, "bold")
        hdr_anchors = ["w", "w", "w", "w", "e"]


        # hide embedded library's header/title/separator so nothing pushes rows down
        try:
            # header_frame & separator (if present)
            if hasattr(self._embedded_lib, "header_frame"):
                self._embedded_lib.header_frame.grid_forget()
            if hasattr(self._embedded_lib, "separator"):
                self._embedded_lib.separator.grid_forget()
            # if showLibrary creates a big title_label inside itself, remove it too
            if hasattr(self._embedded_lib, "title_label"):
                try:
                    self._embedded_lib.title_label.grid_forget() # type: ignore
                except Exception:
                    pass
            # placeholder label (if the library previously showed "No songs" text)
            if hasattr(self._embedded_lib, "_placeholder_label"):
                try:
                    self._embedded_lib._placeholder_label.grid_forget() # type: ignore
                except Exception:
                    pass
        except Exception:
            pass


        self._embedded_lib.grid(row=1, column=0, sticky="nsew", padx=(0,0), pady=(0,0))
        self._embedded_lib.grid_rowconfigure(0, weight=1)
        self._embedded_lib.grid_columnconfigure(0, weight=1)

        try:
            for col, w in enumerate(self.column_weights):
                self._embedded_lib.list_container.grid_columnconfigure(col, weight=w)
        except Exception:
            pass

        self._populate_embedded_with_playlist()

        self.now_playing_label = getattr(self.controller, "now_playing_label", None)
        self.song_info_label = getattr(self.controller, "now_playing_label", None)
        self.progress = getattr(self.controller, "progress", None)
        self.buttons_frame = getattr(self.controller, "buttons_frame", None)
        self.time_label = getattr(self.controller, "time_label", None)

    def get_playlist_duration(self) -> tuple[int, int]:
        """
        Return (hours, minutes) total duration for the given playlist.
        """

        from mutagen import _file as MutaFile

        playlist_data = self.playlist_data
        all_songs = self.songs_data

        total_seconds = 0

        for sid in playlist_data.get("songs", []):
            song = all_songs.get(sid)
            length = MutaFile.File(song.get('loc', None)).info.length # type: ignore

            if not song:
                continue

            if not length:
                continue

            total_seconds += int(length)

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return hours, minutes


    def _collect_playlist_song_ids(self):
        """Return list of song ids contained in playlist_data (order preserved if 'songs' exists)."""
        playlist_song_ids = []
        if isinstance(self.playlist_data, dict):
            if "songs" in self.playlist_data and isinstance(self.playlist_data["songs"], (list, tuple)):
                playlist_song_ids = list(self.playlist_data["songs"])
            else:
                for v in self.playlist_data.values():
                    if isinstance(v, (list, tuple)):
                        for sid in v:
                            if sid not in playlist_song_ids:
                                playlist_song_ids.append(sid)
                                
        return playlist_song_ids

    def _build_filtered_songs(self):
        """Construct a songs dict shaped like gud.getUserData()[0]['songs'] but limited to playlist entries."""
        playlist_song_ids = self._collect_playlist_song_ids()
        filtered = {}
        for sid in playlist_song_ids:
            if sid in self.songs_data:
                filtered[sid] = self.songs_data[sid]

        if not filtered and isinstance(self.playlist_data, dict):
            for v in self.playlist_data.values():
                if isinstance(v, (list, tuple)):
                    for sid in v:
                        if sid in self.songs_data and sid not in filtered:
                            filtered[sid] = self.songs_data[sid]

        return filtered

    def _populate_embedded_with_playlist(self):
        """Ask the embedded showLibrary to build rows for this playlist's songs."""
        filtered = self._build_filtered_songs()
        try:
            self._embedded_lib._build_rows(filtered)
        except Exception:
            try:
                for child in list(self._embedded_lib.list_container.winfo_children()):
                    child.destroy()
            except Exception:
                pass
            row = 0
            for sid, meta in filtered.items():
                name = meta.get("name", "Untitled")
                path = meta.get("loc", "")
                btn = ctk.CTkButton(self._embedded_lib.list_container, text=name,
                                    command=lambda p=path, n=name: self.controller.play_song(p, n))
                btn.grid(row=row, column=0, sticky="ew", padx=8, pady=2)
                row += 1

    def refresh(self):
        self._populate_embedded_with_playlist()

    def play_song(self, path, name):
        try:
            self.controller.play_song(path, name)
        except Exception:
            pass

    
class Main(TickingFrame):
    def __init__(self, parent, controller, **kwargs):
        super().__init__(parent, **kwargs)

        self.controller = controller

        self.TEST_DIR = "Music"
        self.userData = gud.getUserData() # type: ignore

        self.audio = self.controller.audio

        if type(self.userData) != bool:
            self.userData: dict = self.userData
            self.data = self.userData[0]
            self.songs = self.data['songs']
            self.playlists = self.data['playlists']
            self.settings = self.data['settings']

            self.APP_MODE = str(("dark" if self.settings['darkMode'] else "light"))
            self.loop = bool(True if self.settings["loop"] else False)
            self.shuffle = bool(True if self.settings["shuffle"] else False)


        else:
            self.openCreateWelcome()

            self.userData = gud.getUserData() # type: ignore
        
            if type(self.userData) != bool:
                root = self
                self.destroy()
                self = root

                root.mainloop()

                self.userData: dict = self.userData
                self.data = self.userData[0]
                self.songs = self.data['songs']
                self.playlists = self.data['playlists']
                self.settings = self.data['settings']

                self.APP_MODE = str(("dark" if self.settings['darkMode'] else "light"))
                self.loop = bool(True if self.settings["loop"] else False)
                self.shuffle = bool(True if self.settings["shuffle"] else False)


        self.APP_COLOUR = 'dark-blue'

        try:
            ctk.set_appearance_mode(self.APP_MODE)

        except AttributeError:
            ctk.set_appearance_mode('dark')


        ctk.set_default_color_theme(self.APP_COLOUR)

        l.info((self.winfo_width(), self.winfo_height()))

        self.initSideWindow = self.controller.initSideWindow

        # Configure grid for Main frame
        self.grid_rowconfigure(0, weight=0)  # top label
        self.grid_rowconfigure(1, weight=1)  # song list or main content
        self.grid_rowconfigure(2, weight=0)  # bottom buttons
        self.grid_columnconfigure(0, weight=1)

        self.main_topframe = ctk.CTkFrame(self, fg_color='transparent')
        self.main_mainFrame = ctk.CTkFrame(self, fg_color='transparent')
        self.main_bottomFrame = ctk.CTkFrame(self, fg_color='transparent')

        self.main_topframe.grid(row=0, column=0, sticky='n', pady=20)
        self.main_mainFrame.grid(row=1, column=0, sticky='n', pady=20)
        self.main_bottomFrame.grid(row=2, column=0, sticky='ew', pady=15, ipady=10)

        self.main_mainFrame.grid_rowconfigure(0, weight=1)
        self.main_mainFrame.grid_columnconfigure(0, weight=1)

        self.main_bottomFrame.grid_columnconfigure(0, weight=1)
        self.main_bottomFrame.grid_columnconfigure(1, weight=1)

        self.after(100, self.update)


    def openCreateWelcome(self):
        self.page_window = createWelcome(self, controller=self.controller)



class App(ctk.CTk):
    """Controller class for PyTunes"""
    def __init__(self, *args, **kwargs):
        ctk.CTk.__init__(self, *args, **kwargs)

        self.w = int(self.winfo_screenwidth() * 0.8)
        self.h = int(self.winfo_screenheight() * 0.6)

        self.geometry(f'{self.w}x{self.h}')
        self.title(f"{NAME} {__version__}")

        self.container = ctk.CTkFrame(self)
        self.container.grid(row=0, column=0, sticky="nsew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.audio = AudioBackend()

        data = gud.getUserData()
        if type(data) != bool:
            user = data[0] # type: ignore
            saved = user.get("settings", {})
            self.shuffle_state = saved.get("shuffle", False)
            self.loop_state = saved.get("loop", False)
            self.muted_state = saved.get("muted", False)
            self.volume_level = saved.get("volume", 100)

        else:
            # No user data — show the welcome / setup window modally and block until user finishes
            try:
                welcome = createWelcome(self, controller=self)
                # center relative to main window (optional)
                try:
                    self.update_idletasks()
                    w = self.winfo_width(); h = self.winfo_height()
                    x = self.winfo_x(); y = self.winfo_y()
                    welcome.geometry(f"+{x + w//2 - 250}+{y + h//2 - 200}")
                except Exception:
                    pass

                # Make it modal so the user must complete the setup
                welcome.grab_set()
                # Optionally, wait until the welcome is closed / setup is complete
                self.wait_window(welcome)

                # After the welcome closes, try reloading user data
                data = gud.getUserData()
                if type(data) != bool:
                    user = data[0] #type: ignore
                    self.shuffle_state = user.get("settings", {}).get("shuffle", False)
                    self.loop_state = user.get("settings", {}).get("loop", False)
                    self.muted_state = user.get("settings", {}).get("muted", False)
                    self.volume_level = user.get("settings", {}).get("volume", 100)
                else:
                    self.shuffle_state = False
                    self.loop_state = False
                    self.muted_state = False
                    self.volume_level = 100
            except Exception as e:
                l.error("Failed to show welcome dialog: %s", e)
                self.shuffle_state = False
                self.loop_state = False
                self.muted_state = False
                self.volume_level = 100


        songs = user.get('songs', {}) #type: ignore


        self.paths = [str(p.resolve()) for p in Path('Music').rglob('*') if p.is_file()]
        self.toAdd = []

        dataCopy = user #type: ignore

        if (len(songs.keys()) != len(self.paths)) and data:
            lg.debug(f"({len(songs.keys())=} != {len(self.paths)=}). Updating user.json...")

            if len(self.paths) < len(songs.keys()):
                l.error(f"({len(songs.keys())=} > {len(self.paths)=}. Songs may not show up since user.json contains the data, but the song file isn't in CWD/Music")
                ...

            else:
                for p in self.paths:
                    self.toAdd.append(p)


                songsVals = list(os.path.basename(i['loc']) for i in songs.values())

                for s in songsVals:
                    if s not in self.paths:
                        self.toAdd.append(s)

            l.info(f'Music folder out of sync with user.json. Adding{self.toAdd=}')

            for c, p in enumerate(self.toAdd):
                name_part = os.path.splitext(os.path.basename(p))[0]
                dataCopy['songs'][f'song{c}'] = {
                        'name': name_part,
                        'loc': os.path.abspath(p)
                    }

            try:
                gud.addUserData(dataCopy)


            except Exception as e:
                l.error(e)


        self.initSideWindow = createSideWindow(
            master=self.container, controller=self, width=200, fg_color='transparent', corner_radius=0
        )

        self.initSideWindow.grid(row=0, column=0, sticky="ns")
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=0)

        self.initMainWindow = ctk.CTkFrame(self.container, fg_color='transparent')
        self.initMainWindow.grid(row=0, column=1, sticky="nsew")
        self.container.grid_columnconfigure(1, weight=1)

        self.controls_frame = ctk.CTkFrame(self, fg_color="#222222", corner_radius=0)
        self.controls_frame.grid(row=1, column=0, sticky="nsew")

        self.grid_columnconfigure(0, weight=1)

        self._album_art_size = 96
        self.controls_frame.grid_columnconfigure(0, weight=0, minsize=self._album_art_size + 16)
        self.controls_frame.grid_columnconfigure(1, weight=1)
        self.controls_frame.grid_columnconfigure(2, weight=0, minsize=200)
        self.controls_frame.grid_columnconfigure(3, weight=0, minsize=180)

        self.controls_frame.grid_rowconfigure(0, weight=1)
        self.controls_frame.grid_rowconfigure(1, weight=1)
        self.controls_frame.grid_rowconfigure(2, weight=0)

        self._album_art_img = None
        try:
            placeholder = load_album_art("")  # may return CTkImage or None
        except Exception:
            placeholder = None

        if placeholder is not None:
            self._album_art_img = placeholder
            self.album_art_label = ctk.CTkLabel(self.controls_frame, image=self._album_art_img, text="", fg_color="transparent")
        else:
            self.album_art_label = ctk.CTkLabel(self.controls_frame, text="♪", font=("Helvetica", 28), fg_color="transparent")

        self.album_art_label.configure(width=self._album_art_size, height=self._album_art_size)
        self.album_art_label.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(12,8), pady=(6,6))

        self.now_playing_label = ctk.CTkLabel(
            self.controls_frame, text="", font=('Helvetica', 18, 'bold'),
            anchor="w", wraplength=max(300, self.w // 3)
        )

        self.now_playing_label.grid(row=0, column=1, sticky="sw", padx=(0,8), pady=(6,0))

        self.song_info_label = ctk.CTkLabel(
            self.controls_frame, text="", font=('Helvetica', 12), anchor="w",
            wraplength=max(300, self.w // 3)
        )

        self.song_info_label.grid(row=1, column=1, sticky="nw", padx=(0,8))

        self.buttons_frame = ctk.CTkFrame(self.controls_frame, fg_color="transparent")
        self.buttons_frame.grid(row=1, column=2, sticky="n", padx=(6,12), pady=(0,0))
        self.buttons_frame.grid_columnconfigure((0,1,2), weight=1)

        self.pause_btn = ctk.CTkButton(self.buttons_frame, width=44, text="⏸", text_color='white', font=('Helvetica', 24), fg_color="transparent", hover_color="#333333", corner_radius=100, command=lambda: getattr(self, "audio", None) and self.audio.pause())
        self.resume_btn = ctk.CTkButton(self.buttons_frame, width=44, text="▶", text_color='white', font=('Helvetica', 24), fg_color="transparent", hover_color="#333333", corner_radius=100, command=lambda: getattr(self, "audio", None) and self.audio.unpause())
        self.stop_btn = ctk.CTkButton(self.buttons_frame, width=44, text="⏹", text_color='white', font=('Helvetica', 24), fg_color="transparent", hover_color="#333333", corner_radius=100, command=self.stop_song)

        self.pause_btn.grid(row=0, column=0, padx=(6,10), pady=0, sticky='ns')
        self.resume_btn.grid(row=0, column=1, padx=(6,10), pady=0, sticky='ns')
        self.stop_btn.grid(row=0, column=2, padx=(6,10), pady=0, sticky='ns')

        self.tertiary_frame = ctk.CTkFrame(self.controls_frame, fg_color="transparent")
        self.tertiary_frame.grid(row=0, column=3, rowspan=2, sticky="se", padx=(0,10), pady=(0,0))

        self.tertiary_frame.grid_columnconfigure((0,1,2), weight=1)
        self.tertiary_frame.grid_rowconfigure((1, 2, 3), weight=1)


        self.mute_btn = ctk.CTkButton(
            self.tertiary_frame,
            text="🔇",
            width=36,
            fg_color="transparent",
            hover_color="#666",
            command=lambda: getattr(self, "toggle_mute", lambda: None)()
            )
        
        self.shuffle_btn = ctk.CTkButton (
            self.tertiary_frame,
            text="🔀",
            width=36,
            fg_color=("transparent" if not getattr(self, 'shuffle_state', False) else "#2b8a3e"),
            hover_color="#666",
            command=lambda: getattr(self, "toggle_shuffle", lambda: None)()
        )

        self.loop_btn = ctk.CTkButton(
            self.tertiary_frame,
            text="🔁",
            width=36,
            fg_color=("transparent" if not getattr(self, 'loop_state', False) else "#2b8a3e"),
            hover_color="#666",
            command=lambda: getattr(self, "toggle_loop", lambda: None)()
        )

        self.mute_btn.grid(row=1, column=0, sticky="ew")
        self.shuffle_btn.grid(row=1, column=1, sticky="ew")
        self.loop_btn.grid(row=1, column=2, sticky="ew")

        progress_container = ctk.CTkFrame(self.controls_frame, fg_color="transparent")
        progress_container.grid(row=2, column=0, columnspan=4, sticky="ew", padx=40, pady=(6,10))
        progress_container.grid_columnconfigure(0, weight=1)
        progress_container.grid_columnconfigure(1, weight=0)


        self.progress = ctk.CTkProgressBar(progress_container, height=8)
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0,6))
        self.progress.set(0)

        self.progress.bind("<Button-1>", self._on_seek)

        self.play_start_offset = 0.0           
        self._playback_time_ref = None          
        self.current_song_length = 0.0
        self._is_playing = False
        self._is_paused = False
        self._is_scrubbing = False


        self.time_label = ctk.CTkLabel(progress_container, text="00:00 / 00:00", font=('Helvetica', 12))
        self.time_label.grid(row=0, column=1, sticky="e", padx=(10, 0))

        self.volume_var = ctk.DoubleVar(value=self.volume_level)
        self.volume_slider = ctk.CTkSlider(
            self.tertiary_frame,
            from_=0,
            to=100,
            orientation="horizontal",
            variable=self.volume_var,
            command=lambda v: self._update_volume(float(v))
        )
        self.volume_slider.grid(row=0, column=0, columnspan=4, sticky="s", padx=20, pady=10)
        self.audio.set_volume(self.volume_level/100)

        self.frames = {}
        self.current_frame = None


        for page in (Main, showLibrary, ):
            frame = page(controller=self, parent=self.initMainWindow)
            self.frames[page] = frame
            frame.place(x=0, y=0, relwidth=1, relheight=1)


        self.current_page = None
        self._playlist_btns = []
        self.after(100, self.show_frame, Main)
        self.after(100, self._update_progress)
        self.after(100, self._heartbeat)
        self._create_context_menu()

        self._menu_btn = ctk.CTkButton(
            self,
            text="≡",
            width=36,
            height=36,
            fg_color="#222222",
            bg_color='#222222',
            hover_color="#333333",
            corner_radius=32,
            font=('Helvetica', 32, 'bold')
        )

        self._menu_btn.place(relx=1.0, x=-12, y=10, anchor="ne")
        self._menu_btn.configure(command=self._show_menu)

        self._menu = Menu(self, tearoff=0)
        self._menu.add_command(label="Settings", command=lambda: SettingsDialog(self))
        self._menu.add_command(
            label="Toggle Dark/Light",
            command=lambda: ctk.set_appearance_mode(
                "Light" if ctk.get_appearance_mode() == "Dark" else "Dark"
            )
        )
        self._menu.add_separator()
        self._menu.add_command(label="Quit", command=self.destroy)
        

    def save_settings(self):
            gud.addUserData({"settings": {
                "shuffle": self.shuffle_state,
                "loop": self.loop_state,
                "muted": self.muted_state,
                "volume": self.volume_level
            }})


    def toggle_shuffle(self):
            self.shuffle_state = not self.shuffle_state
            self.shuffle_btn.configure(fg_color=("#2b8a3e" if self.shuffle_state else "transparent"))
            self.save_settings()

    def toggle_loop(self):
            self.loop_state = not self.loop_state
            self.loop_btn.configure(fg_color=("#2b8a3e" if self.loop_state else "transparent"))
            self.save_settings()

    def toggle_mute(self):
            self.muted_state = not self.muted_state
            if self.muted_state:
                self.audio.set_volume(0.0)
            else:
                self.audio.set_volume(self.volume_level/100)
            self.mute_btn.configure(fg_color=("#a83232" if self.muted_state else "transparent"))
            self.save_settings()


    def _show_menu(self, event=None):
        x = self._menu_btn.winfo_rootx()
        y = self._menu_btn.winfo_rooty() + self._menu_btn.winfo_height()
        try:
            self._menu.tk_popup(x, y)
        finally:
            self._menu.grab_release()

        self._menu_btn.configure(command=self._show_menu)



    def show_frame(self, cont, animate=False, direction='right', duration=400):
        next_frame = self.frames[cont]

        if self.current_frame is next_frame:
            return

        width = self.container.winfo_width()

        if not animate or self.current_frame is None:
            next_frame.lift()
            self.current_frame = next_frame
            self.current_page = next_frame

            return


        if direction == 'right':
            start_pos = width
            step_sign = -1

        else:
            start_pos = -width
            step_sign = 1

        next_frame.place(x=start_pos, y=0, relwidth=1, relheight=1)
        next_frame.lift()

        fps = 120
        steps = max(int(duration / (1000/fps)), 1)
        step_px = step_sign * (width / steps)
        pos = float(start_pos)

        def slide():
            nonlocal pos
            pos += step_px
            if (direction == 'right' and pos <= 0) or (direction == 'left' and pos >= 0):
                pos = 0
                next_frame.place(x=0, y=0, relwidth=1, relheight=1)
                if self.current_frame:
                    self.current_frame.place_forget()
                self.current_frame = next_frame
                self.current_page = next_frame

            else:
                next_frame.place(x=int(pos), y=0, relwidth=1, relheight=1)
                if self.current_frame:
                    self.current_frame.place(
                        x=int(pos - width if direction=='right' else pos + width), y=0,
                        relwidth=1, relheight=1
                    )
                self.after(int(1000/fps), slide)

        slide()


    def show_context_menu(self, event, item_info: dict):
        """Display the context menu at mouse position for a given item."""

        self._context_item = item_info  # store info for callbacks
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()



    def _create_context_menu(self):
        """Create a reusable right-click menu for songs or playlists."""
        self.context_menu = Menu(self, tearoff=0)
        self.context_menu.add_command(label="Rename", command=self._context_rename)
        self.context_menu.add_command(label="Delete", command=self._context_delete)


    def _context_rename(self):
        item = getattr(self, "_context_item", None)
        if not item:
            return
        # Example rename logic — replace with your real update
        print(f"Rename requested for: {item['name']}")


    def _context_delete(self):
        item = getattr(self, "_context_item", None)
        if not item:
            return
        # Example delete logic — replace with your real delete
        print(f"Delete requested for: {item['name']}")


    def is_playing(self) -> bool:
        # Delegate to backend
        return self.audio.is_playing()

    def play_song(self, path: str, name: str):
        if not os.path.exists(path):
            l.critical(f"⚠️ File not found: {path}")
            return
        
        try:
            # reset & start
            self.audio.stop()
            self.audio.load(path)
            self.audio.play()
            self.play_start_offset = 0.0
            self.current_song_name = name
            self.current_song_path = path
            self.progress.set(0)

            current_view = getattr(self, "current_frame", None)

            # Ask it to highlight the playing song if it supports that method
            if hasattr(current_view, "set_playing_row"):
                try:
                    # Find the song index by title
                    for idx, row_data in current_view.table_index.items(): # type: ignore
                        if row_data["title"] == name:
                            current_view.set_playing_row(idx) # type: ignore
                            break
                except Exception as e:
                    print("Highlight failed:", e)

            if PIL_AVAILABLE:
                try:
                    new_img = load_album_art(path, size=self._album_art_size)
                    if new_img:
                        self._album_art_img = new_img
                        self.album_art_label.configure(image=self._album_art_img, text="")
                    else:
                        # if CTkImage couldn't be created, keep text placeholder
                        self.album_art_label.configure(image=None, text="♪")
                except Exception as e:
                    l.debug("Album art load error: %s", e)
                    try:
                        self.album_art_label.configure(image=None, text="♪")
                    except Exception as e:
                        l.error(e)
                        
            else:
                try:
                    self.album_art_label.configure(image=None, text="♪")
                except Exception as e:
                    l.error(e)


            # tags / labels
            songData = getAudioData(path)
            self.now_playing_label.configure(text=f"{name}")
            self.song_info_label.configure(
                text=f"\n{songData.artist or 'Unknown'} • {songData.album or 'Unknown'} • {songData.year or 'Unknown'}"
            )

            # duration
            try:
                from mutagen import _file as MutaFile
                audio_file = MutaFile.File(path)
                self.current_song_length = float(audio_file.info.length) if audio_file and audio_file.info else 0.0
            except Exception:
                self.current_song_length = 0.0

        except Exception as e:
            l.critical(f"Error playing {name}: {e}")


    def stop_song(self):
        self.audio.stop()
        self.progress.set(0)
        self.time_label.configure(text="00:00 / 00:00")
        self.now_playing_label.configure(text="")
        self.song_info_label.configure(text="")
        self.album_art_label.configure(image=self._album_art_img)  # or load_album_art("") to reset


    def _on_seek(self, event):
        # guard
        p = self.current_song_path
        if not p or not self.current_song_length or self.current_song_length <= 0:
            return

        w = self.progress.winfo_width()
        if w <= 0:
            return

        fraction = max(0.0, min(event.x / w, 1.0))
        new_time = fraction * self.current_song_length

        try:
            import pygame
            pygame.mixer.music.stop()
            pygame.mixer.music.play(start=new_time)
            try:
                # keep backend state in sync
                self.audio._is_playing = True
            except Exception:
                pass

            self.play_start_offset = float(new_time)

            # immediate UI reflect
            self.progress.set(min(max(fraction, 0.0), 1.0))
            elapsed = int(self.play_start_offset)
            total = int(self.current_song_length)
            self.time_label.configure(text=f"{elapsed//60:02}:{elapsed%60:02} / {total//60:02}:{total%60:02}")
        except Exception as e:
            l.critical("Seek failed:", e)

    def _update_progress(self):
        try:
            if self.is_playing() and self.current_song_length > 0:
                pos_since_play = self.audio.get_pos_seconds()
                elapsed_total = self.play_start_offset + max(0.0, pos_since_play)

                if elapsed_total < 0:
                    elapsed_total = 0.0
                if elapsed_total > self.current_song_length:
                    elapsed_total = self.current_song_length

                fraction = min(max(elapsed_total / self.current_song_length, 0.0), 1.0)
                self.progress.set(fraction)

                elapsed = int(elapsed_total)
                total = int(self.current_song_length)
                self.time_label.configure(
                    text=f"{elapsed//60:02}:{elapsed%60:02} / {total//60:02}:{total%60:02}"
                )
        finally:
            self.after(100, self._update_progress)



    def setup_complete(self):
        """Called once the user finishes the initial setup."""
        try:
            if getattr(self, "initSideWindow", None):
                if hasattr(self.initSideWindow, "_pl_cache"):
                    self.initSideWindow._pl_cache = None

                if hasattr(self.initSideWindow, "_refresh_playlists"):
                    self.initSideWindow._refresh_playlists(force=True)

            # Let pages know user data changed (optional)
            for frame in getattr(self, "frames", {}).values():
                hook = getattr(frame, "on_setup_changed", None)
                if callable(hook):
                    hook()

            # Route to your home page
            self.show_frame(Main)   # or showLibrary / showPlaylist

            # Kick the heartbeat once immediately so UI updates without waiting 100ms
            if hasattr(self, "_heartbeat"):
                self.after(0, self._heartbeat)

            # Also broadcast a virtual event for any widget that wants to bind directly
            self.event_generate("<<UserDataChanged>>", when="tail")

        except Exception as e:
            l.critical("setup_complete error:", e)


    def _heartbeat(self):
        try:
            if getattr(self, "initSideWindow", None):
                tick = getattr(self.initSideWindow, "refresh_tick", None)
                if callable(tick):
                    tick()
        except Exception:
            pass

        try:
            page = getattr(self, "current_page", None)
            tick = getattr(page, "refresh_tick", None)
            if callable(tick):
                tick()
        except Exception:
            pass

        self.after(100, self._heartbeat)



    def _update_volume(self, v):
        self.volume_level = v
        if not self.muted_state:
            self.audio.set_volume(v/100)

        gud.addUserData({"settings": {"volume": v}})



    def show_playlist(self, pid, pdata, songs_data):
        # Destroy any previous playlist view if it exists
        if showPlaylist in self.frames:
            self.frames[showPlaylist].destroy()
            del self.frames[showPlaylist]

        # Create a new instance
        frame = showPlaylist(
            parent=self.initMainWindow,
            controller=self,
            playlist_id=pid,
            playlist_data=pdata,
            songs_data=songs_data
        )

        self.frames[showPlaylist] = frame
        frame.place(x=0, y=0, relwidth=1, relheight=1)

        # Animate transition
        self.show_frame(showPlaylist, animate=False, direction='right')
        self.current_page = frame


if __name__ == '__main__':
    try:
        app = App()
        app.mainloop()

    
    except Exception as mainE:
        l.critical(mainE, exc_info=True)