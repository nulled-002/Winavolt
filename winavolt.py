#!/usr/bin/env python3
"""
winavolt.py - classic Winamp 2.x skin front end for the Spotify desktop client.

Spotify runs in the background; this window only displays and controls it
through MPRIS (playerctl).

    sudo apt install playerctl python3-tk python3-pil.imagetk
    ./winavolt.py                       # uses the theme set in the config file
    ./winavolt.py ~/skins/Other.wsz     # one-off override

Config: ~/.local/share/winavolt/config.ini (created on first run), e.g.
    [winavolt]
    theme = ~/Downloads/theme.wsz
Install:  ./winavolt.py --install   (adds the 'winavolt' command + app-menu launcher)
Other options: --config FILE --scale 1|2|3 --shade --pos x,y --no-top --player NAME

Mouse:   buttons, seek bar, volume slider, wheel = volume, click the time
         to toggle remaining time, drag anywhere else to move the window,
         right-click or the menu button (top-left) for the menu.
Keys:    z prev  x play  c pause  v stop  b next  s shuffle  r repeat
         Left/Right seek 5s   Up/Down volume   e equalizer   p playlist
         (keys need window focus)
"""
import argparse, atexit, configparser, io, json, os, re, shutil, signal, subprocess, sys, threading, time
import unicodedata, zipfile
import tkinter as tk
import tkinter.font as tkfont
from PIL import Image, ImageTk

# ------------------------------------------------------------------ args
ap = argparse.ArgumentParser(description="Winamp-skinned Spotify remote")
CONF_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "winavolt")
DEFAULT_CONFIG = os.path.join(CONF_DIR, "config.ini")
DEFAULT_CFG_TEXT = """# winavolt configuration
# Command-line options override anything set here.
[winavolt]
# Winamp skin: a .wsz/.zip file or an unpacked skin folder (~ is expanded)
theme = ~/Downloads/theme.wsz
# 1, 2 or 3 (window size multiplier)
scale = 1
# MPRIS player to control (see: playerctl -l)
player = spotify
# initial window position: x,y
position = 100,100
# false = a normal (managed) window that other windows can cover; needs 'xprop'
always_on_top = true
# playlist look: classic = compact Winamp-style window, one line per track
#                big     = tall window, two big lines per track
playlist_style = classic
# rows shown (classic: at least this many, the window grows to fit; big: 3-8)
playlist_rows = 4
# playlist text size in pixels (0 = auto: 10 for classic)
playlist_font_size = 0
# font for the playlist (empty = whatever the skin says); list fonts with: fc-list : family | sort -u
playlist_font =
# start in shade (mini) mode
shade = false
"""

ap = argparse.ArgumentParser(description="Winamp-skinned Spotify remote")
ap.add_argument("skin", nargs="?",
                help="skin to use instead of the 'theme' set in the config file")
ap.add_argument("--config", default=DEFAULT_CONFIG, help=f"config file (default {DEFAULT_CONFIG})")
ap.add_argument("--scale", type=int, choices=(1, 2, 3))
ap.add_argument("--player", help="MPRIS player name")
ap.add_argument("--pos", help="initial window position x,y")
ap.add_argument("--shade", action="store_true", help="start in shade (mini) mode")
ap.add_argument("--no-shade", action="store_true")
ap.add_argument("--top", action="store_true", help="stay on top")
ap.add_argument("--no-top", action="store_true", help="don't stay on top")
ap.add_argument("--install", action="store_true",
                help="install the 'winavolt' command and an application-menu launcher")
ap.add_argument("--uninstall", action="store_true", help="remove what --install added")
args = ap.parse_args()

# ---- install / uninstall (command in ~/.local/bin + .desktop launcher + icon)
_HOME = os.path.expanduser("~")
_BIN = os.path.join(_HOME, ".local", "bin", "winavolt")
_DESKTOP = os.path.join(_HOME, ".local", "share", "applications", "winavolt.desktop")
_ICON = os.path.join(_HOME, ".local", "share", "icons", "hicolor", "256x256", "apps", "winavolt.png")


def _make_icon(path):
    from PIL import ImageDraw
    S = 256
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, S - 8, S - 8), radius=44, fill=(24, 36, 78, 255),
                        outline=(120, 140, 200, 255), width=6)
    d.rounded_rectangle((22, 22, S - 22, 80), radius=18, fill=(40, 62, 130, 255))
    bolt = [(150, 34), (66, 148), (120, 148), (94, 226), (190, 106), (136, 106), (172, 34)]
    d.polygon(bolt, fill=(255, 196, 30, 255), outline=(255, 120, 0, 255))
    im.save(path)


def install():
    for p in (_BIN, _DESKTOP, _ICON):
        os.makedirs(os.path.dirname(p), exist_ok=True)
    me = os.path.abspath(__file__)
    if not (os.path.exists(_BIN) and os.path.samefile(me, _BIN)):
        shutil.copy2(me, _BIN)
    os.chmod(_BIN, 0o755)
    if not os.path.exists(_ICON):      # keep a custom icon if you replaced it
        _make_icon(_ICON)
    with open(_DESKTOP, "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=Winavolt\n"
                "GenericName=Music Player\n"
                "Comment=Winamp-skinned remote for Spotify\n"
                f'Exec="{_BIN}"\nIcon=winavolt\nTerminal=false\n'
                "Categories=AudioVideo;Audio;Player;\n"
                "Keywords=winamp;spotify;player;music;\nStartupWMClass=Winavolt\n")
    for cmd in (["update-desktop-database", os.path.dirname(_DESKTOP)],
                ["gtk-update-icon-cache", "-f", "-t", os.path.join(_HOME, ".local", "share", "icons", "hicolor")]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, capture_output=True)
    print(f"Installed command:  {_BIN}\nInstalled launcher: {_DESKTOP}\nInstalled icon:     {_ICON}")
    if os.path.join(_HOME, ".local", "bin") not in os.environ.get("PATH", "").split(":"):
        print("\nNote: ~/.local/bin is not in your PATH. Add this to ~/.bashrc:\n"
              '    export PATH="$HOME/.local/bin:$PATH"')
    print("\nRun it with:  winavolt      (or find 'Winavolt' in your application menu)")


def uninstall():
    for p in (_BIN, _DESKTOP, _ICON):
        try:
            os.remove(p)
            print("Removed", p)
        except FileNotFoundError:
            pass
    print("Config and history in ~/.local/share/winavolt were left alone.")


if args.install:
    install()
    sys.exit(0)
if args.uninstall:
    uninstall()
    sys.exit(0)

# ---- config file (~/.local/share/winavolt/config.ini by default)
cfg_path = os.path.expanduser(args.config)
if not os.path.exists(cfg_path):
    try:
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        with open(cfg_path, "w") as _f:
            _f.write(DEFAULT_CFG_TEXT)
        print(f"Created default config: {cfg_path}")
    except OSError as ex:
        print(f"Could not create {cfg_path}: {ex}", file=sys.stderr)
cfg = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(" #", " ;"))
try:
    cfg.read(cfg_path)
except configparser.Error as ex:
    sys.exit(f"Bad config file {cfg_path}: {ex}")


def cget(key, default):
    return cfg.get("winavolt", key, fallback=default).strip()


def cbool(key, default):
    try:
        return cfg.getboolean("winavolt", key, fallback=default)
    except ValueError:
        return default


args.skin = os.path.expandvars(os.path.expanduser(args.skin or cget("theme", "")))
if not args.skin:
    sys.exit(f"No theme set. Edit {cfg_path} and set:  theme = ~/Downloads/theme.wsz")
if not os.path.exists(args.skin):
    sys.exit(f"Theme not found: {args.skin}\nSet 'theme' in {cfg_path} or pass a skin path.")
if args.scale is None:
    try:
        args.scale = int(cget("scale", "1"))
    except ValueError:
        args.scale = 1
    if args.scale not in (1, 2, 3):
        sys.exit(f"scale in {cfg_path} must be 1, 2 or 3")
args.player = args.player or cget("player", "spotify")
args.pos = args.pos or cget("position", "100,100")
args.shade = False if args.no_shade else (args.shade or cbool("shade", False))
args.no_top = True if args.no_top else (False if args.top else not cbool("always_on_top", True))
args.pl_font = cget("playlist_font", "")
try:
    args.pl_rows = max(3, min(12, int(cget("playlist_rows", "4"))))
except ValueError:
    args.pl_rows = 4
args.pl_style = cget("playlist_style", "classic").lower()
if args.pl_style not in ("classic", "big"):
    args.pl_style = "classic"
try:
    args.pl_font_size = max(0, min(40, int(cget("playlist_font_size", "0"))))
except ValueError:
    args.pl_font_size = 0

if not shutil.which("playerctl"):
    sys.exit("playerctl not found. Install it: sudo apt install playerctl")

K = args.scale
PLAYER = args.player


# ------------------------------------------------------------------ skin
class Skin:
    def __init__(self, path):
        self.files = {}
        if os.path.isdir(path):
            for dp, _, fs in os.walk(path):
                for f in fs:
                    self.files[f.lower()] = os.path.join(dp, f)
            self._read = lambda p: open(p, "rb").read()
        else:
            z = zipfile.ZipFile(path)
            for n in z.namelist():
                base = n.replace("\\", "/").split("/")[-1].lower()
                if not base or base.startswith("._") or "__macosx" in n.lower():
                    continue
                self.files[base] = n
            self._read = z.read

    def get(self, *names):
        for n in names:
            k = self.files.get(n)
            if k:
                try:
                    return Image.open(io.BytesIO(self._read(k))).convert("RGB")
                except Exception:
                    pass
        return None


try:
    skin = Skin(args.skin)
except Exception as ex:
    sys.exit(f"Could not open skin: {ex}")

MAIN = skin.get("main.bmp")
NUMS = skin.get("numbers.bmp", "nums_ex.bmp")
if MAIN is None or NUMS is None:
    sys.exit("That doesn't look like a classic Winamp skin (main.bmp/numbers.bmp missing).")

# ------------------------------------------------------------------ window
# always_on_top = true  -> borderless "override-redirect" window (always above others).
# always_on_top = false -> a normal managed window with its decorations stripped, so other
# windows can cover it, it shows in the taskbar and gets real keyboard focus.
MANAGED = bool(args.no_top)
if MANAGED and not shutil.which("xprop"):
    print("winavolt: always_on_top = false needs 'xprop' (sudo apt install x11-utils); "
          "staying on top instead.", file=sys.stderr)
    MANAGED = False
    args.no_top = False


