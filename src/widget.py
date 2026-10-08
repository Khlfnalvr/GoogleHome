"""Google Home taskbar widget for Windows 11.

Sits in the taskbar's notification area. Left-click the house icon to open a
flyout with lamp and AC controls; right-click for Quit.
"""

import ctypes
import math
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

WIDTH, HEIGHT = 360, 470
MARGIN = 12
APP_NAME = "GoogleHomeWidget"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# Colors are (light mode, dark mode).
BG = ("#f3f3f3", "#1f1f1f")
CARD = ("#ffffff", "#2b2b2b")
BORDER = ("#e3e3e3", "#383838")
CONTROL = ("#ebebeb", "#3a3a3a")
CONTROL_HOVER = ("#dedede", "#474747")
TEXT = ("#1f1f1f", "#f2f2f2")
MUTED = ("#666666", "#a6a6a6")
ON_ACCENT = ("#ffffff", "#202124")  # text and icons on an accent color
ACCENT = {"lamp": ("#f29900", "#fdd663"), "ac": ("#1a73e8", "#8ab4f8")}
ACCENT_HOVER = ("#1765cc", "#aecbfa")
ICON_OFF = ("#6b6b6b", "#b0b0b0")
FAN_SPEEDS = ("auto", "low", "medium", "high")


def tray_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon([(32, 4), (62, 32), (54, 32), (54, 60), (10, 60), (10, 32), (2, 32)], fill=(66, 133, 244))
    draw.rectangle([26, 40, 38, 60], fill=(255, 255, 255))
    return img


def draw_bulb(draw: ImageDraw.ImageDraw, color: str) -> None:
    draw.ellipse([22, 6, 74, 58], fill=color)
    draw.polygon([(32, 46), (64, 46), (60, 68), (36, 68)], fill=color)
    draw.rounded_rectangle([36, 73, 60, 80], radius=3, fill=color)
    draw.rounded_rectangle([41, 85, 55, 92], radius=3, fill=color)


def draw_snowflake(draw: ImageDraw.ImageDraw, color: str) -> None:
    for angle in range(0, 360, 60):
        a = math.radians(angle + 30)
        draw.line([(48, 48), (48 + 42 * math.cos(a), 48 + 42 * math.sin(a))], fill=color, width=7)
        mx, my = 48 + 26 * math.cos(a), 48 + 26 * math.sin(a)
        for side in (-1, 1):
            b = a + side * math.radians(45)
            draw.line([(mx, my), (mx + 15 * math.cos(b), my + 15 * math.sin(b))], fill=color, width=6)


def draw_switch_on(draw: ImageDraw.ImageDraw, track: str, knob: str) -> None:
    draw.rounded_rectangle([0, 0, 183, 103], radius=52, fill=track)
    draw.ellipse([92, 12, 172, 92], fill=knob)


def draw_switch_off(draw: ImageDraw.ImageDraw, color: str) -> None:
    draw.rounded_rectangle([4, 4, 179, 99], radius=48, outline=color, width=8)
    draw.ellipse([24, 24, 80, 80], fill=color)


def icon(size: tuple[int, int], draw_fn, *colors: tuple[str, str]) -> ctk.CTkImage:
    """Draw at 4x size, in light- and dark-mode colors. Each color is a (light, dark) pair."""
    images = []
    for mode in (0, 1):
        img = Image.new("RGBA", (size[0] * 4, size[1] * 4), (0, 0, 0, 0))
        draw_fn(ImageDraw.Draw(img), *(color[mode] for color in colors))
        images.append(img)
    return ctk.CTkImage(*images, size=size)


