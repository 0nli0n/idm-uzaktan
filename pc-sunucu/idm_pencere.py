# -*- coding: utf-8 -*-
"""
IDM ana penceresini (Windows) uzaktan kullanma
================================================

IDM'in tek bir indirmeyi duraklatma/devam ettirme icin resmi bir arayuzu yok.
Bu modul IDM ana penceresindeki indirme listesinde ilgili satiri secer ve
IDM'in kendi arac cubugu dugmelerinin komutunu (Devam / Durdur / Tumunu durdur /
Kuyrugu durdur) gonderir - tipki elle tiklamak gibi.

Guvenlik:
- Dugmeler yalnizca METNINE gore bulunur; siraya gore asla tahmin yapilmaz
  (yanlislikla "Sil" dugmesine basilmasin diye).
- Komut gonderilmeden once listede tam olarak bir satirin secili oldugu ve
  bu satirin dogru dosya oldugu dogrulanir.

Yalnizca Python standart kutuphanesi (ctypes) kullanir.
"""

import ctypes
import os
import struct
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---- Win32 tanimlari -------------------------------------------------------
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                       wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = wintypes.LPVOID
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD]
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID, ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID, ctypes.c_size_t,
                                       ctypes.POINTER(ctypes.c_size_t)]
kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MEM_COMMIT, MEM_RESERVE, MEM_RELEASE = 0x1000, 0x2000, 0x8000
PAGE_READWRITE = 0x04
SMTO_ABORTIFHUNG = 0x0002
GA_ROOT = 2
WM_COMMAND = 0x0111

LVM_GETITEMCOUNT = 0x1004
LVM_SETITEMSTATE = 0x102B
LVM_GETITEMTEXTW = 0x1073
LVM_GETSELECTEDCOUNT = 0x1032
LVM_GETNEXTITEM = 0x100C
LVM_ENSUREVISIBLE = 0x1013
LVM_GETHEADER = 0x101F
HDM_GETITEMCOUNT = 0x1200
LVIF_TEXT, LVIF_STATE = 0x1, 0x8
LVIS_FOCUSED, LVIS_SELECTED = 0x1, 0x2
LVNI_SELECTED = 0x2

TB_GETBUTTON = 0x0417
TB_BUTTONCOUNT = 0x0418
TB_GETBUTTONTEXTW = 0x044B
BTNS_SEP = 0x1

TEXT_OFF = 512      # uzak tampon icinde metin alaninin baslangici
TEXT_CCH = 1024     # karakter


class PencereHatasi(Exception):
    pass


def _class(hwnd):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, b, 256)
    return b.value


def _title(hwnd):
    b = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, b, 512)
    return b.value


def _pid(hwnd):
    p = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def _image_name(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        b = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, b, ctypes.byref(n)):
            return b.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def _send(hwnd, msg, wparam=0, lparam=0, timeout=3000):
    res = ctypes.c_size_t()
    ok = user32.SendMessageTimeoutW(hwnd, msg, wparam, lparam, SMTO_ABORTIFHUNG, timeout, ctypes.byref(res))
    if not ok:
        raise PencereHatasi("IDM yanıt vermiyor (pencere mesajı zaman aşımına uğradı).")
    v = res.value
    # LRESULT isaretli olabilir (ör. -1)
    if v >= 1 << (8 * ctypes.sizeof(ctypes.c_size_t) - 1):
        v -= 1 << (8 * ctypes.sizeof(ctypes.c_size_t))
    return v


def _children(hwnd):
    out = []

    def cb(h, _l):
        out.append(h)
        return True

    user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
    return out