def strip_decor(win, skip_taskbar=False):
    """Remove titlebar/borders from a managed Tk window via _MOTIF_WM_HINTS."""
    hint = ["-f", "_MOTIF_WM_HINTS", "32c", "-set", "_MOTIF_WM_HINTS", "2, 0, 0, 0, 0"]
    ok = False
    try:
        ok = subprocess.run(["xprop", "-id", win.wm_frame(), *hint], capture_output=True,
                            timeout=3).returncode == 0
    except Exception:
        pass
    if skip_taskbar:   # must be set before the window is first mapped
        try:
            subprocess.run(["xprop", "-id", win.wm_frame(), "-f", "_NET_WM_STATE", "32a",
                            "-set", "_NET_WM_STATE",
                            "_NET_WM_STATE_SKIP_TASKBAR, _NET_WM_STATE_SKIP_PAGER"],
                           capture_output=True, timeout=3)
        except Exception:
            pass
    try:   # belt and braces once the window is mapped
        title = win.title()
        win.after(400, lambda: subprocess.Popen(["xprop", "-name", title, *hint],
                                                stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL))
    except Exception:
        pass
    return ok


root = tk.Tk(className="Winavolt")
root.title("Winavolt")
if MANAGED:
    root.withdraw()
else:
    root.overrideredirect(True)
    if not args.no_top:
        root.attributes("-topmost", True)
cv = tk.Canvas(root, width=275 * K, height=116 * K, highlightthickness=0, bd=0)
cv.pack()

KEEP = []  # keep PhotoImage references alive


def spr(sheet, x, y, w, h):
    """Crop a sprite out of a skin sheet and make it a (scaled) PhotoImage."""
    if sheet is None:
        return None
    im = sheet.crop((x, y, x + w, y + h))
    if K != 1:
        im = im.resize((w * K, h * K), Image.NEAREST)
    ph = ImageTk.PhotoImage(im)
    KEEP.append(ph)
    return ph


def pil_photo(im):
    if K != 1:
        im = im.resize((im.width * K, im.height * K), Image.NEAREST)
    return ImageTk.PhotoImage(im)


def put(img, x, y, tag=""):
    if img is None:
        return None
    return cv.create_image(x * K, y * K, image=img, anchor="nw",
                           tags=(tag,) if tag else ())


def setimg(item, img):
    if item is not None and img is not None:
        cv.itemconfig(item, image=img)


M = {"shade": args.shade}   # current mode
# Main-window position in the same coordinates we pass to geometry().  We own it: docked
# windows are always placed from this, never from what the WM reports (which is late during
# drags and can differ by frame offsets in managed mode).  "off" = WM-reported client origin
# minus this position, learned once the window has settled.
POS = {"x": 0, "y": 0, "off": None, "t": 0.0}
D = {}                      # current mouse drag
EMPTY = dict(ok=False, status="", vol=0.0, pos=0, length=0, artist="", title="",
             shuffle="Off", loop="None", ts=0.0, uri="")
STATE = dict(EMPTY, ts=time.monotonic())
HOLD = {"shuffle": 0.0, "loop": 0.0}   # briefly trust optimistic values
POKE = threading.Event()
REMAINING = {"on": False}

