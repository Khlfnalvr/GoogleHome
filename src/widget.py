"""Google Home taskbar widget for Windows 11.

Sits in the taskbar's notification area. Left-click the house icon to open a
flyout with lamp and AC controls; right-click for Quit.
"""

import ctypes
import queue
import sys
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw

import home

WIDTH, HEIGHT = 340, 380
MARGIN = 12
MUTED = ("gray40", "gray65")
APP_NAME = "GoogleHomeWidget"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def tray_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon([(32, 4), (62, 32), (54, 32), (54, 60), (10, 60), (10, 32), (2, 32)], fill=(66, 133, 244))
    draw.rectangle([26, 40, 38, 60], fill=(255, 255, 255))
    return img


# --- Windows integration ----------------------------------------------------

def work_area(win: ctk.CTk) -> tuple[int, int, int, int]:
    """Screen area not covered by the taskbar, in physical pixels."""
    if sys.platform == "win32":
        from ctypes import wintypes

        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
        return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()


def style_native(win: ctk.CTk) -> None:
    """Windows 11 rounded corners, and bring the borderless flyout to the front."""
    if sys.platform != "win32":
        return
    hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
    corner = ctypes.c_int(2)  # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
    ctypes.windll.user32.SetForegroundWindow(hwnd)


def autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{Path(__file__).resolve()}"'


def get_autostart() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_command())
        elif get_autostart():
            winreg.DeleteValue(key, APP_NAME)


# --- Flyout -----------------------------------------------------------------

