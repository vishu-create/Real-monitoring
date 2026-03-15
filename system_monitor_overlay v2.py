"""
System Monitor Overlay  v4
==========================
Always-on-top slim bar: CPU · CPU TEMP · RAM · DISK I/O · iGPU · NET

- Fully click-through  — overlay never blocks clicks on apps beneath it
- System tray icon     — right-click tray icon to Show/Hide or Quit
- Auto-detects RAM     — reads actual installed RAM from your system
- Disk I/O activity    — shows live read/write speed, not fullness
- iGPU auto-hide       — only shown if AMD GPU data is actually readable

Requirements (bundled in exe via PyInstaller, nothing to install manually):
    psutil · pystray · Pillow

Optional for iGPU data:
    pip install pyadl          ← AMD Display Library wrapper
    — OR —
    Run LibreHardwareMonitor   ← https://github.com/LibreHardwareMonitor
"""

import sys
import ctypes
import time
import threading
import tkinter as tk
import psutil

# ── Auto-detect system RAM (rounds to nearest GB) ─────────────────────────────
TOTAL_RAM_GB = round(psutil.virtual_memory().total / (1024 ** 3))

# ── Config ────────────────────────────────────────────────────────────────────
BAR_HEIGHT      = 36
FONT_FAMILY     = "Consolas"
FONT_SIZE       = 11
UPDATE_INTERVAL = 1000       # ms
BG_COLOR        = "#0d0d0d"
ALPHA           = 0.82
PADDING_X       = 12

# ── Colour helpers ────────────────────────────────────────────────────────────
def usage_color(pct):
    if pct < 50: return "#39ff14"
    if pct < 80: return "#ffb347"
    return "#ff4444"

def temp_color(c):
    if c < 50: return "#00cfff"
    if c < 70: return "#39ff14"
    if c < 85: return "#ffb347"
    return "#ff4444"

def fmt_bytes(bps):
    """Format bytes/sec nicely."""
    if bps < 1_024:       return f"{bps:.0f}B/s"
    if bps < 1_048_576:   return f"{bps/1_024:.1f}KB/s"
    if bps < 1_073_741_824: return f"{bps/1_048_576:.1f}MB/s"
    return                       f"{bps/1_073_741_824:.1f}GB/s"

# ══════════════════════════════════════════════════════════════════════════════
#  CPU TEMPERATURE
# ══════════════════════════════════════════════════════════════════════════════
_cpu_temp_backend = None

def _cpu_temp_lhwm():
    try:
        import wmi
        w = wmi.WMI(namespace="root\\LibreHardwareMonitor")
        for s in w.Sensor():
            if s.SensorType == "Temperature" and "CPU Package" in s.Name:
                return float(s.Value)
        for s in w.Sensor():
            if s.SensorType == "Temperature" and "CPU" in s.Name:
                return float(s.Value)
    except Exception:
        pass
    return None

def _cpu_temp_psutil():
    try:
        temps = psutil.sensors_temperatures()
        for key in ("k10temp", "coretemp", "acpitz", "cpu_thermal"):
            if key in temps and temps[key]:
                return temps[key][0].current
    except Exception:
        pass
    return None

def get_cpu_temp():
    global _cpu_temp_backend
    if _cpu_temp_backend is None:
        for probe, tag in [(_cpu_temp_lhwm, "lhwm"),
                           (_cpu_temp_psutil, "psutil")]:
            v = probe()
            if v is not None:
                _cpu_temp_backend = tag
                return v
        _cpu_temp_backend = "none"
        return None
    if _cpu_temp_backend == "lhwm":   return _cpu_temp_lhwm()
    if _cpu_temp_backend == "psutil": return _cpu_temp_psutil()
    return None

# ══════════════════════════════════════════════════════════════════════════════
#  AMD iGPU BACKEND
# ══════════════════════════════════════════════════════════════════════════════
_gpu_backend = None

