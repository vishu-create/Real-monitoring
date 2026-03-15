"""
System Monitor Overlay  v3
==========================
Tailored for:  AMD Ryzen 5 5500U  ·  16 GB RAM
Always-on-top slim bar: CPU · CPU TEMP · RAM · DISK · iGPU · NET

Requirements (only one):
    pip install psutil

Optional — enables AMD iGPU load & VRAM readings:
    pip install pyadl          ← AMD Display Library wrapper (easiest)
    — OR —
    Run LibreHardwareMonitor   ← https://github.com/LibreHardwareMonitor/LibreHardwareMonitor
    (keeps running in tray, exposes WMI data, no Python package needed)

Run normally:
    python system_monitor_overlay.py

Run without a terminal window (Windows):
    pythonw system_monitor_overlay.py
"""

import sys
import subprocess
import time
import tkinter as tk
import psutil

# ─── User config ───────────────────────────────────────────────────────────────
TOTAL_RAM_GB    = 16            # Your installed RAM
BAR_HEIGHT      = 36            # Pixel height of the overlay bar
FONT_FAMILY     = "Consolas"
FONT_SIZE       = 11
UPDATE_INTERVAL = 1000          # Refresh every 1 second (ms)
BG_COLOR        = "#0d0d0d"
ALPHA           = 0.82          # 0.0 = invisible  ·  1.0 = fully opaque
PADDING_X       = 14

# ─── Colour scale ──────────────────────────────────────────────────────────────
def usage_color(pct):
    """Green under 50 %, orange under 80 %, red above."""
    if pct < 50: return "#39ff14"
    if pct < 80: return "#ffb347"
    return "#ff4444"

def temp_color(c):
    """Cool blue → green → orange → red as temperature rises."""
    if c < 50:  return "#00cfff"
    if c < 70:  return "#39ff14"
    if c < 85:  return "#ffb347"
    return "#ff4444"

def fmt_speed(bps):
    if bps < 1_024:     return f"{bps:.0f} B/s"
    if bps < 1_048_576: return f"{bps/1_024:.1f} KB/s"
    return                     f"{bps/1_048_576:.1f} MB/s"

# ══════════════════════════════════════════════════════════════════════════════
#  CPU TEMPERATURE
#  Windows: WMI via LibreHardwareMonitor (free, runs in tray)
#  Linux:   psutil.sensors_temperatures()  — works out of the box
# ══════════════════════════════════════════════════════════════════════════════
_cpu_temp_backend = None   # 'lhwm_wmi' | 'psutil' | 'none'

def _cpu_temp_wmi():
    """Query LibreHardwareMonitor WMI for CPU package temp."""
    try:
        import wmi
        w       = wmi.WMI(namespace="root\\LibreHardwareMonitor")
        sensors = w.Sensor()
        for s in sensors:
            if s.SensorType == "Temperature" and "CPU Package" in s.Name:
                return float(s.Value)
        # Fallback: first CPU temperature found
        for s in sensors:
            if s.SensorType == "Temperature" and "CPU" in s.Name:
                return float(s.Value)
    except Exception:
        pass
    return None

def _cpu_temp_psutil():
    """Linux / macOS — works on most machines without extra tools."""
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
        for probe, tag in [(_cpu_temp_wmi, "lhwm_wmi"),
                           (_cpu_temp_psutil, "psutil")]:
            val = probe()
            if val is not None:
                _cpu_temp_backend = tag
                return val
        _cpu_temp_backend = "none"
        return None
    if _cpu_temp_backend == "lhwm_wmi": return _cpu_temp_wmi()
    if _cpu_temp_backend == "psutil":   return _cpu_temp_psutil()
    return None