class _Remote:
    """IDM surecinde gecici bellek (ListView/Toolbar mesajlari icin)."""

    def __init__(self, pid, size=8192):
        self.h = kernel32.OpenProcess(
            PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_QUERY_INFORMATION, False, pid)
        if not self.h:
            raise PencereHatasi("IDM sürecine erişilemedi. IDM yönetici olarak çalışıyorsa sunucuyu da "
                                "yönetici olarak başlatın (baslat.bat'a sağ tık > Yönetici olarak çalıştır).")
        self.size = size
        self.addr = kernel32.VirtualAllocEx(self.h, None, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not self.addr:
            kernel32.CloseHandle(self.h)
            raise PencereHatasi("IDM sürecinde bellek ayrılamadı.")
        wow = wintypes.BOOL()
        kernel32.IsWow64Process(self.h, ctypes.byref(wow))
        self.is32 = bool(wow.value) or ctypes.sizeof(ctypes.c_void_p) == 4

    def write(self, off, data):
        n = ctypes.c_size_t()
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        if not kernel32.WriteProcessMemory(self.h, self.addr + off, buf, len(data), ctypes.byref(n)):
            raise PencereHatasi("IDM belleğine yazılamadı.")

    def read(self, off, size):
        buf = ctypes.create_string_buffer(size)
        n = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(self.h, self.addr + off, buf, size, ctypes.byref(n)):
            raise PencereHatasi("IDM belleği okunamadı.")
        return buf.raw[:n.value]

    def read_text(self):
        raw = self.read(TEXT_OFF, TEXT_CCH * 2)
        return raw.decode("utf-16-le", "ignore").split("\x00")[0]

    def clear_text(self):
        self.write(TEXT_OFF, b"\x00\x00")

    def close(self):
        if self.addr:
            kernel32.VirtualFreeEx(self.h, self.addr, 0, MEM_RELEASE)
            self.addr = None
        if self.h:
            kernel32.CloseHandle(self.h)
            self.h = None

    # ---- yapilar (hedef surecin 32/64 bit duzenine gore) ----------------
    def lvitem(self, mask, item=0, sub=0, state=0, state_mask=0):
        text = self.addr + TEXT_OFF
        if self.is32:
            return struct.pack("<IiiIIIiiiiiIIIi", mask, item, sub, state, state_mask,
                               text & 0xFFFFFFFF, TEXT_CCH, 0, 0, 0, 0, 0, 0, 0, 0)
        return struct.pack("<IiiII4xQiiqiiI4xQQi4x", mask, item, sub, state, state_mask,
                           text, TEXT_CCH, 0, 0, 0, 0, 0, 0, 0, 0)

    def tbbutton_size(self):
        return 20 if self.is32 else 32

    def parse_tbbutton(self, raw):
        _ibmp, cmd, st, style = struct.unpack_from("<iiBB", raw, 0)  # ilk alanlar iki duzende de ayni
        return cmd, st, style


# ---------------------------------------------------------------------------

def _norm(s):
    return (s or "").replace("&", "").strip().lower()


def classify_button(text):
    """Arac cubugu dugme metnini (Ingilizce/Turkce, kisaltmalar dahil) bir eyleme esler."""
    t = " ".join(_norm(text).split())
    if not t:
        return None
    has = lambda *ws: any(w in t for w in ws)
    # Turkce IDM kisaltmalari: "T. Durdur" (Tumunu), "K. Durdur" / "K. Baslat" (Kuyrugu)
    if t.startswith("t.") and has("durdur"):
        return "tumunu_durdur"
    if t.startswith("k."):
        if has("durdur"):
            return "kuyrugu_durdur"
        if has("başlat", "baslat"):
            return "kuyrugu_baslat"
        return None
    queue = has("queue", "kuyru")
    stop = has("stop", "durdur", "duraklat", "pause")
    if queue and stop:
        return "kuyrugu_durdur"
    if queue and has("start", "başlat", "baslat"):
        return "kuyrugu_baslat"
    if stop and (has("tümü", "tumu", "hepsi") or t.endswith(" all") or " all " in t or t.startswith("all ")):
        return "tumunu_durdur"
    if stop:
        return "durdur"
    if has("resume", "devam", "sürdür", "surdur"):
        return "devam"
    return None


class IdmPencere:
    def __init__(self):
        self.lock = threading.Lock()

    # ---- pencereyi bul ----------------------------------------------------
    def _find(self):
        tops = []

        def cb(h, _l):
            tops.append(h)
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        names = {}
        best = None
        for h in tops:
            pid = _pid(h)
            if pid not in names:
                names[pid] = _image_name(pid)
            if names[pid] != "idman.exe":
                continue
            kids = _children(h)
            lists = [k for k in kids if _class(k) == "SysListView32"]
            bars = [k for k in kids if _class(k) == "ToolbarWindow32"]
            if not lists or not bars:
                continue
            counts = []
            for lv in lists:
                try:
                    counts.append((_send(lv, LVM_GETITEMCOUNT), lv))
                except PencereHatasi:
                    counts.append((-1, lv))
            counts.sort(key=lambda x: x[0], reverse=True)
            cand = (counts[0][0], h, counts[0][1], bars, pid)
            if best is None or cand[0] > best[0]:
                best = cand
        if best is None:
            return None
        _n, main, lv, bars, pid = best
        return {"ana": main, "liste": lv, "araclar": bars, "pid": pid}

    def find(self):
        w = self._find()
        if w is None:
            raise PencereHatasi("IDM ana penceresi bulunamadı. IDM'in açık olduğundan emin olun.")
        return w

    # ---- okuma ------------------------------------------------------------
    def _item_text(self, rm, lv, item, sub=0):
        rm.clear_text()
        rm.write(0, rm.lvitem(LVIF_TEXT, item, sub))
        _send(lv, LVM_GETITEMTEXTW, item, rm.addr)
        return rm.read_text()

    def _buttons(self, rm, bars):
        res = []
        for tb in bars:
            n = _send(tb, TB_BUTTONCOUNT)
            for i in range(max(0, min(n, 64))):
                if not _send(tb, TB_GETBUTTON, i, rm.addr):
                    continue
                cmd, st, style = rm.parse_tbbutton(rm.read(0, rm.tbbutton_size()))
                sep = bool(style & BTNS_SEP)
                text = ""
                if not sep:
                    rm.clear_text()
                    if _send(tb, TB_GETBUTTONTEXTW, cmd, rm.addr + TEXT_OFF) > 0:
                        text = rm.read_text()
                res.append({"arac": tb, "sira": i, "id": cmd, "metin": text, "ayirici": sep,
                            "eylem": None if sep else classify_button(text), "durum": st})
        return res

    # ---- eylemler -----------------------------------------------------------
    def _button_for(self, w, rm, action):
        btns = [b for b in self._buttons(rm, w["araclar"]) if b["eylem"] == action]
        if not btns:
            raise PencereHatasi("IDM araç çubuğunda gerekli düğme bulunamadı (%s). Tanılama bilgisini "
                                "gönderin." % action)
        if len({b["id"] for b in btns}) > 1:
            raise PencereHatasi("IDM araç çubuğunda bu işe uyan birden fazla düğme var (%s); güvenlik "
                                "için işlem yapılmadı. Tanılama bilgisini gönderin."
                                % ", ".join(b["metin"] for b in btns))
        return btns[0]

    def _post(self, w, b):
        root = user32.GetAncestor(b["arac"], GA_ROOT) or w["ana"]
        if not user32.PostMessageW(root, WM_COMMAND, b["id"] & 0xFFFF, 0):
            raise PencereHatasi("Komut IDM'e gönderilemedi.")

    def _select(self, w, rm, name):
        lv = w["liste"]
        n = _send(lv, LVM_GETITEMCOUNT)
        target = _norm(name)
        exact, loose = None, None
        for i in range(n):
            t = _norm(self._item_text(rm, lv, i, 0))
            if t == target:
                exact = i
                break
            if loose is None and t and (t.startswith(target) or target.startswith(t)):
                loose = i
        idx = exact if exact is not None else loose
        matched = _norm(self._item_text(rm, lv, idx, 0)) if idx is not None else None
        if idx is None:
            raise PencereHatasi("Bu indirme IDM penceresindeki listede görünmüyor. IDM'de soldaki "
                                "kategorilerden 'Tüm indirmeler'i seçin ve tekrar deneyin.")
        # once tum secimi kaldir, sonra yalnizca bu satiri sec
        rm.write(0, rm.lvitem(LVIF_STATE, 0, 0, 0, LVIS_SELECTED | LVIS_FOCUSED))
        _send(lv, LVM_SETITEMSTATE, (1 << (8 * ctypes.sizeof(ctypes.c_size_t))) - 1, rm.addr)
        rm.write(0, rm.lvitem(LVIF_STATE, idx, 0, LVIS_SELECTED | LVIS_FOCUSED, LVIS_SELECTED | LVIS_FOCUSED))
        _send(lv, LVM_SETITEMSTATE, idx, rm.addr)
        _send(lv, LVM_ENSUREVISIBLE, idx, 0)
        time.sleep(0.05)
        # dogrulama
        if _send(lv, LVM_GETSELECTEDCOUNT) != 1:
            raise PencereHatasi("IDM listesinde satır seçilemedi; güvenlik için işlem yapılmadı.")
        sel = _send(lv, LVM_GETNEXTITEM, (1 << (8 * ctypes.sizeof(ctypes.c_size_t))) - 1, LVNI_SELECTED)
        if sel != idx or _norm(self._item_text(rm, lv, sel, 0)) != matched:
            raise PencereHatasi("Seçilen satır doğrulanamadı; güvenlik için işlem yapılmadı.")
        return idx

    def item_action(self, name, action):
        """action: 'devam' ya da 'durdur'"""
        with self.lock:
            w = self.find()
            rm = _Remote(w["pid"])
            try:
                b = self._button_for(w, rm, action)  # once dugme var mi bak
                self._select(w, rm, name)
                self._post(w, b)
            finally:
                rm.close()

    def global_action(self, action):
        """action: 'tumunu_durdur' ya da 'kuyrugu_durdur'"""
        with self.lock:
            w = self.find()
            rm = _Remote(w["pid"])
            try:
                self._post(w, self._button_for(w, rm, action))
            finally:
                rm.close()

    # ---- tanilama -----------------------------------------------------------
    def diagnostics(self):
        info = {"bulundu": False}
        try:
            with self.lock:
                w = self._find()
                if w is None:
                    info["hata"] = "IDM ana penceresi bulunamadı (IDM kapalı olabilir)."
                    return info
                info.update({"bulundu": True, "sinif": _class(w["ana"]), "baslik": _title(w["ana"])})
                rm = _Remote(w["pid"])
                try:
                    info["hedef_32bit"] = rm.is32
                    lv = w["liste"]
                    n = _send(lv, LVM_GETITEMCOUNT)
                    hdr = _send(lv, LVM_GETHEADER)
                    cols = _send(hdr, HDM_GETITEMCOUNT) if hdr else 0
                    info["liste_satir_sayisi"] = n
                    info["sutun_sayisi"] = cols
                    info["ilk_satirlar"] = [[self._item_text(rm, lv, i, c) for c in range(min(cols or 1, 5))]
                                            for i in range(min(n, 4))]
                    info["arac_dugmeleri"] = [
                        {k: v for k, v in b.items() if k != "arac"} for b in self._buttons(rm, w["araclar"])]
                finally:
                    rm.close()
        except PencereHatasi as e:
            info["hata"] = str(e)
        except Exception as e:  # tanilama asla sunucuyu dusurmemeli
            info["hata"] = "Beklenmeyen hata: %r" % e
        return info