def _gpu_pyadl():
    try:
        import pyadl
        devices = pyadl.ADLManager.getInstance().getDevices()
        if not devices:
            return None, None, None
        d    = devices[0]
        load = float(d.getCurrentUsage())
        try:
            mem_used  = d.getCurrentMemoryUsage()
            mem_total = d.adapter_info.iAdapterMemory
            vram_pct  = round(mem_used / (mem_total / 1024 / 1024) * 100, 1) if mem_total else None
        except Exception:
            vram_pct = None
        try:
            temp = float(d.getCurrentTemperature())
        except Exception:
            temp = None
        return load, vram_pct, temp
    except Exception:
        pass
    return None, None, None

def _gpu_lhwm():
    try:
        import wmi
        w = wmi.WMI(namespace="root\\LibreHardwareMonitor")
        load = vram = temp = None
        for s in w.Sensor():
            st, sn = s.SensorType, s.Name
            if st == "Load"        and "GPU Core"   in sn: load = float(s.Value)
            if st == "Load"        and "GPU Memory" in sn: vram = float(s.Value)
            if st == "Temperature" and "GPU Core"   in sn: temp = float(s.Value)
        if load is not None:
            return load, vram, temp
    except Exception:
        pass
    return None, None, None

def get_gpu_info():
    global _gpu_backend
    if _gpu_backend is None:
        for probe, tag in [(_gpu_pyadl, "pyadl"),
                           (_gpu_lhwm,  "lhwm")]:
            load, vram, temp = probe()
            if load is not None:
                _gpu_backend = tag
                return load, vram, temp
        _gpu_backend = "none"
        return None, None, None
    if _gpu_backend == "pyadl": return _gpu_pyadl()
    if _gpu_backend == "lhwm":  return _gpu_lhwm()
    return None, None, None

# ══════════════════════════════════════════════════════════════════════════════
#  CLICK-THROUGH  (Windows only)
#  Makes the overlay window invisible to mouse clicks — all clicks pass
#  straight through to whatever app is underneath.
# ══════════════════════════════════════════════════════════════════════════════
def make_click_through(root):
    if sys.platform != "win32":
        return
    try:
        hwnd  = ctypes.windll.user32.GetParent(root.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)   # GWL_EXSTYLE
        # WS_EX_LAYERED (0x80000) | WS_EX_TRANSPARENT (0x20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20)
    except Exception as e:
        print(f"[click-through] {e}")

# ══════════════════════════════════════════════════════════════════════════════
#  SYSTEM TRAY  (pystray + Pillow — bundled into exe)
# ══════════════════════════════════════════════════════════════════════════════
def start_tray(root):
    """Create a system-tray icon in a background thread."""
    try:
        import pystray
        from PIL import Image, ImageDraw, ImageFont

        # Draw a small green monitor icon programmatically
        size = 64
        img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d    = ImageDraw.Draw(img)
        # Screen bezel
        d.rounded_rectangle([4, 8, 60, 48], radius=4,
                             fill="#1a1a1a", outline="#39ff14", width=3)
        # Screen glow
        d.rectangle([10, 14, 54, 42], fill="#0d0d0d")
        # Activity bars inside screen
        for i, (x, h, col) in enumerate([(14, 16, "#39ff14"),
                                          (24, 22, "#ffb347"),
                                          (34, 10, "#39ff14"),
                                          (44, 18, "#00cfff")]):
            d.rectangle([x, 42 - h, x + 6, 42], fill=col)
        # Stand
        d.rectangle([28, 48, 36, 56], fill="#39ff14")
        d.rectangle([20, 56, 44, 60], fill="#39ff14")

        _visible = [True]

        def toggle(icon, item):
            def _t():
                if _visible[0]:
                    root.withdraw()
                    _visible[0] = False
                else:
                    root.deiconify()
                    _visible[0] = True
            root.after(0, _t)

        def quit_app(icon, item):
            icon.stop()
            root.after(0, root.destroy)

        menu = pystray.Menu(
            pystray.MenuItem("Show / Hide overlay", toggle),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_app),
        )
        icon = pystray.Icon("SysMonitor", img, "System Monitor", menu)
        threading.Thread(target=icon.run, daemon=True).start()

    except Exception as e:
        print(f"[tray] {e}")