# ══════════════════════════════════════════════════════════════════════════════
#  AMD iGPU BACKEND
#  Ryzen 5 5500U has AMD Radeon Vega integrated graphics.
#  Three probes tried in order — first one that returns data wins.
#
#  Probe 1 — pyadl   (pip install pyadl)
#    AMD Display Library Python wrapper. Easiest; no extra software.
#    Returns GPU engine load & memory info directly.
#
#  Probe 2 — LibreHardwareMonitor WMI
#    Keep LHM running in the system tray.  No Python package needed.
#    Exposes all AMD sensor data including iGPU load, VRAM, and temp.
#    Download: https://github.com/LibreHardwareMonitor/LibreHardwareMonitor
#
#  Probe 3 — None
#    Shows "N/A" gracefully — everything else still works fine.
# ══════════════════════════════════════════════════════════════════════════════
_gpu_backend = None   # 'pyadl' | 'lhwm_wmi' | 'none'

def _gpu_pyadl():
    """pyadl — AMD Display Library wrapper (pip install pyadl)."""
    try:
        import pyadl
        devices = pyadl.ADLManager.getInstance().getDevices()
        if not devices:
            return None, None, None
        d    = devices[0]
        load = d.getCurrentUsage()                         # 0–100
        # pyadl may not expose VRAM used/total on all iGPU SKUs
        try:
            mem_used  = d.getCurrentMemoryUsage()          # MB
            mem_total = d.adapter_info.iAdapterMemory or 1 # bytes → convert
            if mem_total < 1_000:                          # already in MB
                vram_pct = round(mem_used / mem_total * 100, 1)
            else:
                vram_pct = round(mem_used / (mem_total / 1024 / 1024) * 100, 1)
        except Exception:
            vram_pct = None
        try:
            temp = d.getCurrentTemperature()
        except Exception:
            temp = None
        return float(load), vram_pct, temp
    except Exception:
        pass
    return None, None, None

def _gpu_lhwm_wmi():
    """LibreHardwareMonitor WMI — works for AMD iGPU with no extra packages."""
    try:
        import wmi
        w       = wmi.WMI(namespace="root\\LibreHardwareMonitor")
        sensors = w.Sensor()
        load = vram = temp = None
        for s in sensors:
            st, sn = s.SensorType, s.Name
            if st == "Load"        and "GPU Core" in sn:   load  = float(s.Value)
            if st == "Load"        and "GPU Memory" in sn: vram  = float(s.Value)
            if st == "Temperature" and "GPU Core" in sn:   temp  = float(s.Value)
        if load is not None:
            return load, vram, temp
    except Exception:
        pass
    return None, None, None

def get_gpu_info():
    """Returns (load_pct, vram_pct, temp_c) — any value may be None."""
    global _gpu_backend
    if _gpu_backend is None:
        for probe, tag in [(_gpu_pyadl, "pyadl"),
                           (_gpu_lhwm_wmi, "lhwm_wmi")]:
            load, vram, temp = probe()
            if load is not None:
                _gpu_backend = tag
                return load, vram, temp
        _gpu_backend = "none"
        return None, None, None

    if _gpu_backend == "pyadl":    return _gpu_pyadl()
    if _gpu_backend == "lhwm_wmi": return _gpu_lhwm_wmi()
    return None, None, None