def font(size: int, bold: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(size=size, weight="bold" if bold else "normal")


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
        super().__init__(fg_color=BG)
        self.settings = home.load_config()
        self.creds = home.load_credentials()
        self.events: queue.Queue = queue.Queue()  # callbacks to run on the UI thread
        self.tray: pystray.Icon | None = None
        self.hidden_at = 0.0
        self.keep_open = False
        self.jobs: dict[str, str] = {}  # debounced commands, by name
        # Per device: (image when off, image when on)
        self.glyphs = {
            device: (icon((24, 24), draw, ICON_OFF), icon((24, 24), draw, ON_ACCENT))
            for device, draw in (("lamp", draw_bulb), ("ac", draw_snowflake))
        }
        self.toggles = {
            device: (
                icon((46, 26), draw_switch_off, ICON_OFF),
                icon((46, 26), draw_switch_on, ACCENT[device], ON_ACCENT),
            )
            for device in ACCENT
        }
        self.badges: dict[str, tuple[ctk.CTkFrame, ctk.CTkLabel]] = {}
        self.subtitles: dict[str, ctk.CTkLabel] = {}
        self.switches: dict[str, ctk.CTkButton] = {}

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
        row.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(row, text=text, font=font(20, bold=True), text_color=TEXT).pack(side="left")
        if button:
            ctk.CTkButton(
                row, text=button, width=36, height=36, corner_radius=18, font=font(18), command=command,
                fg_color="transparent", text_color=TEXT, hover_color=CONTROL_HOVER,
            ).pack(side="right")

    def _button(self, parent, text: str, command, primary: bool = True) -> ctk.CTkButton:
        if primary:
            colors = {"fg_color": ACCENT["ac"], "hover_color": ACCENT_HOVER, "text_color": ON_ACCENT}
        else:
            colors = {
                "fg_color": "transparent", "hover_color": CONTROL_HOVER, "text_color": TEXT,
                "border_width": 1, "border_color": BORDER,
            }
        return ctk.CTkButton(
            parent, text=text, command=command, height=40, corner_radius=20, font=font(14, bold=True), **colors
        )

    def _round_button(self, parent, text: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=text, width=40, height=40, corner_radius=20, font=font(20), command=command,
            fg_color=CONTROL, hover_color=CONTROL_HOVER, text_color=TEXT,
        )

    def _device_card(self, page: ctk.CTkFrame, device: str, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(page, corner_radius=16, fg_color=CARD, border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=16, pady=6)
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(14, 12))
        badge = ctk.CTkFrame(top, width=40, height=40, corner_radius=20)
        badge.pack(side="left")
        glyph = ctk.CTkLabel(badge, text="")
        glyph.place(relx=0.5, rely=0.5, anchor="center")
        self.badges[device] = (badge, glyph)
        names = ctk.CTkFrame(top, fg_color="transparent")
        names.pack(side="left", padx=12)
        ctk.CTkLabel(names, text=title, font=font(15, bold=True), text_color=TEXT, height=20).pack(anchor="w")
        self.subtitles[device] = ctk.CTkLabel(names, text="", font=font(12), text_color=MUTED, height=16)
        self.subtitles[device].pack(anchor="w")
        self.switches[device] = ctk.CTkButton(
            top, text="", width=46, height=26, border_spacing=0, fg_color="transparent", hover=False,
            command=lambda: self.toggle_power(device),
        )
        self.switches[device].pack(side="right")
        return card

    def _caption(self, card: ctk.CTkFrame, text: str) -> ctk.CTkLabel:
        """A small label row; returns the right-aligned value label."""
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14)
        ctk.CTkLabel(row, text=text, font=font(12), text_color=MUTED, height=18).pack(side="left")
        value = ctk.CTkLabel(row, text="", font=font(12, bold=True), text_color=TEXT, height=18)
        value.pack(side="right")
        return value

    def _status(self, page: ctk.CTkFrame) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            page, text="", font=font(12), text_color=MUTED, justify="left", wraplength=WIDTH - 32
        )
        label.pack(anchor="w", padx=18, pady=(6, 12))
        return label

    # Pages

    def _build_login(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self, fg_color="transparent")
        self._header(page, "Google Home")
        ctk.CTkLabel(
            page, justify="left", text_color=MUTED, font=font(13),
            text="Sign in with your Google account to control\nyour Google Home lamp and AC from here.",
        ).pack(anchor="w", padx=16, pady=(4, 16))
        self.sign_in_button = self._button(page, "Sign in with Google", self.sign_in)
        self.sign_in_button.pack(fill="x", padx=16)
        self.login_status = self._status(page)
        return page

    def _build_home(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self, fg_color="transparent")
        self._header(page, "Google Home", "⚙", lambda: self.show_page("settings"))

        lamp = self._device_card(page, "lamp", "Lamp")
        self.brightness_label = self._caption(lamp, "Brightness")
        self.brightness = ctk.CTkSlider(
            lamp, from_=5, to=100, number_of_steps=19, height=20,
            fg_color=CONTROL, progress_color=ACCENT["lamp"],
            button_color=ACCENT["lamp"], button_hover_color=ACCENT["lamp"],
            command=self.change_brightness,
        )
        self.brightness.pack(fill="x", padx=8, pady=(6, 16))

        ac = self._device_card(page, "ac", "Air conditioner")
        temp = ctk.CTkFrame(ac, fg_color="transparent")
        temp.pack(fill="x", padx=14, pady=(0, 12))
        self._round_button(temp, "−", lambda: self.change_temp(-1)).pack(side="left")
        self.temp_label = ctk.CTkLabel(temp, text="", font=font(30, bold=True), text_color=TEXT)
        self.temp_label.pack(side="left", expand=True)
        self._round_button(temp, "+", lambda: self.change_temp(1)).pack(side="right")

        self._caption(ac, "Fan speed")
        chips = ctk.CTkFrame(ac, fg_color="transparent")
        chips.pack(fill="x", padx=11, pady=(6, 16))
        self.fan_chips = {}
        for speed in FAN_SPEEDS:
            self.fan_chips[speed] = ctk.CTkButton(
                chips, text=speed.capitalize(), width=60, height=32, corner_radius=16, font=font(12, bold=True),
                command=lambda s=speed: self.set_fan(s),
            )
            self.fan_chips[speed].pack(side="left", expand=True, fill="x", padx=3)

        self.status = self._status(page)
        return page

    def _build_settings(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self, fg_color="transparent")
        self._header(page, "Settings", "←", lambda: self.show_page("home"))
        ctk.CTkLabel(
            page, text="Device names, exactly as in the Google Home app:", font=font(12), text_color=MUTED
        ).pack(anchor="w", padx=16, pady=(0, 4))
        self.lamp_entry = self._entry(page, "Lamp")
        self.ac_entry = self._entry(page, "AC")
        self.autostart_switch = ctk.CTkSwitch(
            page, text="Start with Windows", text_color=TEXT, progress_color=ACCENT["ac"]
        )
        self.autostart_switch.pack(anchor="w", padx=16, pady=16)
        self._button(page, "Save", self.save_settings).pack(fill="x", padx=16, pady=(0, 8))
        self._button(page, "Sign out", self.sign_out, primary=False).pack(fill="x", padx=16)
        self.settings_status = self._status(page)
        return page

    def _entry(self, page: ctk.CTkFrame, label: str) -> ctk.CTkEntry:
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row, text=label, width=50, anchor="w", text_color=TEXT).pack(side="left")
        entry = ctk.CTkEntry(
            row, height=36, corner_radius=10, fg_color=CARD, border_color=BORDER, text_color=TEXT
        )
        entry.pack(side="left", fill="x", expand=True)
        return entry

    def show_page(self, name: str) -> None:
        for page in self.pages.values():
            page.pack_forget()
        if name == "home":
            for device in self.switches:
                self.subtitles[device].configure(text=self.settings[device])
                self._show_power(device)
            self.brightness.set(self.settings["lamp_brightness"])
            self.brightness_label.configure(text=f"{self.settings['lamp_brightness']}%")
            self.temp_label.configure(text=f"{self.settings['ac_temp']}°")
            self._show_fan()
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

    def _show_power(self, device: str) -> None:
        on = bool(self.settings[f"{device}_on"])
        self.switches[device].configure(image=self.toggles[device][on])
        badge, glyph = self.badges[device]
        badge.configure(fg_color=ACCENT[device] if on else CONTROL)
        glyph.configure(image=self.glyphs[device][on])

    def _show_fan(self) -> None:
        for speed, chip in self.fan_chips.items():
            if speed == self.settings["ac_fan"]:
                chip.configure(fg_color=ACCENT["ac"], hover_color=ACCENT["ac"], text_color=ON_ACCENT)
            else:
                chip.configure(fg_color=CONTROL, hover_color=CONTROL_HOVER, text_color=TEXT)

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

    def toggle_power(self, device: str) -> None:
        on = not self.settings[f"{device}_on"]
        self.settings[f"{device}_on"] = on
        self._save()
        self._show_power(device)
        self.run_command(f"turn {'on' if on else 'off'} {self.settings[device]}")

    def change_brightness(self, value: float) -> None:
        self.settings["lamp_brightness"] = round(value)
        self.brightness_label.configure(text=f"{self.settings['lamp_brightness']}%")
        self._debounce("brightness", self._send_brightness)

    def _send_brightness(self) -> None:
        self.settings["lamp_on"] = True  # Google turns the lamp on when brightness is set
        self._save()
        self._show_power("lamp")
        self.run_command(f"set {self.settings['lamp']} brightness to {self.settings['lamp_brightness']}%")

    def change_temp(self, delta: int) -> None:
        self.settings["ac_temp"] = max(16, min(30, self.settings["ac_temp"] + delta))
        self.temp_label.configure(text=f"{self.settings['ac_temp']}°")
        self._debounce("temp", self._send_temp)

    def _send_temp(self) -> None:
        self._save()
        self.run_command(f"set {self.settings['ac']} to {self.settings['ac_temp']} degrees")

    def set_fan(self, speed: str) -> None:
        self.settings["ac_fan"] = speed
        self._save()
        self._show_fan()
        self.run_command(f"set {self.settings['ac']} fan speed to {speed}")

    def _debounce(self, name: str, fn) -> None:
        """Wait until the user stops clicking or dragging, then call fn once."""
        if name in self.jobs:
            self.after_cancel(self.jobs[name])

        def fire() -> None:
            del self.jobs[name]
            fn()

        self.jobs[name] = self.after(800, fire)

    def _save(self) -> None:
        try:
            home.save_config(self.settings)
        except OSError:
            pass

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