class Flyout(ctk.CTk):
    # Borderless window: stop CustomTkinter re-showing it to recolor a title bar.
    _deactivate_windows_window_header_manipulation = True

    def __init__(self) -> None:
        super().__init__()
        self.settings = home.load_config()
        self.creds = home.load_credentials()
        self.events: queue.Queue = queue.Queue()  # callbacks to run on the UI thread
        self.tray: pystray.Icon | None = None
        self.hidden_at = 0.0
        self.keep_open = False
        self.temp_job: str | None = None

        self.title("Google Home")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.withdraw()
        self.bind("<FocusOut>", lambda _e: self.after(150, self._hide_if_unfocused))
        self.bind("<Escape>", lambda _e: self.hide())

        self.pages = {
            "login": self._build_login(),
            "home": self._build_home(),
            "settings": self._build_settings(),
        }
        self.show_page("home" if self.creds else "login")
        self.after(50, self._pump_events)

    # Layout helpers

    def _header(self, page: ctk.CTkFrame, text: str, button: str = "", command=None) -> None:
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(14, 8))
        ctk.CTkLabel(row, text=text, font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        if button:
            ctk.CTkButton(
                row, text=button, width=32, command=command, fg_color="transparent",
                text_color=("gray10", "gray90"), hover_color=("gray80", "gray25"),
            ).pack(side="right")

    def _card(self, page: ctk.CTkFrame) -> tuple[ctk.CTkFrame, ctk.CTkLabel]:
        card = ctk.CTkFrame(page, corner_radius=10)
        card.pack(fill="x", padx=16, pady=6)
        title = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=14, weight="bold"))
        title.pack(anchor="w", padx=12, pady=(8, 4))
        return card, title

    def _row(self, card: ctk.CTkFrame) -> ctk.CTkFrame:
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 10))
        return row

    def _on_off(self, card: ctk.CTkFrame, device: str) -> None:
        row = self._row(card)
        for word, pad in (("on", (0, 4)), ("off", (4, 0))):
            ctk.CTkButton(
                row, text=word.capitalize(),
                command=lambda w=word: self.run_command(f"turn {w} {self.settings[device]}"),
            ).pack(side="left", expand=True, fill="x", padx=pad)

    def _status(self, page: ctk.CTkFrame) -> ctk.CTkLabel:
        label = ctk.CTkLabel(page, text="", text_color=MUTED, justify="left", wraplength=WIDTH - 32)
        label.pack(anchor="w", padx=16, pady=(6, 12))
        return label

    # Pages

    def _build_login(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self, fg_color="transparent")
        self._header(page, "Google Home")
        ctk.CTkLabel(
            page, justify="left",
            text="Sign in with your Google account to control\nyour Google Home lamp and AC from here.",
        ).pack(anchor="w", padx=16, pady=(4, 16))
        self.sign_in_button = ctk.CTkButton(page, text="Sign in with Google", height=40, command=self.sign_in)
        self.sign_in_button.pack(fill="x", padx=16)
        self.login_status = self._status(page)
        return page

    def _build_home(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self, fg_color="transparent")
        self._header(page, "Google Home", "⚙", lambda: self.show_page("settings"))

        lamp, self.lamp_title = self._card(page)
        self._on_off(lamp, "lamp")

        ac, self.ac_title = self._card(page)
        self._on_off(ac, "ac")
        temp = self._row(ac)
        ctk.CTkButton(temp, text="−", width=44, command=lambda: self.change_temp(-1)).pack(side="left")
        self.temp_label = ctk.CTkLabel(temp, text="", font=ctk.CTkFont(size=20, weight="bold"))
        self.temp_label.pack(side="left", expand=True)
        ctk.CTkButton(temp, text="+", width=44, command=lambda: self.change_temp(1)).pack(side="right")

        self.status = self._status(page)
        return page

    def _build_settings(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self, fg_color="transparent")
        self._header(page, "Settings", "←", lambda: self.show_page("home"))
        ctk.CTkLabel(page, text="Device names, exactly as in the Google Home app:", text_color=MUTED).pack(
            anchor="w", padx=16, pady=(0, 4)
        )
        self.lamp_entry = self._entry(page, "Lamp")
        self.ac_entry = self._entry(page, "AC")
        self.autostart_switch = ctk.CTkSwitch(page, text="Start with Windows")
        self.autostart_switch.pack(anchor="w", padx=16, pady=14)
        ctk.CTkButton(page, text="Save", command=self.save_settings).pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkButton(
            page, text="Sign out", command=self.sign_out, fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"), hover_color=("gray80", "gray25"),
        ).pack(fill="x", padx=16)
        self.settings_status = self._status(page)
        return page

    def _entry(self, page: ctk.CTkFrame, label: str) -> ctk.CTkEntry:
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row, text=label, width=50, anchor="w").pack(side="left")
        entry = ctk.CTkEntry(row)
        entry.pack(side="left", fill="x", expand=True)
        return entry

    def show_page(self, name: str) -> None:
        for page in self.pages.values():
            page.pack_forget()
        if name == "home":
            self.lamp_title.configure(text=f"Lamp · {self.settings['lamp']}")
            self.ac_title.configure(text=f"AC · {self.settings['ac']}")
            self.temp_label.configure(text=f"{self.settings['ac_temp']}°")
        elif name == "settings":
            for entry, key in ((self.lamp_entry, "lamp"), (self.ac_entry, "ac")):
                entry.delete(0, "end")
                entry.insert(0, self.settings[key])
            if get_autostart():
                self.autostart_switch.select()
            else:
                self.autostart_switch.deselect()
            self.settings_status.configure(text="")
        self.pages[name].pack(fill="both", expand=True)

    # Actions

    def sign_in(self) -> None:
        if home.find_client_secret() is None:
            self.keep_open = True
            path = filedialog.askopenfilename(
                parent=self, title="Choose your Google OAuth client_secret.json", filetypes=[("JSON", "*.json")]
            )
            self.keep_open = False
            self.focus_force()
            if not path:
                return
            try:
                home.import_client_secret(path)
            except (OSError, ValueError) as err:
                self.login_status.configure(text=str(err))
                return
        self.sign_in_button.configure(state="disabled")
        self.login_status.configure(text="Finish signing in with Google in your browser…")
        self._submit(self._signed_in, home.sign_in)

    def _signed_in(self, future: Future) -> None:
        self.sign_in_button.configure(state="normal")
        try:
            self.creds = future.result()
        except Exception as err:
            self.login_status.configure(text=f"Sign-in failed: {err}")
            return
        self.login_status.configure(text="")
        self.status.configure(text="Signed in.")
        self.show_page("home")
        self.show()

    def sign_out(self) -> None:
        home.sign_out()
        self.creds = None
        self.login_status.configure(text="Signed out.")
        self.show_page("login")

    def save_settings(self) -> None:
        self.settings["lamp"] = self.lamp_entry.get().strip() or home.DEFAULT_CONFIG["lamp"]
        self.settings["ac"] = self.ac_entry.get().strip() or home.DEFAULT_CONFIG["ac"]
        try:
            home.save_config(self.settings)
            set_autostart(bool(self.autostart_switch.get()))
        except OSError as err:
            self.settings_status.configure(text=f"Could not save: {err}")
            return
        self.show_page("home")

    def change_temp(self, delta: int) -> None:
        self.settings["ac_temp"] = max(16, min(30, self.settings["ac_temp"] + delta))
        self.temp_label.configure(text=f"{self.settings['ac_temp']}°")
        # Wait until the user stops clicking, then send one command.
        if self.temp_job:
            self.after_cancel(self.temp_job)
        self.temp_job = self.after(800, self._send_temp)

    def _send_temp(self) -> None:
        self.temp_job = None
        try:
            home.save_config(self.settings)
        except OSError:
            pass
        self.run_command(f"set {self.settings['ac']} to {self.settings['ac_temp']} degrees")

    def run_command(self, query: str) -> None:
        if self.creds is None:
            self.show_page("login")
            return
        self.status.configure(text=f"“{query}”…")
        self._submit(self._command_done, home.send_command, self.creds, query, self.settings["language"])

    def _command_done(self, future: Future) -> None:
        try:
            self.status.configure(text=future.result())
        except home.SignInRequired as err:
            home.sign_out()
            self.creds = None
            self.login_status.configure(text=str(err))
            self.show_page("login")
        except Exception as err:
            self.status.configure(text=f"Error: {err}")

    # Threading: blocking work runs in a background thread; results come back via the queue.

    def _submit(self, on_done, fn, *args) -> None:
        future: Future = Future()

        def work() -> None:
            try:
                future.set_result(fn(*args))
            except Exception as err:
                future.set_exception(err)
            self.events.put(lambda: on_done(future))

        threading.Thread(target=work, daemon=True).start()

    def _pump_events(self) -> None:
        while not self.events.empty():
            self.events.get_nowait()()
        self.after(50, self._pump_events)

    # Show / hide

    def toggle(self) -> None:
        if self.state() != "withdrawn":
            self.hide()
        elif time.monotonic() - self.hidden_at > 0.4:  # ignore the tray click that just closed it
            self.show()

    def show(self) -> None:
        scale = ctk.ScalingTracker.get_window_scaling(self)
        _left, _top, right, bottom = work_area(self)
        x = right - round((WIDTH + MARGIN) * scale)
        y = bottom - round((HEIGHT + MARGIN) * scale)
        self.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.focus_force()
        style_native(self)

    def hide(self) -> None:
        self.withdraw()
        self.hidden_at = time.monotonic()

    def _hide_if_unfocused(self) -> None:
        try:
            focused = self.focus_get()
        except KeyError:  # focus is in a native dialog
            focused = True
        if focused is None and not self.keep_open and self.state() != "withdrawn":
            self.hide()

    # Tray

    def start_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Open", lambda: self.events.put(self.toggle), default=True),
            pystray.MenuItem("Quit", lambda: self.events.put(self.quit_app)),
        )
        self.tray = pystray.Icon(APP_NAME, tray_image(), "Google Home", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def quit_app(self) -> None:
        if self.tray:
            self.tray.stop()
        self.destroy()


def main() -> None:
    ctk.set_appearance_mode("system")
    app = Flyout()
    if "--check" in sys.argv:  # build smoke test: construct and show the UI, then exit
        app.update()
        app.show()
        app.update()
        app.quit_app()
        return
    app.start_tray()
    if app.creds is None:
        app.after(300, app.show)  # first run: open the sign-in flyout right away
    app.mainloop()


if __name__ == "__main__":
    main()