# ══════════════════════════════════════════════════════════════════════════════
#  OVERLAY
# ══════════════════════════════════════════════════════════════════════════════
class SystemMonitorOverlay:
    def __init__(self, root: tk.Tk):
        self.root        = root
        self._pinned_top = True
        self._drag_y     = 0

        # ── Window chrome ──────────────────────────────────────────────────
        root.title("SysMonitor")
        root.overrideredirect(True)          # no title-bar / borders
        root.attributes("-topmost", True)
        root.attributes("-alpha", ALPHA)
        root.configure(bg=BG_COLOR)
        root.resizable(False, False)
        sw = root.winfo_screenwidth()
        root.geometry(f"{sw}x{BAR_HEIGHT}+0+0")

        self.frame = tk.Frame(root, bg=BG_COLOR, height=BAR_HEIGHT)
        self.frame.pack(fill="both", expand=True)

        # ── Brand / drag handle ────────────────────────────────────────────
        lbl_brand = tk.Label(
            self.frame, text="⬡ R5-5500U",
            bg=BG_COLOR, fg="#3a3a3a",
            font=(FONT_FAMILY, 9, "bold"), padx=PADDING_X
        )
        lbl_brand.pack(side="left")

        # ── Layout helpers ─────────────────────────────────────────────────
        def sep():
            tk.Label(self.frame, text="│", bg=BG_COLOR, fg="#252525",
                     font=(FONT_FAMILY, FONT_SIZE)).pack(side="left")

        def tag(txt):
            tk.Label(self.frame, text=txt, bg=BG_COLOR, fg="#505050",
                     font=(FONT_FAMILY, 9)).pack(side="left")

        def val(init="---", color="#39ff14"):
            lbl = tk.Label(self.frame, text=init, bg=BG_COLOR, fg=color,
                           font=(FONT_FAMILY, FONT_SIZE, "bold"), padx=3)
            lbl.pack(side="left")
            return lbl

        def mini_bar(w=52):
            c = tk.Canvas(self.frame, width=w, height=6,
                          bg="#1c1c1c", highlightthickness=0)
            c.pack(side="left", padx=(0, 4))
            return c

        # ── CPU ────────────────────────────────────────────────────────────
        sep(); tag(" CPU")
        self.lbl_cpu  = val("---%")
        self.bar_cpu  = mini_bar()

        # ── CPU Temperature ────────────────────────────────────────────────
        sep(); tag(" TEMP")
        self.lbl_temp = val("---°C", "#00cfff")

        # ── RAM  (shows X.X / 16 GB) ───────────────────────────────────────
        sep(); tag(" RAM")
        self.lbl_ram  = val(f"---/{TOTAL_RAM_GB}G")
        self.bar_ram  = mini_bar()

        # ── DISK ───────────────────────────────────────────────────────────
        sep(); tag(" DISK")
        self.lbl_disk = val("---%")
        self.bar_disk = mini_bar()

        # ── AMD iGPU ───────────────────────────────────────────────────────
        sep(); tag(" iGPU")
        self.lbl_gpu  = val("---%")
        self.bar_gpu  = mini_bar()
        self.lbl_vram = tk.Label(self.frame, text="",
                                 bg=BG_COLOR, fg="#505050",
                                 font=(FONT_FAMILY, 8), padx=2)
        self.lbl_vram.pack(side="left")

        # ── Network ────────────────────────────────────────────────────────
        sep(); tag(" ↑")
        self.lbl_net_up   = val("---", "#00cfff")
        tag(" ↓")
        self.lbl_net_down = val("---", "#00cfff")

        # ── Right controls ─────────────────────────────────────────────────
        btn_close = tk.Label(self.frame, text=" ✕ ",
                             bg=BG_COLOR, fg="#3a3a3a",
                             font=(FONT_FAMILY, 10), cursor="hand2")
        btn_close.pack(side="right", padx=6)
        btn_close.bind("<Button-1>", lambda _: root.destroy())
        btn_close.bind("<Enter>",    lambda _: btn_close.config(fg="#ff4444"))
        btn_close.bind("<Leave>",    lambda _: btn_close.config(fg="#3a3a3a"))

        self.btn_pin = tk.Label(self.frame, text=" ⊕ ",
                                bg=BG_COLOR, fg="#39ff14",
                                font=(FONT_FAMILY, 10), cursor="hand2")
        self.btn_pin.pack(side="right", padx=2)
        self.btn_pin.bind("<Button-1>", self._toggle_pin)

        # ── Drag (vertical repositioning) ──────────────────────────────────
        for w in (self.frame, lbl_brand):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>",      self._drag_move)

        # ── Network baseline ───────────────────────────────────────────────
        net = psutil.net_io_counters()
        self._prev_sent  = net.bytes_sent
        self._prev_recv  = net.bytes_recv
        self._prev_net_t = time.time()

        self._update()

    # ── Fill mini bar ──────────────────────────────────────────────────────
    def _fill(self, canvas, pct, color, w=52):
        canvas.delete("all")
        canvas.create_rectangle(0, 0, int(w * min(pct, 100) / 100), 6,
                                fill=color, outline="")

    # ── Stats update ───────────────────────────────────────────────────────
    def _update(self):
        try:
            # ── CPU load ──────────────────────────────────────────────────
            cpu = psutil.cpu_percent(interval=None)
            cc  = usage_color(cpu)
            self.lbl_cpu.config(text=f"{cpu:5.1f}%", fg=cc)
            self._fill(self.bar_cpu, cpu, cc)

            # ── CPU temperature ───────────────────────────────────────────
            t = get_cpu_temp()
            if t is not None:
                self.lbl_temp.config(text=f"{t:.0f}°C", fg=temp_color(t))
            else:
                self.lbl_temp.config(text=" N/A", fg="#3a3a3a")

            # ── RAM  (used GB / 16 GB) ────────────────────────────────────
            mem      = psutil.virtual_memory()
            used_gb  = mem.used / (1024 ** 3)
            ram_pct  = mem.percent
            rc       = usage_color(ram_pct)
            self.lbl_ram.config(
                text=f"{used_gb:.1f}/{TOTAL_RAM_GB}G",
                fg=rc
            )
            self._fill(self.bar_ram, ram_pct, rc)

            # ── Disk ──────────────────────────────────────────────────────
            disk = psutil.disk_usage("/").percent
            dc   = usage_color(disk)
            self.lbl_disk.config(text=f"{disk:5.1f}%", fg=dc)
            self._fill(self.bar_disk, disk, dc)

            # ── AMD iGPU ──────────────────────────────────────────────────
            gpu_load, gpu_vram, gpu_temp = get_gpu_info()
            if gpu_load is not None:
                gc = usage_color(gpu_load)
                self.lbl_gpu.config(text=f"{gpu_load:5.1f}%", fg=gc)
                self._fill(self.bar_gpu, gpu_load, gc)
                parts = []
                if gpu_vram is not None: parts.append(f"VRAM:{gpu_vram:.0f}%")
                if gpu_temp is not None: parts.append(f"{gpu_temp:.0f}°C")
                self.lbl_vram.config(text="  ".join(parts) if parts else "",
                                     fg="#666")
            else:
                self.lbl_gpu.config(text="  N/A", fg="#3a3a3a")
                self.lbl_vram.config(
                    text="install pyadl or run LHM",
                    fg="#2a2a2a"
                )

            # ── Network ───────────────────────────────────────────────────
            now  = time.time()
            net  = psutil.net_io_counters()
            dt   = max(now - self._prev_net_t, 0.001)
            up   = (net.bytes_sent - self._prev_sent)  / dt
            down = (net.bytes_recv - self._prev_recv)  / dt
            self._prev_sent  = net.bytes_sent
            self._prev_recv  = net.bytes_recv
            self._prev_net_t = now
            self.lbl_net_up.config(text=fmt_speed(up))
            self.lbl_net_down.config(text=fmt_speed(down))

        except Exception:
            pass

        self.root.after(UPDATE_INTERVAL, self._update)

    # ── Drag ───────────────────────────────────────────────────────────────
    def _drag_start(self, e): self._drag_y = e.y_root
    def _drag_move(self, e):
        y = self.root.winfo_y() + (e.y_root - self._drag_y)
        self.root.geometry(f"+0+{y}")
        self._drag_y = e.y_root

    # ── Pin / unpin ────────────────────────────────────────────────────────
    def _toggle_pin(self, _=None):
        self._pinned_top = not self._pinned_top
        self.root.attributes("-topmost", self._pinned_top)
        self.btn_pin.config(fg="#39ff14" if self._pinned_top else "#444")


# ─── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    psutil.cpu_percent(interval=None)   # warm-up: first call always returns 0.0
    root = tk.Tk()
    SystemMonitorOverlay(root)
    root.mainloop()