# ══════════════════════════════════════════════════════════════════════════════
#  OVERLAY WIDGET
# ══════════════════════════════════════════════════════════════════════════════
class SystemMonitorOverlay:
    def __init__(self, root: tk.Tk, gpu_available: bool):
        self.root       = root
        self._drag_y    = 0
        self._gpu_avail = gpu_available

        # ── Window chrome ──────────────────────────────────────────────────
        root.title("SysMonitor")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", ALPHA)
        root.configure(bg=BG_COLOR)
        root.resizable(False, False)
        sw = root.winfo_screenwidth()
        root.geometry(f"{sw}x{BAR_HEIGHT}+0+0")

        self.frame = tk.Frame(root, bg=BG_COLOR, height=BAR_HEIGHT)
        self.frame.pack(fill="both", expand=True)

        # ── Layout helpers ─────────────────────────────────────────────────
        lbl_brand = tk.Label(self.frame, text="⬡ SYSMON",
                             bg=BG_COLOR, fg="#2e2e2e",
                             font=(FONT_FAMILY, 9, "bold"), padx=PADDING_X)
        lbl_brand.pack(side="left")

        def sep():
            tk.Label(self.frame, text="│", bg=BG_COLOR, fg="#222",
                     font=(FONT_FAMILY, FONT_SIZE)).pack(side="left")

        def tag(txt, color="#484848"):
            tk.Label(self.frame, text=txt, bg=BG_COLOR, fg=color,
                     font=(FONT_FAMILY, 9)).pack(side="left")

        def val(init="---", color="#39ff14"):
            lbl = tk.Label(self.frame, text=init, bg=BG_COLOR, fg=color,
                           font=(FONT_FAMILY, FONT_SIZE, "bold"), padx=2)
            lbl.pack(side="left")
            return lbl

        def mini_bar(w=48):
            c = tk.Canvas(self.frame, width=w, height=6,
                          bg="#1c1c1c", highlightthickness=0)
            c.pack(side="left", padx=(0, 3))
            return c

        # ── CPU load + temp ────────────────────────────────────────────────
        sep()
        tag(" CPU")
        self.lbl_cpu   = val("---%")
        self.bar_cpu   = mini_bar()
        self.lbl_ctemp = val("--°C", "#00cfff")

        # ── RAM  (X.X / total GB) ──────────────────────────────────────────
        sep()
        tag(" RAM")
        self.lbl_ram = val(f"--/{TOTAL_RAM_GB}G")
        self.bar_ram = mini_bar()

        # ── Disk I/O (live read / write speed) ────────────────────────────
        sep()
        tag(" DISK R:")
        self.lbl_disk_r = val("---", "#ffb347")
        tag(" W:")
        self.lbl_disk_w = val("---", "#ff6464")

        # ── AMD iGPU  (only created when data is available) ────────────────
        if gpu_available:
            sep()
            tag(" iGPU")
            self.lbl_gpu   = val("---%")
            self.bar_gpu   = mini_bar()
            self.lbl_gtemp = val("--°C", "#00cfff")

        # ── Network ────────────────────────────────────────────────────────
        sep()
        tag(" ↑")
        self.lbl_net_up   = val("---", "#00cfff")
        tag(" ↓")
        self.lbl_net_down = val("---", "#00cfff")

        # ── Drag handle (vertical repositioning) ───────────────────────────
        for w in (self.frame, lbl_brand):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>",      self._drag_move)

        # ── Baselines ──────────────────────────────────────────────────────
        net = psutil.net_io_counters()
        self._prev_sent  = net.bytes_sent
        self._prev_recv  = net.bytes_recv
        self._prev_net_t = time.time()

        dio = psutil.disk_io_counters()
        self._prev_dr = dio.read_bytes
        self._prev_dw = dio.write_bytes
        self._prev_dt = time.time()

        self._update()

    # ── Fill mini bar ──────────────────────────────────────────────────────
    def _fill(self, canvas, pct, color, w=48):
        canvas.delete("all")
        canvas.create_rectangle(0, 0, int(w * min(pct, 100) / 100), 6,
                                fill=color, outline="")

    # ── Stats loop ─────────────────────────────────────────────────────────
    def _update(self):
        try:
            now = time.time()

            # CPU
            cpu = psutil.cpu_percent(interval=None)
            cc  = usage_color(cpu)
            self.lbl_cpu.config(text=f"{cpu:5.1f}%", fg=cc)
            self._fill(self.bar_cpu, cpu, cc)

            # CPU Temp
            t = get_cpu_temp()
            if t is not None:
                self.lbl_ctemp.config(text=f"{t:.0f}°C", fg=temp_color(t))
            else:
                self.lbl_ctemp.config(text="--°C", fg="#333")

            # RAM
            mem     = psutil.virtual_memory()
            used_gb = mem.used / (1024 ** 3)
            rc      = usage_color(mem.percent)
            self.lbl_ram.config(text=f"{used_gb:.1f}/{TOTAL_RAM_GB}G", fg=rc)
            self._fill(self.bar_ram, mem.percent, rc)

            # Disk I/O
            dio  = psutil.disk_io_counters()
            dt_d = max(now - self._prev_dt, 0.001)
            dr   = (dio.read_bytes  - self._prev_dr) / dt_d
            dw   = (dio.write_bytes - self._prev_dw) / dt_d
            self._prev_dr = dio.read_bytes
            self._prev_dw = dio.write_bytes
            self._prev_dt = now
            self.lbl_disk_r.config(text=fmt_bytes(dr))
            self.lbl_disk_w.config(text=fmt_bytes(dw))

            # iGPU
            if self._gpu_avail:
                gpu_load, gpu_vram, gpu_temp = get_gpu_info()
                if gpu_load is not None:
                    gc = usage_color(gpu_load)
                    self.lbl_gpu.config(text=f"{gpu_load:5.1f}%", fg=gc)
                    self._fill(self.bar_gpu, gpu_load, gc)
                    if gpu_temp is not None:
                        self.lbl_gtemp.config(text=f"{gpu_temp:.0f}°C",
                                              fg=temp_color(gpu_temp))
                    else:
                        self.lbl_gtemp.config(text="--°C", fg="#333")
                else:
                    self.lbl_gpu.config(text="  N/A", fg="#333")
                    self.lbl_gtemp.config(text="--°C",  fg="#333")

            # Network
            net  = psutil.net_io_counters()
            dt_n = max(now - self._prev_net_t, 0.001)
            up   = (net.bytes_sent - self._prev_sent) / dt_n
            down = (net.bytes_recv - self._prev_recv) / dt_n
            self._prev_sent  = net.bytes_sent
            self._prev_recv  = net.bytes_recv
            self._prev_net_t = now
            self.lbl_net_up.config(text=fmt_bytes(up))
            self.lbl_net_down.config(text=fmt_bytes(down))

        except Exception:
            pass

        self.root.after(UPDATE_INTERVAL, self._update)

    # ── Drag ───────────────────────────────────────────────────────────────
    def _drag_start(self, e): self._drag_y = e.y_root
    def _drag_move(self, e):
        y = self.root.winfo_y() + (e.y_root - self._drag_y)
        self.root.geometry(f"+0+{y}")
        self._drag_y = e.y_root


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    psutil.cpu_percent(interval=None)   # warm-up (first call always returns 0.0)

    # Probe GPU once at startup — if no data, skip iGPU section entirely
    _load, _, _ = get_gpu_info()
    GPU_AVAILABLE = _load is not None

    root = tk.Tk()
    SystemMonitorOverlay(root, GPU_AVAILABLE)

    # Apply click-through AFTER the window is fully mapped
    root.update()
    make_click_through(root)

    # Launch system tray icon in background thread
    start_tray(root)

    root.mainloop()