# ------------------------------------------------------------------ playerctl
def pc(*a, timeout=3):
    try:
        r = subprocess.run(["playerctl", "-p", PLAYER, *a], capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def run(*a):
    """Fire a playerctl command in the background, then refresh state."""
    def go():
        pc(*a)
        POKE.set()
    threading.Thread(target=go, daemon=True).start()


FMT = ("{{status}}|{{volume}}|{{position}}|{{mpris:length}}|{{mpris:trackid}}"
       "|{{artist}}|{{title}}")


def poller():
    global STATE
    while True:
        out = pc("metadata", "--format", FMT)
        p = out.split("|", 6)
        now = time.monotonic()
        if len(p) == 7:
            try:
                tid = p[4]
                uri = ("spotify:track:" + tid.rsplit("/", 1)[-1]
                       if tid.startswith("/com/spotify/track/") else "")
                new = dict(ok=True, status=p[0], vol=float(p[1] or 0),
                           pos=int(float(p[2] or 0)), length=int(float(p[3] or 0)),
                           artist=p[5], title=p[6], ts=now, uri=uri)
            except ValueError:
                new = None
            if new:
                old = STATE
                new["shuffle"] = old["shuffle"] if now < HOLD["shuffle"] else (pc("shuffle") or "Off")
                new["loop"] = old["loop"] if now < HOLD["loop"] else (pc("loop") or "None")
                STATE = new
        else:
            STATE = dict(EMPTY, ts=now)
        POKE.wait(0.5)
        POKE.clear()


# ------------------------------------------------------------------ title bar / background
cv_main_bg = put(spr(MAIN, 0, 0, 275, 116), 0, 0, "full")

TB = skin.get("titlebar.bmp")
bar_full = spr(TB, 27, 0, 275, 14) if TB else spr(MAIN, 0, 0, 275, 14)
bar_shade = spr(TB, 27, 29, 275, 14) if TB else spr(MAIN, 0, 0, 275, 14)
bar_item = put(bar_full, 0, 0)

# ------------------------------------------------------------------ buttons
BTNS = []


class Btn:
    def __init__(self, x, y, w, h, normal, pressed, cmd, tag="", sel=None, selp=None):
        self.rect, self.cmd, self.tag = (x, y, w, h), cmd, tag
        self.sel = self.down = False
        self.imgs = {(False, False): normal,
                     (False, True): pressed or normal,
                     (True, False): sel or normal,
                     (True, True): selp or pressed or normal}
        self.item = put(normal, x, y, tag)
        BTNS.append(self)

    def show(self):
        cv.itemconfig(self.item, image=self.imgs[(self.sel, self.down)])

    def hit(self, x, y):
        rx, ry, w, h = self.rect
        return rx <= x < rx + w and ry <= y < ry + h

    def visible(self):
        return self.tag == "" or self.tag == ("shade" if M["shade"] else "full")


def btn(x, y, w, h, normal, pressed, cmd, tag="", sel=None, selp=None):
    if normal is None:
        return None
    return Btn(x, y, w, h, normal, pressed, cmd, tag, sel, selp)


# title bar buttons (both modes)
btn(6, 3, 9, 9, spr(TB, 0, 0, 9, 9), spr(TB, 0, 9, 9, 9), lambda: show_menu())
btn(244, 3, 9, 9, spr(TB, 9, 0, 9, 9), spr(TB, 9, 9, 9, 9), lambda: minimize())
btn(254, 3, 9, 9, spr(TB, 0, 18, 9, 9), spr(TB, 9, 18, 9, 9), lambda: toggle_shade())
btn(264, 3, 9, 9, spr(TB, 18, 0, 9, 9), spr(TB, 18, 9, 9, 9), lambda: root.destroy())

# transport
CB = skin.get("cbuttons.bmp")
for sx, w, x, a in [(0, 23, 16, ("previous",)), (23, 23, 39, ("play",)),
                    (46, 23, 62, ("play-pause",)), (69, 23, 85, ("stop",)),
                    (92, 22, 108, ("next",))]:
    btn(x, 88, w, 18, spr(CB, sx, 0, w, 18), spr(CB, sx, 18, w, 18),
        (lambda a=a: do_cmd(a)), "full")
btn(136, 89, 22, 16, spr(CB, 114, 0, 22, 16), spr(CB, 114, 16, 22, 16),
    lambda: open_dialog(), "full")

# shuffle / repeat (real) and EQ / PL (decorative: Spotify has neither)
SR = skin.get("shufrep.bmp")


def toggle_shuffle():
    global STATE
    new = "Off" if STATE["shuffle"] == "On" else "On"
    STATE = {**STATE, "shuffle": new}
    HOLD["shuffle"] = time.monotonic() + 1.5
    run("shuffle", new)


def toggle_repeat():
    global STATE
    new = "Playlist" if STATE["loop"] == "None" else "None"
    STATE = {**STATE, "loop": new}
    HOLD["loop"] = time.monotonic() + 1.5
    run("loop", new)


B_SHUF = btn(164, 89, 47, 15, spr(SR, 28, 0, 47, 15), spr(SR, 28, 15, 47, 15),
             toggle_shuffle, "full", spr(SR, 28, 30, 47, 15), spr(SR, 28, 45, 47, 15))
B_REP = btn(210, 89, 28, 15, spr(SR, 0, 0, 28, 15), spr(SR, 0, 15, 28, 15),
            toggle_repeat, "full", spr(SR, 0, 30, 28, 15), spr(SR, 0, 45, 28, 15))
B_EQ = btn(219, 58, 23, 12, spr(SR, 0, 61, 23, 12), spr(SR, 46, 61, 23, 12),
           lambda: EQW.toggle(), "full", spr(SR, 0, 73, 23, 12), spr(SR, 46, 73, 23, 12))
B_PL = btn(242, 58, 23, 12, spr(SR, 23, 61, 23, 12), spr(SR, 69, 61, 23, 12),
           lambda: PLW.toggle(), "full", spr(SR, 23, 73, 23, 12), spr(SR, 69, 73, 23, 12))

# ------------------------------------------------------------------ time digits
DIG = [spr(NUMS, i * 9, 0, 9, 13) for i in range(10)]
digit_items = [put(DIG[0], x, 26) for x in (48, 60, 78, 90)]
try:
    minus_color = "#%02x%02x%02x" % NUMS.getpixel((8 * 9 + 4, 6))
except Exception:
    minus_color = "#00ff00"
minus_item = cv.create_rectangle(36 * K, 32 * K, 41 * K, 33 * K, fill=minus_color,
                                 outline="", state="hidden")
LAST = {"neg": False}

# ------------------------------------------------------------------ skin font + marquees
FONT = skin.get("text.bmp") or Image.new("RGB", (155, 18))
TXT_BG = FONT.getpixel((28 * 5 + 2, 3))
CELLS = {}
for i, c in enumerate('abcdefghijklmnopqrstuvwxyz"@'):
    CELLS[c] = (i, 0)
for i, c in enumerate("0123456789\u2026.:()-'!_+\\/[]^&%,=$#"):
    CELLS[c] = (i, 1)
CELLS["?"], CELLS["*"] = (3, 2), (4, 2)
PUNCT = {0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-"}
GAP = "  ***  "


def norm(s):
    s = s.translate(PUNCT)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def render(text):
    im = Image.new("RGB", (max(1, len(text) * 5), 6), TXT_BG)
    for i, ch in enumerate(text):
        c = CELLS.get(ch)
        if c:
            im.paste(FONT.crop((c[0] * 5, c[1] * 6, c[0] * 5 + 5, c[1] * 6 + 6)), (i * 5, 0))
    return im


class Marquee:
    def __init__(self, x, y, width, tag):
        self.W, self.off, self.text, self.ph = width, 0, None, None
        self.item = cv.create_image(x * K, y * K, anchor="nw", tags=(tag,))
        self.set("")

    def set(self, text):
        if text == self.text:
            return
        self.text, self.off = text, 0
        t = norm(text)
        im = render(t)
        self.long = im.width > self.W
        if self.long:
            one = render(t + GAP)
            self.period = one.width
            self.src = Image.new("RGB", (self.period * 2, 6), TXT_BG)
            self.src.paste(one, (0, 0))
            self.src.paste(one, (self.period, 0))
        else:
            self.src = Image.new("RGB", (self.W, 6), TXT_BG)
            self.src.paste(im, (0, 0))
        self.draw()

    def step(self, n):
        if self.long:
            self.off = (self.off + n) % self.period
            self.draw()

    def draw(self):
        self.ph = pil_photo(self.src.crop((self.off, 0, self.off + self.W, 6)))
        cv.itemconfig(self.item, image=self.ph)


main_mq = Marquee(111, 24, 154, "full")
shade_mq = Marquee(52, 4, 190, "shade")
time_mq = Marquee(18, 4, 30, "shade")

# ------------------------------------------------------------------ indicators
PP = skin.get("playpaus.bmp")
pp_imgs = {"Playing": spr(PP, 0, 0, 9, 9), "Paused": spr(PP, 9, 0, 9, 9),
           "Stopped": spr(PP, 18, 0, 9, 9)}
pp_item = put(pp_imgs["Stopped"], 24, 28, "full")
MS = skin.get("monoster.bmp")
st_on, st_off = spr(MS, 0, 0, 29, 12), spr(MS, 0, 12, 29, 12)
mo_on, mo_off = spr(MS, 29, 0, 27, 12), spr(MS, 29, 12, 27, 12)
stereo_item = put(st_off, 239, 41, "full")
mono_item = put(mo_off, 212, 41, "full")
LAST_PP = {"v": None}

# ------------------------------------------------------------------ seek bar
PB = skin.get("posbar.bmp")
seek_img = (spr(PB, 248, 0, 29, 10), spr(PB, 278, 0, 29, 10))
seek_item = put(seek_img[0], 16, 72)
if seek_item is not None:
    cv.itemconfig(seek_item, state="hidden")

# ------------------------------------------------------------------ volume (+ decorative balance)
VOL = skin.get("volume.bmp")
vol_bg = [spr(VOL, 0, 15 * n, 68, 13) for n in range(28)]
vol_knob = (spr(VOL, 15, 422, 14, 11), spr(VOL, 0, 422, 14, 11))
vol_item = put(vol_bg[0], 107, 57, "full")
vol_knob_item = put(vol_knob[0], 107, 58, "full")

BAL = skin.get("balance.bmp")
if BAL is not None:
    put(spr(BAL, 9, 0, 38, 13), 177, 57, "full")
    put(spr(BAL, 15, 422, 14, 11), 189, 58, "full")


def show_volume(v):
    if vol_item is None:
        return
    v = max(0.0, min(1.0, v))
    setimg(vol_item, vol_bg[round(v * 27)])
    cv.coords(vol_knob_item, (107 + 54 * v) * K, 58 * K)


# ------------------------------------------------------------------ time display
def set_time(secs, neg=False):
    m, s = divmod(max(0, int(secs)), 60)
    m = min(m, 99)
    for it, d in zip(digit_items, (m // 10, m % 10, s // 10, s % 10)):
        setimg(it, DIG[d])
    time_mq.set(("-" if neg else "") + f"{m:02d}:{s:02d}")
    LAST["neg"] = neg


def title_text(st):
    if not st["ok"]:
        return "spotify not running"
    name = " - ".join(x for x in (st["artist"], st["title"]) if x) or "spotify"
    if st["length"]:
        m, s = divmod(st["length"] // 1_000_000, 60)
        name += f" ({m}:{s:02d})"
    return name


tick_n = 0


def tick():
    global tick_n
    tick_n += 1
    st, now = STATE, time.monotonic()
    shade = M["shade"]
    playing, paused = st["status"] == "Playing", st["status"] == "Paused"
    length = st["length"]
    pos = st["pos"] + ((now - st["ts"]) * 1e6 if playing else 0)
    if length:
        pos = min(pos, length)

    t = title_text(st)
    main_mq.set(t)
    shade_mq.set(t)
    if tick_n % 2 == 0:
        main_mq.step(2)
        shade_mq.step(2)

    seeking = D.get("kind") == "seek"
    if not seeking:
        neg = REMAINING["on"] and bool(length)
        set_time(((length - pos) if neg else pos) / 1e6, neg)
        if seek_item is not None:
            if length and not shade:
                cv.coords(seek_item, (16 + pos / length * 219) * K, 72 * K)
                cv.itemconfig(seek_item, state="normal")
            else:
                cv.itemconfig(seek_item, state="hidden")
    blink = paused and not seeking and int(now * 2) % 2 == 0
    digits_on = not shade and not blink
    for it in digit_items:
        if it is not None:
            cv.itemconfig(it, state="normal" if digits_on else "hidden")
    cv.itemconfig(minus_item, state="normal" if (digits_on and LAST["neg"]) else "hidden")

    if D.get("kind") != "vol":
        show_volume(st["vol"])

    status = st["status"] if st["status"] in pp_imgs else "Stopped"
    live = st["ok"] and status in ("Playing", "Paused")
    key = (status, live, st["shuffle"], st["loop"])
    if key != LAST_PP["v"]:
        LAST_PP["v"] = key
        setimg(pp_item, pp_imgs[status])
        setimg(stereo_item, st_on if live else st_off)
        setimg(mono_item, mo_off)
        for b, on in ((B_SHUF, st["shuffle"] == "On"), (B_REP, st["loop"] != "None")):
            if b:
                b.sel = on
                b.show()
    PLW.note_track(st)
    PLW.autoadvance(st, pos, length)
    for b, w in ((B_EQ, EQW), (B_PL, PLW)):
        if b and b.sel != w.visible:
            b.sel = w.visible
            b.show()
    root.after(100, tick)


# ------------------------------------------------------------------ mouse
def on_press(e):
    cv.focus_force()
    D.clear()
    x, y = e.x / K, e.y / K
    for b in BTNS:
        if b.visible() and b.hit(x, y):
            b.down = True
            b.show()
            D.update(kind="btn", btn=b)
            return
    if not M["shade"]:
        if 16 <= x < 264 and 72 <= y < 82 and STATE["length"]:
            D["kind"] = "seek"
            setimg(seek_item, seek_img[1])
            on_motion(e)
            return
        if 107 <= x < 175 and 57 <= y < 70 and vol_item is not None:
            D["kind"] = "vol"
            setimg(vol_knob_item, vol_knob[1])
            on_motion(e)
            return
        if 36 <= x < 99 and 24 <= y < 41:
            REMAINING["on"] = not REMAINING["on"]
            return
    D.update(kind="win", ox=e.x_root - POS["x"], oy=e.y_root - POS["y"])


def on_motion(e):
    k, x = D.get("kind"), e.x / K
    if k == "win":
        move_main(e.x_root - D["ox"], e.y_root - D["oy"])
    elif k == "seek":
        tx = max(16, min(235, x - 14.5))
        D["frac"] = (tx - 16) / 219
        cv.coords(seek_item, tx * K, 72 * K)
        set_time(D["frac"] * STATE["length"] / 1e6)
    elif k == "vol":
        D["frac"] = max(0.0, min(1.0, (x - 114) / 54))
        show_volume(D["frac"])


def on_release(e):
    global STATE
    k = D.pop("kind", None)
    if k == "btn":
        b = D.pop("btn")
        b.down = False
        b.show()
        if b.cmd and b.hit(e.x / K, e.y / K):
            b.cmd()
    elif k == "seek":
        setimg(seek_item, seek_img[0])
        f = D.get("frac", 0.0)
        STATE = {**STATE, "pos": int(f * STATE["length"]), "ts": time.monotonic()}
        run("position", f"{f * STATE['length'] / 1e6:.2f}")
    elif k == "vol":
        setimg(vol_knob_item, vol_knob[0])
        run("volume", f"{D.get('frac', 0.0):.2f}")
    elif k == "win":
        POS["t"] = time.monotonic()
        root.after(1200, learn_offset)
    D.clear()


def on_wheel(e):
    up = getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0
    run("volume", "0.05+" if up else "0.05-")


cv.bind("<ButtonPress-1>", on_press)
cv.bind("<B1-Motion>", on_motion)
cv.bind("<ButtonRelease-1>", on_release)
cv.bind("<Button-4>", on_wheel)
cv.bind("<Button-5>", on_wheel)
cv.bind("<MouseWheel>", on_wheel)
cv.bind("<Button-3>", lambda e: show_menu(e.x_root, e.y_root))

KEYS = {"z": ("previous",), "x": ("play",), "c": ("play-pause",), "v": ("stop",),
        "b": ("next",), "Left": ("position", "5-"), "Right": ("position", "5+"),
        "Up": ("volume", "0.05+"), "Down": ("volume", "0.05-")}


def do_cmd(a):
    """Transport command; Next/Previous follow the playlist being played, if there is one."""
    if a == ("next",) and PLW.step(1):
        return
    if a == ("previous",) and PLW.step(-1):
        return
    run(*a)


def on_key(e):
    if e.keysym in KEYS:
        do_cmd(KEYS[e.keysym])
    elif e.keysym == "s":
        toggle_shuffle()
    elif e.keysym == "r":
        toggle_repeat()
    elif e.keysym == "e":
        EQW.toggle()
    elif e.keysym == "p":
        PLW.toggle()


root.bind("<Key>", on_key)

# ------------------------------------------------------------------ open link dialog
URI_RE = re.compile(r"open\.spotify\.com/(?:intl-[a-z]+/)?"
                    r"(track|album|playlist|artist|episode|show)/([A-Za-z0-9]+)")


def to_uri(s):
    if s.startswith("spotify:"):
        return s
    m = URI_RE.search(s)
    return f"spotify:{m.group(1)}:{m.group(2)}" if m else None


def open_dialog():
    top = tk.Toplevel(root)
    top.title("Open Spotify link")
    top.attributes("-topmost", True)
    tk.Label(top, text="Spotify URI or open.spotify.com link:").pack(padx=12, pady=(12, 4))
    ent = tk.Entry(top, width=52)
    ent.pack(padx=12)
    ent.focus_force()

    def go(_=None):
        uri = to_uri(ent.get().strip())
        top.destroy()
        if uri:
            run("open", uri)

    ent.bind("<Return>", go)
    tk.Button(top, text="Play", command=go).pack(pady=10)


# ------------------------------------------------------------------ menu, shade, minimize
var_shade = tk.BooleanVar(value=args.shade)
var_rem = tk.BooleanVar(value=False)
var_top = tk.BooleanVar(value=not args.no_top)
menu = tk.Menu(root, tearoff=0)


def toggle_shade():
    M["shade"] = not M["shade"]
    var_shade.set(M["shade"])
    apply_mode()


def toggle_remaining():
    REMAINING["on"] = var_rem.get()


def restart(scale, top):
    argv = [sys.executable, os.path.abspath(__file__), args.skin, "--scale", str(scale),
            "--player", PLAYER, "--pos", f"{POS['x']},{POS['y']}",
            "--config", cfg_path,
            "--shade" if M["shade"] else "--no-shade",
            "--top" if top else "--no-top"]
    EQE.stop()
    os.execv(sys.executable, argv)


def rescale():
    restart(2 if K == 1 else 1, var_top.get())


def minimize():
    if not MANAGED:
        root.overrideredirect(False)
    root.iconify()


if not MANAGED:
    root.bind("<Map>", lambda e: (e.widget is root and not root.overrideredirect()
                                  and root.overrideredirect(True)))

menu.add_command(label="Open Spotify link...", command=open_dialog)
menu.add_separator()
menu.add_checkbutton(label="Shade mode", variable=var_shade, command=toggle_shade)
menu.add_checkbutton(label="Time remaining", variable=var_rem,
                     command=toggle_remaining)
menu.add_checkbutton(label="Always on top (restarts)", variable=var_top,
                     command=lambda: restart(K, var_top.get()))
menu.add_command(label="Equalizer", command=lambda: EQW.toggle())
menu.add_command(label="Playlist (play history)", command=lambda: PLW.toggle())
menu.add_command(label="Float / dock equalizer", command=lambda: EQW.toggle_dock())
menu.add_command(label="Float / dock playlist", command=lambda: PLW.toggle_dock())
menu.add_command(label="Switch 1x / 2x (restarts)", command=rescale)
menu.add_separator()
menu.add_command(label="Minimize", command=minimize)
menu.add_command(label="Quit", command=root.destroy)


_POPUP = {"m": None}


def menu_is_open():
    return _POPUP["m"] is not None


def close_menu(_e=None):
    m, _POPUP["m"] = _POPUP["m"], None
    root.unbind_all("<ButtonPress>")
    if m is not None:
        for fn in (m.unpost, m.grab_release):
            try:
                fn()
            except tk.TclError:
                pass


def popup_menu(m, x, y):
    """Post a popup menu so that clicking anywhere else dismisses it.

    On X11, tk_popup() takes a global pointer grab, and that grab is exactly what makes a
    click outside the menu close it.  So it must NOT be released after posting (the usual
    `finally: m.grab_release()` snippet breaks dismissal).  The bindings below are a safety
    net for clicks inside our own windows and for the Escape key."""
    close_menu()
    _POPUP["m"] = m
    name = str(m)

    def away(e):
        w = str(e.widget)
        if w != name and not w.startswith(name + "."):
            close_menu()

    def closed(_e=None):
        if _POPUP["m"] is m:
            _POPUP["m"] = None
            root.unbind_all("<ButtonPress>")

    m.bind("<Unmap>", closed, add="+")
    m.bind("<Escape>", close_menu, add="+")
    root.bind_all("<ButtonPress>", away, add="+")
    m.tk_popup(x, y)


def show_menu(x=None, y=None):
    if x is None:
        x, y = root.winfo_pointerxy()
    var_rem.set(REMAINING["on"])
    popup_menu(menu, x, y)


def apply_mode():
    shade = M["shade"]
    cv.itemconfig("full", state="hidden" if shade else "normal")
    cv.itemconfig("shade", state="normal" if shade else "hidden")
    h = 14 if shade else 116
    cv.config(height=h * K)
    setimg(bar_item, bar_shade if shade else bar_full)
    resize_root()
    LAST_PP["v"] = None


# ------------------------------------------------------------------ equalizer + playlist windows
from tkinter import messagebox

HIST_PATH = os.path.join(CONF_DIR, "history.json")          # old format, still read for migration
PLAYLISTS_PATH = os.path.join(CONF_DIR, "playlists.json")
os.makedirs(CONF_DIR, exist_ok=True)

EQ_BANDS = [60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000]
EQ_FRAME_REVERSED = False   # flip to True if the slider tracks look upside-down
EQM = skin.get("eqmain.bmp")
PLEDIT = skin.get("pledit.bmp")
EQ_PRESETS = {
    "Flat": [0] * 10,
    "Rock": [5, 4, 3, 1, -1, -1, 1, 3, 4, 5],
    "Pop": [-1, 2, 4, 5, 3, 0, -1, -1, -2, -2],
    "Dance": [5, 4, 2, 0, 0, -2, -3, -3, 0, 0],
    "Bass boost": [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
    "Treble boost": [0, 0, 0, 0, 0, 1, 3, 5, 6, 6],
    "Vocal": [-2, -3, -3, 1, 3, 3, 3, 1, 0, -1],
    "Classical": [0, 0, 0, 0, 0, 0, -3, -3, -3, -5],
}


def sh(*cmd, timeout=6):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def sink_names():
    return [l.split("\t")[1] for l in sh("pactl", "list", "short", "sinks").splitlines()
            if "\t" in l]


def move_streams(sink):
    """Move Spotify's playback streams to `sink` (default-sink change usually does it anyway)."""
    try:
        data = json.loads(sh("pactl", "-f", "json", "list", "sink-inputs") or "[]")
    except ValueError:
        return
    for s in data:
        pr = s.get("properties", {}) or {}
        who = (pr.get("application.name", "") + pr.get("application.process.binary", "")).lower()
        if "spotify" in who:
            sh("pactl", "move-sink-input", str(s.get("index")), sink)


def find_node(name):
    try:
        objs = json.loads(sh("pw-dump", timeout=8) or "[]")
    except ValueError:
        return None
    for o in objs:
        props = (o.get("info", {}) or {}).get("props", {}) or {}
        if o.get("type") == "PipeWire:Interface:Node" and props.get("node.name") == name:
            return o["id"]
    return None


CONF_TMPL = '''context.properties = { log.level = 0 }
context.spa-libs = {
    audio.convert.* = audioconvert/libspa-audioconvert
    support.* = support/libspa-support
}
context.modules = [
    { name = libpipewire-module-rt args = { nice.level = -11 } flags = [ ifexists nofail ] }
    { name = libpipewire-module-protocol-native }
    { name = libpipewire-module-client-node }
    { name = libpipewire-module-adapter }
    { name = libpipewire-module-filter-chain
      args = {
        node.description = "Winavolt EQ"
        media.name = "Winavolt EQ"
        filter.graph = {
            nodes = [ @NODES@ ]
            links = [ @LINKS@ ]
            inputs = [ "preL:In" "preR:In" ]
            outputs = [ "eqL10:Out" "eqR10:Out" ]
        }
        audio.channels = 2
        audio.position = [ FL FR ]
        capture.props = { node.name = "winavolt_eq" media.class = Audio/Sink }
        playback.props = { node.name = "winavolt_eq_out" node.passive = true target.object = "@TARGET@" }
      }
    }
]
'''


class EqEngine:
    """Runs a PipeWire filter-chain (10x peaking biquads + preamp) as a helper process,
    routes the default sink through it, and updates gains live with pw-cli."""

    def __init__(self):
        self.proc = self.node = self.orig = None
        self.pending = None
        self.worker = None
        self.lock = threading.Lock()

    @staticmethod
    def available():
        return all(shutil.which(c) for c in ("pipewire", "pw-dump", "pw-cli", "pactl"))

    def conf(self, gains, pre, target):
        nodes, links = [], []
        mult = 10 ** (pre / 20)
        for ch in "LR":
            nodes.append(f'{{ type = builtin name = pre{ch} label = linear '
                         f'control = {{ Mult = {mult:.5f} Add = 0.0 }} }}')
            prev = f"pre{ch}"
            for i, (f, g) in enumerate(zip(EQ_BANDS, gains)):
                nm = f"eq{ch}{i + 1}"
                nodes.append(f'{{ type = builtin name = {nm} label = bq_peaking '
                             f'control = {{ Freq = {float(f):.1f} Q = 1.4 Gain = {g:.2f} }} }}')
                links.append(f'{{ output = "{prev}:Out" input = "{nm}:In" }}')
                prev = nm
        return (CONF_TMPL.replace("@NODES@", " ".join(nodes))
                .replace("@LINKS@", " ".join(links)).replace("@TARGET@", target))

    def start(self, gains, pre):
        with self.lock:
            if self.proc:
                return True, ""
            cur = sh("pactl", "get-default-sink")
            if not cur or cur.startswith("winavolt_eq"):
                cur = next((s for s in sink_names() if not s.startswith("winavolt_eq")), "")
            if not cur:
                return False, "Couldn't find an output device (pactl list short sinks)."
            self.orig = cur
            path = os.path.join(CONF_DIR, "eq.conf")
            with open(path, "w") as f:
                f.write(self.conf(gains, pre, cur))
            self.proc = subprocess.Popen(["pipewire", "-c", path],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            t0, node = time.time(), None
            while time.time() - t0 < 6:
                if self.proc.poll() is not None:
                    self.proc = None
                    return False, ("The PipeWire filter-chain process exited.\n"
                                   f"Try running:  pipewire -c {path}")
                node = find_node("winavolt_eq")
                if node:
                    break
                time.sleep(0.25)
            if not node:
                self._kill()
                return False, "The EQ node never appeared in PipeWire."
            self.node = node
            sh("pactl", "set-default-sink", "winavolt_eq")
            move_streams("winavolt_eq")
            return True, ""

    def _kill(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
        self.proc = self.node = None

    def stop(self):
        with self.lock:
            if not self.proc:
                return
            if self.orig:
                sh("pactl", "set-default-sink", self.orig)
                move_streams(self.orig)
            self._kill()

    def push(self, gains, pre):
        if not self.node:
            return
        self.pending = (list(gains), pre)
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._pump, daemon=True)
        self.worker.start()

    def _pump(self):
        while self.pending and self.node:
            g, pre = self.pending
            self.pending = None
            params = []
            for ch in "LR":
                params += [f'"pre{ch}:Mult"', f"{10 ** (pre / 20):.5f}"]
                for i, v in enumerate(g):
                    params += [f'"eq{ch}{i + 1}:Gain"', f"{v:.2f}"]
            sh("pw-cli", "s", str(self.node), "Props",
               "{ params = [ " + " ".join(params) + " ] }", timeout=5)
            time.sleep(0.03)


EQE = EqEngine()


# ------------------------------------------------------------------ equalizer / playlist panels
# Docked panels live INSIDE the main window: one X window, so the whole stack moves in perfect
# lockstep no matter how slowly the window manager handles moves.  Any panel can also be
# floated into a window of its own (right-click it, or use the main menu).
def set_top():
    for w in (root, EQW.top, PLW.top):
        if w is not None:
            w.attributes("-topmost", var_top.get())


def stack_h():
    """Height of the main window in base pixels: player (or shade bar) + docked panels."""
    return (14 if M["shade"] else 116) + sum(w.H for w in (EQW, PLW) if w.visible and w.docked)


def resize_root():
    root.geometry(f"{275 * K}x{stack_h() * K}")


def restack():
    for w in (EQW, PLW):
        if w.slot is not None:
            w.slot.pack_forget()
    for w in (EQW, PLW):
        if w.slot is not None and w.visible and w.docked:
            w.slot.pack(side="top")
    resize_root()


def move_main(x, y):
    POS.update(x=x, y=y, t=time.monotonic())
    root.geometry(f"+{x}+{y}")


def learn_offset():
    if POS["off"] is None:
        POS["off"] = (root.winfo_rootx() - POS["x"], root.winfo_rooty() - POS["y"])


def sync_main_position(_e=None):
    """Keep POS right when the window manager moves the window on its own (keyboard move,
    clamping to the work area, tiling).  Ignored while dragging and for 1s after our own
    move, so a late report of our own move is never mistaken for an external one."""
    if POS["off"] is None or D.get("kind") == "win" or time.monotonic() - POS["t"] < 1.0:
        return
    nx = root.winfo_rootx() - POS["off"][0]
    ny = root.winfo_rooty() - POS["off"][1]
    if abs(nx - POS["x"]) > 2 or abs(ny - POS["y"]) > 2:
        POS.update(x=nx, y=ny)


class SubWin:
    W, H = 275, 116
    TITLE = "Winavolt"

    def __init__(self):
        self.top = self.cv = self.slot = None   # floating Toplevel | canvas | docked frame
        self.visible = False
        self.docked = True
        self.drag = None
        self.px = self.py = 0       # position of the floating window (our own coordinates)
        self.pend_open = False      # was a menu open when the current press started?

    def host(self):
        """Any live widget belonging to this panel (for menus, timers, dialogs)."""
        return self.top if self.top is not None else self.cv

    def put(self, img, x, y, **kw):
        return self.cv.create_image(x * K, y * K, image=img, anchor="nw", **kw)

    def _bind(self):
        self.cv.bind("<ButtonPress-1>", self._press)
        self.cv.bind("<B1-Motion>", self._motion)
        self.cv.bind("<ButtonRelease-1>", self._release)
        self.cv.bind("<Button-3>", self.panel_menu)

    def make_docked(self):
        self.slot = tk.Frame(root, width=self.W * K, height=self.H * K, bd=0,
                             highlightthickness=0)
        self.slot.pack_propagate(False)
        self.cv = tk.Canvas(self.slot, width=self.W * K, height=self.H * K,
                            highlightthickness=0, bd=0)
        self.cv.pack()
        self._bind()
        self.build()

    def make_window(self):
        self.top = tk.Toplevel(root, class_="Winavolt")   # same class: panel groups it with the player
        self.top.title(self.TITLE)
        if MANAGED:
            try:
                self.top.attributes("-type", "utility")   # keeps it out of the taskbar
            except tk.TclError:
                pass
            self.top.withdraw()
            strip_decor(self.top, skip_taskbar=True)
        else:
            self.top.overrideredirect(True)
            self.top.attributes("-topmost", var_top.get())
        self.cv = tk.Canvas(self.top, width=self.W * K, height=self.H * K,
                            highlightthickness=0, bd=0)
        self.cv.pack()
        self._bind()
        self.build()

    def teardown(self):
        w = self.top if self.top is not None else self.slot
        if w is not None:
            w.destroy()
        self.top = self.cv = self.slot = None
        self.visible = False
        self.drag = None
        self.anim_on = False        # lets an animated panel restart after a rebuild

    def toggle(self):
        self.hide() if self.visible else self.show()

    def show(self):
        if self.cv is None:
            if not self.can_build():
                return
            if self.docked:
                self.make_docked()
            else:
                if self.px == 0 and self.py == 0:
                    x, y = self.slot_origin()
                    self.px, self.py = x + 30 * K, y + 30 * K
                self.make_window()
        self.visible = True
        if self.docked:
            restack()
        else:
            self.top.geometry(f"{self.W * K}x{self.H * K}+{self.px}+{self.py}")
            self.top.deiconify()
        self.on_show()

    def hide(self):
        self.visible = False
        if self.cv is not None:
            if self.docked:
                self.slot.pack_forget()
                restack()
            else:
                self.top.withdraw()

    def slot_origin(self):
        """Screen position the panel has (or would have) when docked under the player."""
        y = POS["y"] + (14 if M["shade"] else 116) * K
        for w in (EQW, PLW):
            if w is self:
                break
            if w.visible and w.docked:
                y += w.H * K
        return POS["x"], y

    def toggle_dock(self):
        """Float the panel into its own window, or dock it back under the player."""
        was_visible = self.visible
        if self.cv is None:                     # never built yet: just remember the choice
            self.docked = not self.docked
            return
        if self.docked:
            x, y = self.slot_origin()
            self.teardown()
            self.docked = False
            self.px, self.py = x + 30 * K, y + 30 * K
        else:
            self.teardown()
            self.docked = True
        restack()
        if was_visible:
            self.show()

    def can_build(self):
        return True

    def on_show(self):
        pass

    def panel_menu(self, e):
        m = tk.Menu(self.host(), tearoff=0)
        self.extra_menu(m)
        m.add_command(label="Float in its own window" if self.docked else "Dock under the player",
                      command=lambda: root.after(10, self.toggle_dock))
        m.add_command(label="Close", command=lambda: root.after(10, self.hide))
        popup_menu(m, e.x_root, e.y_root)

    def extra_menu(self, m):
        pass

    # --- mouse plumbing: subclasses implement click/drag_item/release.  Docked panels drag
    # the whole stack (the main window); floating ones just move themselves.
    def _press(self, e):
        self.cv.focus_force()
        if self.click(e.x / K, e.y / K, e):
            return
        if self.docked:
            D.clear()
            D.update(kind="win", ox=e.x_root - POS["x"], oy=e.y_root - POS["y"])
        else:
            self.drag = (e.x_root - self.px, e.y_root - self.py)

    def _motion(self, e):
        if self.drag_item(e):
            return
        if self.docked:
            if D.get("kind") == "win":
                on_motion(e)
        elif self.drag:
            nx, ny = e.x_root - self.drag[0], e.y_root - self.drag[1]
            self.px, self.py = nx, ny
            self.top.geometry(f"+{nx}+{ny}")

    def _release(self, e):
        if self.docked:
            if D.get("kind") == "win":
                on_release(e)
        else:
            self.drag = None
        self.release(e)

    def click(self, x, y, e):
        return False

    def drag_item(self, e):
        return False

    def release(self, e):
        pass


def inside(x, y, r):
    return r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]


# ------------------------------------------------------------------ equalizer window
class EqWin(SubWin):
    TITLE = "Winavolt EQ"
    CTRL = {"close": (264, 3, 9, 9), "on": (14, 18, 26, 12), "presets": (217, 18, 44, 12)}

    def __init__(self):
        super().__init__()
        self.gains = [0.0] * 10
        self.pre = 0.0
        self.on = False
        self.pend = None
        self.sl = None
        self._preset_menu_open = False
        self._preset_menu_pending = False
        self._preset_menu = None

    def can_build(self):
        if EQM is None:
            messagebox.showinfo("Equalizer", "This skin has no eqmain.bmp.")
            return False
        return True

    def build(self):
        self.pend = None
        self.sl = None
        self._preset_menu_open = self._preset_menu_pending = False   # a rebuild destroys any open menu
        self._preset_menu = None
        self.put(spr(EQM, 0, 0, 275, 116), 0, 0)
        self.put(spr(EQM, 0, 134, 275, 14), 0, 0)
        self.close_imgs = (spr(EQM, 0, 116, 9, 9), spr(EQM, 0, 125, 9, 9))
        self.close_item = self.put(self.close_imgs[0], 264, 3)
        self.on_imgs = {(False, False): spr(EQM, 10, 119, 26, 12),
                        (False, True): spr(EQM, 128, 119, 26, 12),
                        (True, False): spr(EQM, 69, 119, 26, 12),
                        (True, True): spr(EQM, 187, 119, 26, 12)}
        self.on_item = self.put(self.on_imgs[(False, False)], 14, 18)
        self.put(spr(EQM, 36, 119, 32, 12), 39, 18)          # AUTO (decorative)
        self.pre_imgs = (spr(EQM, 224, 164, 44, 12), spr(EQM, 224, 176, 44, 12))
        self.pre_item = self.put(self.pre_imgs[0], 217, 18)
        self.frames = [spr(EQM, 13 + 15 * (n % 14), 164 + 65 * (n // 14), 14, 63)
                       for n in range(28)]
        self.thumbs = (spr(EQM, 0, 164, 11, 11), spr(EQM, 0, 176, 11, 11))
        self.put(spr(EQM, 0, 294, 113, 19), 86, 17)
        self.pre_line = self.put(spr(EQM, 0, 314, 113, 1), 86, 26)
        self.sliders = []
        for x in [21] + [78 + 18 * i for i in range(10)]:
            bg = self.put(self.frames[0], x, 38)
            th = self.put(self.thumbs[0], x + 1, 38)
            self.sliders.append((x, bg, th))
        for n in range(11):
            self.draw_slider(n)
        self.draw_graph()
        self.refresh_on()

    # --- drawing
    def val(self, n):
        return self.pre if n == 0 else self.gains[n - 1]

    def draw_slider(self, n, pressed=False):
        x, bg, th = self.sliders[n]
        frac = (self.val(n) + 12) / 24
        frame = round(frac * 27)
        if EQ_FRAME_REVERSED:
            frame = 27 - frame
        self.cv.itemconfig(bg, image=self.frames[frame])
        self.cv.coords(th, (x + 1) * K, (38 + round((1 - frac) * 52)) * K)
        self.cv.itemconfig(th, image=self.thumbs[1 if pressed else 0])

    def draw_graph(self):
        self.cv.delete("graph")
        pts = [(87 + i * 111 / 9, 17 + 1 + (12 - g) / 24 * 17) for i, g in enumerate(self.gains)]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            row = max(0, min(18, int(y2 - 17)))
            try:
                col = "#%02x%02x%02x" % EQM.getpixel((115, 294 + row))
            except Exception:
                col = "#00ff00"
            self.cv.create_line(x1 * K, y1 * K, x2 * K, y2 * K, fill=col, width=K, tags="graph")
        self.cv.coords(self.pre_line, 86 * K, (17 + round((12 - self.pre) / 24 * 18)) * K)

    def refresh_on(self, down=False):
        self.cv.itemconfig(self.on_item, image=self.on_imgs[(self.on, down)])

    def set_down(self, name, flag):
        if name == "close":
            self.cv.itemconfig(self.close_item, image=self.close_imgs[1 if flag else 0])
        elif name == "on":
            self.refresh_on(flag)
        elif name == "presets":
            self.cv.itemconfig(self.pre_item, image=self.pre_imgs[1 if flag else 0])

    # --- values
    def set_value(self, n, v):
        v = max(-12.0, min(12.0, v))
        if abs(v) < 0.5:
            v = 0.0
        if n == 0:
            self.pre = v
        else:
            self.gains[n - 1] = v
        self.draw_slider(n, True)
        self.draw_graph()
        if self.on:
            EQE.push(self.gains, self.pre)

    def apply_preset(self, vals):
        self.gains = [float(v) for v in vals]
        for n in range(1, 11):
            self.draw_slider(n)
        self.draw_graph()
        if self.on:
            EQE.push(self.gains, self.pre)

    def toggle_on(self):
        if self.on:
            self.on = False
            self.refresh_on()
            threading.Thread(target=EQE.stop, daemon=True).start()
            return
        if not EQE.available():
            messagebox.showerror("Equalizer", "Needs pipewire, pw-cli, pw-dump and pactl in PATH.",
                                 parent=self.host())
            return
        self.on = True
        self.refresh_on()

        def go():
            ok, err = EQE.start(self.gains, self.pre)
            if ok:
                EQE.push(self.gains, self.pre)
            else:
                root.after(0, self.failed, err)

        threading.Thread(target=go, daemon=True).start()

    def failed(self, err):
        self.on = False
        self.refresh_on()
        messagebox.showerror("Equalizer", err, parent=self.host())

    def presets_menu(self, x=None, y=None):
        # Ignore duplicate opens while a menu is already posted.  In
        # particular, don't let the release that dismisses a menu reopen it.
        if self._preset_menu_open:
            return
        self._preset_menu_open = True

        m = tk.Menu(self.host(), tearoff=0)
        self._preset_menu = m
        for name, vals in EQ_PRESETS.items():
            m.add_command(label=name, command=lambda v=vals: self.apply_preset(v))

        if x is None or y is None:
            x, y = self.host().winfo_pointerxy()

        def menu_closed(_event=None):
            if self._preset_menu_open:
                self._preset_menu_open = False
                self._preset_menu = None

        m.bind("<Unmap>", menu_closed, add="+")
        popup_menu(m, x, y)

    def _post_presets(self, x, y):
        self._preset_menu_pending = False
        if self.host() is not None and self.host().winfo_exists():
            self.presets_menu(x, y)

    # --- mouse
    def click(self, x, y, e):
        for name, r in self.CTRL.items():
            if inside(x, y, r):
                self.pend = name
                self.pend_open = menu_is_open()
                self.set_down(name, True)
                return True
        for n, (sx, _, _) in enumerate(self.sliders):
            if sx <= x < sx + 14 and 38 <= y < 101:
                self.sl = n
                self.drag_item(e)
                return True
        return False

    def drag_item(self, e):
        if self.sl is None:
            return False
        self.set_value(self.sl, 12 - ((e.y / K - 38 - 5.5) / 52) * 24)
        return True

    def release(self, e):
        if self.pend:
            name, self.pend = self.pend, None
            self.set_down(name, False)
            if inside(e.x / K, e.y / K, self.CTRL[name]):
                if name == "close":
                    self.hide()
                elif name == "on":
                    self.toggle_on()
                else:
                    # Open after this ButtonRelease has fully propagated.
                    # This prevents the popup's dismissal click from being
                    # interpreted as another click on the preset button.
                    if (not self.pend_open and not self._preset_menu_pending
                            and not self._preset_menu_open):
                        self._preset_menu_pending = True
                        self.host().after_idle(
                            lambda px=e.x_root, py=e.y_root: self._post_presets(px, py)
                        )
        if self.sl is not None:
            self.draw_slider(self.sl)
            self.sl = None


# ------------------------------------------------------------------ playlist (play history) window
def ask_text(title, prompt, callback, initial=""):
    """Small non-modal text prompt; calls callback(text) on OK."""
    top = tk.Toplevel(root)
    top.title(title)
    top.attributes("-topmost", True)
    top.geometry(f"+{POS['x'] + 20}+{POS['y'] + 20}")
    tk.Label(top, text=prompt).pack(padx=12, pady=(12, 4))
    ent = tk.Entry(top, width=44)
    ent.pack(padx=12)
    ent.insert(0, initial)
    ent.select_range(0, "end")
    ent.focus_force()

    def ok(_e=None):
        text = ent.get().strip()
        top.destroy()
        callback(text)

    ent.bind("<Return>", ok)
    top.bind("<Escape>", lambda _e: top.destroy())
    row = tk.Frame(top)
    row.pack(pady=10)
    tk.Button(row, text="OK", width=8, command=ok).pack(side="left", padx=4)
    tk.Button(row, text="Cancel", width=8, command=top.destroy).pack(side="left", padx=4)


def fetch_title(uri, done):
    """Best effort: ask Spotify's public oEmbed endpoint for a track's title (in a thread)."""
    def work():
        try:
            import urllib.parse
            import urllib.request
            tid = uri.rsplit(":", 1)[-1]
            url = ("https://open.spotify.com/oembed?url="
                   + urllib.parse.quote(f"https://open.spotify.com/track/{tid}", safe=""))
            with urllib.request.urlopen(url, timeout=6) as r:
                title = json.load(r).get("title", "")
        except Exception:
            return
        if title:
            root.after(0, done, title)

    threading.Thread(target=work, daemon=True).start()


class PlWin(SubWin):
    """Playlist window: the built-in History plus any playlists you create (ADD / REM / LIST)."""
    W, H = 275, 232
    TITLE = "Winavolt Playlist"
    X0, Y0 = 12, 20

    def __init__(self):
        super().__init__()
        self.classic = args.pl_style == "classic"
        if self.classic:
            px = args.pl_font_size or 10
            self.ROWH = px + 4
            tiles = max(2, -(-args.pl_rows * self.ROWH // 29))   # window grows in 29px steps
            self.H = 58 + 29 * tiles
            self.ROWS = (self.H - 38 - self.Y0) // self.ROWH
        else:
            self.ROWS = min(args.pl_rows, 8)
            self.ROWH = (self.H - 38 - self.Y0) // self.ROWS
        self.lists, self.active = self.load()
        self.queue_pl, self.queue_pos, self.adv_key = None, -1, None   # playlist being played through
        self._menu_open, self._menu_t = False, 0.0
        self.cur = self.sel = -1
        self.top_i = 0
        self.last_uri = None
        self.pend = None
        self.last_click = (-1, 0.0)
        self.anim = []
        self.anim_on = False
        self.cols = dict(Normal="#00FF00", Current="#FFFFFF", NormalBG="#000000",
                         SelectedBG="#0000FF", Font="Arial")
        try:
            k = skin.files.get("pledit.txt")
            if k:
                for line in skin._read(k).decode("latin-1").splitlines():
                    if "=" in line:
                        a, b = line.split("=", 1)
                        a, b = a.strip(), b.split(";")[0].strip()
                        if a in self.cols and b:
                            if a != "Font" and re.fullmatch(r"[0-9a-fA-F]{6}", b):
                                b = "#" + b
                            self.cols[a] = b
        except Exception:
            pass
        defaults = dict(Normal="#00FF00", Current="#FFFFFF", NormalBG="#000000",
                        SelectedBG="#0000FF")
        for a, d in defaults.items():
            try:
                root.winfo_rgb(self.cols[a])
            except tk.TclError:
                self.cols[a] = d

    @property
    def items(self):
        return self.lists[self.active]["items"]

    @staticmethod
    def load():
        """-> (playlists, active index).  Picks up the old history.json on first run."""
        def clean(items):
            return [d for d in items if isinstance(d, dict) and d.get("uri")]
        lists, active = [], 0
        try:
            with open(PLAYLISTS_PATH) as f:
                data = json.load(f)
            lists = [dict(name=str(p.get("name") or "Playlist"), history=bool(p.get("history")),
                          items=clean(p.get("items", [])))
                     for p in data.get("playlists", []) if isinstance(p, dict)]
            active = int(data.get("active", 0))
        except Exception:
            try:
                with open(HIST_PATH) as f:
                    lists = [dict(name="History", history=True, items=clean(json.load(f))[-500:])]
            except Exception:
                pass
        if not any(p["history"] for p in lists):
            active = active + 1 if lists else 0
            lists.insert(0, dict(name="History", history=True, items=[]))
        return lists, max(0, min(active, len(lists) - 1))

    def save(self):
        try:
            with open(PLAYLISTS_PATH, "w") as f:
                json.dump(dict(version=2, active=self.active, playlists=self.lists), f)
        except Exception:
            pass

    def compose(self):
        """The skin's playlist frame as RGBA; the list area is left transparent so text
        drawn underneath is clipped by the frame."""
        W, H = self.W, self.H
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        S = PLEDIT
        if S is None:
            from PIL import ImageDraw
            d = ImageDraw.Draw(im)
            g = (70, 70, 70, 255)
            d.rectangle((0, 0, W, self.Y0), fill=g)
            d.rectangle((0, H - 38, W, H), fill=g)
            d.rectangle((0, 0, self.X0, H), fill=g)
            d.rectangle((W - 20, 0, W, H), fill=g)
            return im

        def p(sx, sy, w, h, dx, dy):
            im.paste(S.crop((sx, sy, sx + w, sy + h)).convert("RGBA"), (dx, dy))

        for x in range(25, W - 25, 25):
            p(127, 0, 25, 20, x, 0)
        p(0, 0, 25, 20, 0, 0)
        p(153, 0, 25, 20, W - 25, 0)
        p(26, 0, 100, 20, (W - 100) // 2, 0)
        for y in range(20, H - 38, 29):
            p(0, 42, 12, 29, 0, y)
            p(31, 42, 20, 29, W - 20, y)
        p(0, 72, 125, 38, 0, H - 38)
        p(126, 72, 150, 38, W - 150, H - 38)
        return im

    def build(self):
        self.cv.create_rectangle(self.X0 * K, self.Y0 * K, (self.W - 20) * K, (self.H - 38) * K,
                                 fill=self.cols["NormalBG"], outline="")
        self.bg = pil_photo(self.compose())
        self.cv.create_image(0, 0, image=self.bg, anchor="nw", tags="frame")
        fam = args.pl_font or self.cols["Font"]
        if self.classic:
            self.f1 = self.f2 = tkfont.Font(family=fam, size=-(args.pl_font_size or 10) * K)
        else:
            self.f1 = tkfont.Font(family=fam, size=-max(7, int(self.ROWH * 0.36)) * K)
            self.f2 = tkfont.Font(family=fam, size=-max(6, int(self.ROWH * 0.25)) * K)
        self.f3 = tkfont.Font(family=fam, size=-8 * K)
        self._menu_open = False
        self.cv.bind("<Button-3>", self.popup)
        for ev in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.cv.bind(ev, self.wheel)
        self.cv.bind("<Key>", self.key)
        self.redraw()

    def on_show(self):
        if not self.anim_on:
            self.anim_on = True
            self.animate()

    # --- model
    def queue_items(self):
        pl = self.queue_pl
        return pl["items"] if pl is not None and any(p is pl for p in self.lists) else None

    def recompute_cur(self):
        u = self.last_uri
        self.cur = next((i for i, it in enumerate(self.items) if it["uri"] == u), -1) if u else -1

    def scroll_to(self, i):
        if not self.top_i <= i < self.top_i + self.ROWS:
            self.top_i = max(0, i - self.ROWS + 1)

    def learn_meta(self, uri, st):
        """Fill in artist/title/length of tracks that were added by link, once they play."""
        changed = False
        for p in self.lists:
            for it in p["items"]:
                if it["uri"] == uri:
                    for k, v in (("artist", st["artist"]), ("title", st["title"]),
                                 ("length", st["length"] // 1_000_000)):
                        if v and it.get(k) != v:
                            it[k] = v
                            changed = True
        return changed

    def note_track(self, st):
        uri = st.get("uri", "")
        if not st["ok"] or uri == self.last_uri:
            return
        self.last_uri = uri
        if not uri:
            self.cur = -1
            return
        changed = self.learn_meta(uri, st)
        hist = next(p for p in self.lists if p["history"])
        if not any(it["uri"] == uri for it in hist["items"]):
            hist["items"].append(dict(uri=uri, artist=st["artist"], title=st["title"],
                                      length=st["length"] // 1_000_000))
            if len(hist["items"]) > 500:
                del hist["items"][0]
                if hist is self.lists[self.active]:
                    self.sel = max(-1, self.sel - 1)
            changed = True
        qi = self.queue_items()          # keep the play-through position in step with reality
        if qi is not None:
            if 0 <= self.queue_pos < len(qi) and qi[self.queue_pos]["uri"] == uri:
                pass
            else:
                idx = next((i for i, it in enumerate(qi) if it["uri"] == uri), None)
                if idx is None:
                    self.queue_pl = None     # something else started playing: leave the playlist
                else:
                    self.queue_pos = idx
        if changed:
            self.save()
        self.recompute_cur()
        if self.cv is not None:
            if self.cur >= 0:
                self.scroll_to(self.cur)
            self.redraw()

    def autoadvance(self, st, pos, length):
        """When a track of the playlist being played through is about to end, start the next."""
        items = self.queue_items()
        if items is None or st["status"] != "Playing" or not length or pos < 2_000_000:
            return
        if not 0 <= self.queue_pos < len(items) or items[self.queue_pos]["uri"] != st.get("uri"):
            return
        if length - pos > 700_000:
            return
        key = (st["uri"], self.queue_pos)
        if self.adv_key == key:
            return
        self.adv_key = key
        self.step(1)

    def step(self, d):
        """Next/previous within the playlist being played through.  False = not handled."""
        items = self.queue_items()
        if items is None:
            return False
        j = self.queue_pos + d
        if not 0 <= j < len(items):
            return False
        self.queue_pos, self.adv_key = j, None
        run("open", items[j]["uri"])
        return True

    def play(self, i):
        if 0 <= i < len(self.items):
            pl = self.lists[self.active]
            self.queue_pl = None if pl["history"] else pl    # custom playlists play through
            self.queue_pos, self.adv_key = i, None
            run("open", self.items[i]["uri"])

    # ---- playlists
    def switch(self, i):
        if not 0 <= i < len(self.lists):
            return
        self.active = i
        self.sel, self.top_i = -1, 0
        self.recompute_cur()
        if self.cur >= 0:
            self.scroll_to(self.cur)
        self.save()
        self.redraw()

    def new_playlist(self, name):
        name = (name or "").strip() or f"Playlist {sum(1 for p in self.lists if not p['history']) + 1}"
        base, n = name, 2
        while any(p["name"].lower() == name.lower() for p in self.lists):
            name, n = f"{base} ({n})", n + 1
        self.lists.append(dict(name=name, history=False, items=[]))
        self.switch(len(self.lists) - 1)

    def rename(self, name):
        pl = self.lists[self.active]
        if not name or pl["history"]:
            return
        if any(p is not pl and p["name"].lower() == name.lower() for p in self.lists):
            messagebox.showinfo("Winavolt", "There is already a playlist with that name.",
                                parent=self.host())
            return
        pl["name"] = name
        self.save()
        self.redraw()

    def delete_playlist(self, i):
        if not 0 <= i < len(self.lists):
            return
        pl = self.lists[i]
        if pl["history"]:
            if messagebox.askyesno("Winavolt", "History is built in and can't be deleted.\n"
                                   "Clear all of its tracks instead?", parent=self.host()):
                self.switch(i)
                self.clear_active(confirm=False)
            return
        if not messagebox.askyesno("Winavolt", f"Delete the playlist \u201c{pl['name']}\u201d "
                                   f"and its {len(pl['items'])} tracks?", parent=self.host()):
            return
        if self.queue_pl is pl:
            self.queue_pl = None
        del self.lists[i]
        if self.active == i:
            self.active = max(0, i - 1)
        elif self.active > i:
            self.active -= 1
        self.sel, self.top_i = -1, 0
        self.recompute_cur()
        self.save()
        self.redraw()

    # ---- tracks
    def add_uri(self, uri, artist="", title="", length=0):
        if not uri.startswith("spotify:track:"):
            return
        items = self.items
        for n, it in enumerate(items):
            if it["uri"] == uri:                     # already in this playlist: just show it
                self.sel = n
                self.scroll_to(n)
                self.redraw()
                return
        items.append(dict(uri=uri, artist=artist, title=title, length=length))
        self.sel = len(items) - 1
        self.scroll_to(self.sel)
        self.recompute_cur()
        self.save()
        self.redraw()
        if not title:
            fetch_title(uri, lambda t, it=items[-1]: self.set_title(it, t))

    def set_title(self, it, title):
        if not it.get("title"):
            it["title"] = title
            self.save()
            self.redraw()

    def add_current(self):
        st = STATE
        if st["ok"] and st.get("uri"):
            self.add_uri(st["uri"], st["artist"], st["title"], st["length"] // 1_000_000)
        else:
            messagebox.showinfo("Winavolt", "Nothing is playing right now.", parent=self.host())

    def add_link(self, text):
        if not text:
            return
        uri = to_uri(text)
        if not uri or not uri.startswith("spotify:track:"):
            messagebox.showinfo("Winavolt",
                                "That isn't a Spotify track link.\n(Albums and playlists can't be "
                                "expanded without Spotify's API - add their tracks one by one.)",
                                parent=self.host())
            return
        self.add_uri(uri)

    def copy_selected(self, j):
        if not (0 <= self.sel < len(self.items) and 0 <= j < len(self.lists)):
            return
        it = dict(self.items[self.sel])
        dest = self.lists[j]["items"]
        if not any(d["uri"] == it["uri"] for d in dest):
            dest.append(it)
            self.save()

    def remove(self, i):
        items = self.items
        if not 0 <= i < len(items):
            return
        if self.queue_pl is self.lists[self.active]:
            if i == self.queue_pos:
                self.queue_pl = None
            elif i < self.queue_pos:
                self.queue_pos -= 1
        del items[i]
        self.cur = -1 if i == self.cur else (self.cur - 1 if i < self.cur else self.cur)
        self.sel = -1
        self.save()
        self.redraw()

    def clear_active(self, confirm=True):
        pl = self.lists[self.active]
        if not pl["items"]:
            return
        if confirm and not messagebox.askyesno(
                "Winavolt", f"Remove all {len(pl['items'])} tracks from \u201c{pl['name']}\u201d?",
                parent=self.host()):
            return
        del pl["items"][:]
        self.cur, self.sel, self.top_i = -1, -1, 0
        if pl["history"]:
            self.last_uri = None        # the track playing now gets re-added to History
        if self.queue_pl is pl:
            self.queue_pl = None
        self.save()
        self.redraw()

    # --- drawing
    def line(self, text, font, fg, cy, right=None):
        """One line of text; if it is wider than the list it gets a scrolling twin."""
        x0, y = (self.X0 + 3) * K, cy * K
        avail = (right if right is not None else (self.W - 20 - 3) * K) - x0
        w = font.measure(text)
        i1 = self.cv.create_text(x0, y, anchor="w", text=text, font=font, fill=fg, tags="row")
        if w > avail:
            gap = 30 * K
            i2 = self.cv.create_text(x0 + w + gap, y, anchor="w", text=text, font=font,
                                     fill=fg, tags="row")
            self.anim.append(dict(i1=i1, i2=i2, x0=x0, cy=y, period=w + gap, off=0, hold=25))

    def redraw(self):
        if self.cv is None:
            return
        self.cv.delete("row")
        self.anim = []
        self.top_i = max(0, min(self.top_i, max(0, len(self.items) - self.ROWS)))
        for r in range(self.ROWS):
            i = self.top_i + r
            if i >= len(self.items):
                break
            it = self.items[i]
            y = self.Y0 + r * self.ROWH
            if i == self.sel:
                self.cv.create_rectangle(self.X0 * K, y * K, (self.W - 20) * K,
                                         (y + self.ROWH) * K,
                                         fill=self.cols["SelectedBG"], outline="", tags="row")
            fg = self.cols["Current"] if i == self.cur else self.cols["Normal"]
            artist, title = it.get("artist", ""), it.get("title", "")
            short = it["uri"].rsplit(":", 1)[-1]      # shown until the real title is known
            dur = ""
            if it.get("length"):
                m, s = divmod(int(it["length"]), 60)
                dur = f"{m}:{s:02d}"
            if self.classic:
                label = f"{i + 1}. " + (" - ".join(x for x in (artist, title) if x) or short)
                right = (self.W - 20 - 3) * K
                clip = right - (self.f1.measure("00:00") + 8 * K) if dur else right
                self.line(label, self.f1, fg, y + self.ROWH / 2, right=clip)
                if dur:       # mask the sliding text, then draw the fixed duration column
                    bgc = self.cols["SelectedBG"] if i == self.sel else self.cols["NormalBG"]
                    self.cv.create_rectangle(clip, y * K, (self.W - 20) * K, (y + self.ROWH) * K,
                                             fill=bgc, outline="", tags="row")
                    self.cv.create_text(right, (y + self.ROWH / 2) * K, anchor="e", text=dur,
                                        font=self.f1, fill=fg, tags="row")
            else:
                self.line(f"{i + 1}. {title or artist or short}", self.f1, fg, y + self.ROWH * 0.30)
                self.line("  -  ".join(x for x in (artist if title else "", dur) if x) or " ",
                          self.f2, fg, y + self.ROWH * 0.72)
        self.cv.tag_raise("frame")      # frame on top clips the sliding text
        self.draw_label()

    def animate(self):
        if not self.visible or self.host() is None:
            self.anim_on = False
            return
        step = max(1, K)
        for a in self.anim:
            if a["hold"] > 0:
                a["hold"] -= 1
                continue
            a["off"] += step
            if a["off"] >= a["period"]:
                a["off"], a["hold"] = 0, 25
            self.cv.coords(a["i1"], a["x0"] - a["off"], a["cy"])
            self.cv.coords(a["i2"], a["x0"] - a["off"] + a["period"], a["cy"])
        self.host().after(40, self.animate)

    def draw_label(self):
        """Name and size of the open playlist, in the skin's little black display."""
        self.cv.delete("label")
        pl = self.lists[self.active]
        text = f"{pl['name']} ({len(pl['items'])})"
        x0, y0, x1, y1 = 130, self.H - 31, 221, self.H - 21
        avail = (x1 - x0 - 4) * K
        t = text
        while len(t) > 1 and self.f3.measure(t + ("\u2026" if t != text else "")) > avail:
            t = t[:-1]
        if t != text:
            t += "\u2026"
        self.cv.create_rectangle(x0 * K, y0 * K, x1 * K, y1 * K, fill=self.cols["NormalBG"],
                                 outline="", tags="label")
        self.cv.create_text((x0 + 2) * K, (y0 + y1) / 2 * K, anchor="w", text=t, font=self.f3,
                            fill=self.cols["Normal"], tags="label")

    def row_at(self, x, y):
        if self.X0 <= x < self.W - 20 and self.Y0 <= y < self.Y0 + self.ROWS * self.ROWH:
            i = self.top_i + int((y - self.Y0) // self.ROWH)
            return i if i < len(self.items) else None
        return None

    # --- mouse / keys
    def zones(self):
        by = self.H - 31
        return {"close": (self.W - 11, 3, 9, 9), "add": (10, by, 26, 18),
                "rem": (39, by, 26, 18), "list": (227, by, 26, 18)}

    def click(self, x, y, e):
        for name, r in self.zones().items():
            if inside(x, y, r):
                self.pend = name
                self.pend_open = menu_is_open()
                return True
        if self.X0 <= x < self.W - 20 and self.Y0 <= y < self.H - 38:
            i = self.row_at(x, y)
            if i is not None:
                now = time.monotonic()
                if self.last_click[0] == i and now - self.last_click[1] < 0.4:
                    self.play(i)
                self.last_click = (i, now)
                self.sel = i
                self.redraw()
            return True
        return False

    def release(self, e):
        if self.pend:
            name, self.pend = self.pend, None
            if inside(e.x / K, e.y / K, self.zones()[name]):
                if name == "close":
                    self.hide()
                elif not self.pend_open:       # the click that closed a menu mustn't reopen it
                    self.post({"add": self.build_add, "rem": self.build_rem,
                               "list": self.build_list}[name], e.x_root, e.y_root)

    def wheel(self, e):
        up = getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0
        self.top_i += -1 if up else 1
        self.redraw()

    def key(self, e):
        if e.keysym == "Delete":
            self.remove(self.sel)
        elif e.keysym == "Return":
            self.play(self.sel)

    # --- menus (ADD / REM / LIST buttons and the right-click menu)
    def post(self, builder, x, y):
        def go():
            if self.host() is not None:
                popup_menu(builder(self.host()), x, y)

        self.host().after_idle(go)

    def build_add(self, parent):
        m = tk.Menu(parent, tearoff=0)
        others = [j for j in range(len(self.lists)) if j != self.active]
        m.add_command(label="New playlist\u2026", command=lambda: root.after(10, self.ask_new))
        m.add_separator()
        m.add_command(label="Add the track that is playing now", command=self.add_current)
        m.add_command(label="Add a Spotify track link\u2026",
                      command=lambda: root.after(10, self.ask_link))
        sub = tk.Menu(m, tearoff=0)
        for j in others:
            sub.add_command(label=self.lists[j]["name"], command=lambda j=j: self.copy_selected(j))
        ok = 0 <= self.sel < len(self.items) and bool(others)
        m.add_cascade(label="Copy selected track to", menu=sub,
                      state="normal" if ok else "disabled")
        return m

    def build_rem(self, parent):
        m = tk.Menu(parent, tearoff=0)
        m.add_command(label="Remove selected track",
                      state="normal" if 0 <= self.sel < len(self.items) else "disabled",
                      command=lambda: self.remove(self.sel))
        m.add_command(label="Remove all tracks from this playlist",
                      command=lambda: root.after(10, self.clear_active))
        m.add_separator()
        sub = tk.Menu(m, tearoff=0)
        for i, p in enumerate(self.lists):
            sub.add_command(label=p["name"] + ("   (built in: clears it)" if p["history"] else ""),
                            command=lambda i=i: root.after(10, self.delete_playlist, i))
        m.add_cascade(label="Delete a whole playlist", menu=sub)
        return m

    def build_list(self, parent):
        m = tk.Menu(parent, tearoff=0)
        for i, p in enumerate(self.lists):
            mark = "\u25cf " if i == self.active else "    "
            m.add_command(label=f"{mark}{p['name']}   ({len(p['items'])})",
                          command=lambda i=i: self.switch(i))
        m.add_separator()
        m.add_command(label="New playlist\u2026", command=lambda: root.after(10, self.ask_new))
        m.add_command(label="Rename this playlist\u2026",
                      state="disabled" if self.lists[self.active]["history"] else "normal",
                      command=lambda: root.after(10, self.ask_rename))
        return m

    def ask_new(self):
        n = sum(1 for p in self.lists if not p["history"]) + 1
        ask_text("New playlist", "Name for the new playlist:", self.new_playlist, f"Playlist {n}")

    def ask_rename(self):
        ask_text("Rename playlist", "New name:", self.rename, self.lists[self.active]["name"])

    def ask_link(self):
        ask_text("Add a track", "Spotify track link or URI:", self.add_link)

    def popup(self, e):
        i = self.row_at(e.x / K, e.y / K)
        if i is not None:
            self.sel = i
            self.redraw()

        def builder(parent):
            m = tk.Menu(parent, tearoff=0)
            m.add_command(label="Play", command=lambda: self.play(self.sel))
            m.add_separator()
            m.add_cascade(label="Playlists", menu=self.build_list(m))
            m.add_cascade(label="Add", menu=self.build_add(m))
            m.add_cascade(label="Remove", menu=self.build_rem(m))
            m.add_separator()
            m.add_command(label="Float in its own window" if self.docked else "Dock under the player",
                          command=lambda: root.after(10, self.toggle_dock))
            m.add_command(label="Close", command=lambda: root.after(10, self.hide))
            return m

        self.post(builder, e.x_root, e.y_root)


EQW = EqWin()
PLW = PlWin()

# ------------------------------------------------------------------ go
try:
    px, py = (int(v) for v in args.pos.split(","))
except ValueError:
    px, py = 100, 100
root.geometry(f"+{px}+{py}")
POS.update(x=px, y=py, t=time.monotonic())
root.after(1500, learn_offset)
root.bind("<Configure>", lambda e: sync_main_position() if e.widget is root else None)
apply_mode()
if MANAGED:
    strip_decor(root)
    root.deiconify()
threading.Thread(target=poller, daemon=True).start()
atexit.register(EQE.stop)
for _sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(_sig, lambda *a: (EQE.stop(), os._exit(0)))
tick()
root.mainloop()
