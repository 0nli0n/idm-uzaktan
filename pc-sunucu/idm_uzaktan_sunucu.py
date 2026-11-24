#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IDM Uzaktan - bilgisayar tarafi kopru sunucusu
================================================

Telefondaki "IDM Uzaktan" uygulamasinin bilgisayardaki Internet Download
Manager'i (IDM) yonetebilmesi icin kucuk bir HTTP sunucusu.

- Yalnizca Python standart kutuphanesini kullanir (ek kurulum gerekmez).
- Yalnizca yerel agdan (ev Wi-Fi'i) gelen baglantilari kabul eder.
- Her istek, ilk calistirmada uretilen 6 haneli PIN ile dogrulanir.

Calistirmak icin:  baslat.bat  (ya da: py -3 idm_uzaktan_sunucu.py)
"""

import ipaddress
import json
import mimetypes
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.2.1"
APP_ID = "idmuzaktan"
DISCOVERY_MAGIC = b"IDMUZAKTAN_KESIF"

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "sunucu.log")

IS_WIN = os.name == "nt"
FAKE = os.environ.get("IDMUZAKTAN_FAKE") == "1"  # yalnizca test icin

if IS_WIN:
    import winreg  # noqa: E402

idm_pencere = None
PENCERE_HATA = None
if IS_WIN:
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import idm_pencere  # noqa: E402  (ayni klasordeki modul)
    except Exception as _e:  # modul yoksa ya da yuklenemezse diger ozellikler calismaya devam eder
        PENCERE_HATA = repr(_e)

# pythonw ile (konsolsuz) calisinca stdout yoktur; ciktiyi dosyaya yonlendir.
if sys.stdout is None or sys.stderr is None:
    _log_file = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_file
    sys.stderr = _log_file


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    try:
        print(line, flush=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Ayarlar
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "port": 8765,
    "kesif_portu": 8766,
    "pin": "",
    "bilgisayar_adi": "",
    # Bos birakilirsa IDM otomatik bulunur.
    "idm_yolu": "",
    # Telefonda gosterilecek klasorler. Bos birakilirsa IDM'in varsayilan
    # klasoru ve kullanicinin "Indirilenler" klasoru kullanilir.
    "indirme_klasorleri": [],
    # IDM gecici klasoru (Secenekler > Kaydetme Yeri > Gecici klasor).
    # Bos birakilirsa %APPDATA%\IDM\DwnlData kullanilir.
    "idm_gecici_klasor": "",
    # Listede gosterilecek en fazla indirme sayisi
    "liste_siniri": 300,
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            log("UYARI: config.json okunamadi (%s), varsayilanlar kullaniliyor." % e)
    changed = False
    if not re.fullmatch(r"\d{6}", str(cfg.get("pin", ""))):
        cfg["pin"] = "%06d" % secrets.randbelow(1000000)
        changed = True
    if not cfg.get("bilgisayar_adi"):
        cfg["bilgisayar_adi"] = socket.gethostname()
        changed = True
    if changed or not os.path.exists(CONFIG_PATH):
        save_config(cfg)
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# IDM ile iletisim
# ---------------------------------------------------------------------------

REG_ROOT = r"Software\DownloadManager"
SENSITIVE = ("cookie", "pass", "auth", "user", "login", "referer", "post")


def _reg_values(key):
    vals = {}
    i = 0
    while True:
        try:
            name, data, typ = winreg.EnumValue(key, i)
        except OSError:
            break
        vals[name] = (data, typ)
        i += 1
    return vals


def _to_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    if isinstance(v, (bytes, bytearray)) and len(v) in (4, 8):
        return int.from_bytes(v, "little")
    return None


def _reg_str(data):
    """REG_SZ ya da UTF-16 olarak saklanmis REG_BINARY degerini metne cevirir."""
    if isinstance(data, str):
        return data.strip("\x00").strip()
    if isinstance(data, (bytes, bytearray)) and len(data) >= 4 and len(data) % 2 == 0:
        try:
            t = bytes(data).decode("utf-16-le").split("\x00")[0].strip()
        except UnicodeDecodeError:
            return None
        if t and all(c.isprintable() for c in t):
            return t
    return None


def _basename_any(p):
    return re.split(r"[\\/]", p.rstrip("\\/"))[-1] if p else ""


class IdmBackend:
    """Gercek IDM (Windows) ile konusan katman."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._prev = {}  # id -> (bytes, time) hiz hesabi icin
        self._lock = threading.Lock()
        self._fidx = None
        self._fidx_lock = threading.Lock()
        self._cat_cache = None

    # ---- IDM programi --------------------------------------------------
    def _reg_root_values(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_ROOT) as k:
                return _reg_values(k)
        except OSError:
            return {}

    def exe_path(self):
        p = self.cfg.get("idm_yolu") or ""
        if p and os.path.isfile(p):
            return p
        v = self._reg_root_values().get("ExePath")
        if v and isinstance(v[0], str) and os.path.isfile(v[0]):
            return v[0]
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
            if base:
                c = os.path.join(base, "Internet Download Manager", "IDMan.exe")
                if os.path.isfile(c):
                    return c
        return None

    def is_running(self):
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq IDMan.exe", "/NH"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
            return "idman.exe" in out.lower()
        except Exception:
            return None

    def _run(self, args):
        exe = self.exe_path()
        if not exe:
            raise ApiError(500, "IDM bulunamadı. config.json içindeki 'idm_yolu' ayarını doldurun.")
        log("IDM komutu: %s" % " ".join(args))
        subprocess.Popen([exe] + args, close_fds=True)

    def add_download(self, url, folder=None, filename=None, start_now=True):
        args = ["/d", url]
        if folder:
            args += ["/p", folder]
        if filename:
            args += ["/f", filename]
        args.append("/n")  # sessiz mod: soru sorma
        if not start_now:
            args.append("/a")  # yalnizca kuyruga ekle
        self._run(args)

    def start_queue(self):
        self._run(["/s"])

    def open_idm(self):
        self._run([])

    # ---- Pencere otomasyonu (tek indirmeyi duraklat/devam ettir) ----------
    def _window(self):
        if getattr(self, "_win", None) is None and idm_pencere is not None:
            self._win = idm_pencere.IdmPencere()
        return getattr(self, "_win", None)

    def window_supported(self):
        return self._window() is not None

    def _window_call(self, fn, allow_open):
        w = self._window()
        if w is None:
            raise ApiError(501, "Pencere otomasyonu bu bilgisayarda kullanılamıyor (%s)."
                           % (PENCERE_HATA or "idm_pencere.py dosyası eksik"))
        try:
            fn(w)
        except idm_pencere.PencereHatasi as e:
            if allow_open and "bulunamadı" in str(e) and "ana penceresi" in str(e):
                # IDM kapaliysa ac ve bir kez daha dene
                self.open_idm()
                time.sleep(4)
                try:
                    fn(w)
                    return
                except idm_pencere.PencereHatasi as e2:
                    raise ApiError(409, str(e2))
            raise ApiError(409, str(e))

    def item_action(self, name, action):
        self._window_call(lambda w: w.item_action(name, action), allow_open=(action == "devam"))

    def global_action(self, action):
        self._window_call(lambda w: w.global_action(action), allow_open=False)

    def window_diagnostics(self):
        w = self._window()
        if w is None:
            return {"bulundu": False, "hata": PENCERE_HATA or "idm_pencere.py yok"}
        return w.diagnostics()

    def name_for_id(self, did):
        for i, vals in self.raw_entries():
            if i == did:
                low = {k.lower(): v[0] for k, v in vals.items()}
                return self._display_name(low, did, "")
        return None

    def reveal(self, path):
        p = os.path.normpath(path).replace('"', "")
        subprocess.Popen('explorer /select,"%s"' % p)

    def default_dir(self):
        vals = self._reg_root_values()
        for name in ("LocalPathW", "LocalPath", "DefaultPath"):
            v = vals.get(name)
            t = _reg_str(v[0]) if v else None
            if t and os.path.isdir(t):
                return t
        return None

    def temp_base(self):
        p = self.cfg.get("idm_gecici_klasor") or ""
        if p and os.path.isdir(p):
            return p
        vals = self._reg_root_values()
        for name in ("TempPath", "TempPathW"):
            v = vals.get(name)
            t = _reg_str(v[0]) if v else None
            if t and os.path.isdir(t):
                d = os.path.join(t, "DwnlData")
                return d if os.path.isdir(d) else t
        appdata = os.environ.get("APPDATA")
        if appdata:
            d = os.path.join(appdata, "IDM", "DwnlData")
            if os.path.isdir(d):
                return d
        return None

    # ---- Indirme listesi -------------------------------------------------
    def raw_entries(self):
        """[(id:int, {deger_adi: (veri, tip)}), ...] en yeniden eskiye."""
        out = []
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_ROOT)
        except OSError:
            return out
        with root:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                if not name.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, name) as k:
                        vals = _reg_values(k)
                except OSError:
                    continue
                out.append((int(name), vals))
        out.sort(key=lambda x: x[0], reverse=True)
        return out

    def temp_index(self):
        """Gecici klasordeki yarim indirmeler: {anahtar: (bayt, son_degisim)}"""
        base = self.temp_base()
        idx = {}
        if not base:
            return idx
        dirs = []
        try:
            for e in os.scandir(base):
                if not e.is_dir():
                    continue
                dirs.append(e)
                # DwnlData\<kullanici>\<dosya>_<id> yapisi icin bir seviye daha
                try:
                    for e2 in os.scandir(e.path):
                        if e2.is_dir():
                            dirs.append(e2)
                except OSError:
                    pass
        except OSError:
            return idx
        for d in dirs:
            total, mtime, nfiles = 0, 0.0, 0
            try:
                for f in os.scandir(d.path):
                    if f.is_file():
                        st = f.stat()
                        nfiles += 1
                        if not f.name.lower().endswith(".log"):
                            total += st.st_size
                        mtime = max(mtime, st.st_mtime)
            except OSError:
                continue
            if nfiles == 0:
                continue
            m = re.search(r"_(\d+)$", d.name)
            if m:
                idx["id:" + m.group(1)] = (total, mtime)
            stem = re.sub(r"_\d+$", "", d.name).lower()
            idx.setdefault("ad:" + stem, (total, mtime))
        return idx

    # ---- Kategori / kayit klasorleri -----------------------------------
    def category_dirs(self):
        """IDM ayarlarinda gecen kayit klasorleri (kategori klasorleri dahil)."""
        now = time.time()
        if self._cat_cache and now - self._cat_cache[0] < 60:
            return self._cat_cache[1]
        found = []

        def collect(vals):
            for name, (data, _typ) in vals.items():
                n = name.lower()
                if "path" in n and "temp" not in n:
                    t = _reg_str(data)
                    if t:
                        p = os.path.expandvars(t)
                        if os.path.isdir(p):
                            found.append(p)

        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_ROOT)
        except OSError:
            root = None
        if root is not None:
            with root:
                collect(_reg_values(root))
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    if name.isdigit():
                        continue
                    try:
                        with winreg.OpenKey(root, name) as k:
                            collect(_reg_values(k))
                            j = 0
                            while j < 200:
                                try:
                                    sub = winreg.EnumKey(k, j)
                                except OSError:
                                    break
                                j += 1
                                try:
                                    with winreg.OpenKey(k, sub) as k2:
                                        collect(_reg_values(k2))
                                except OSError:
                                    pass
                    except OSError:
                        pass
        self._cat_cache = (now, found)
        return found

    def temp_parent(self):
        """IDM gecici klasorunun ust klasoru (ör. F:\\Indirilenler)."""
        base = self.temp_base()
        if base and os.path.basename(base.rstrip("\\/")).lower() == "dwnldata":
            return os.path.dirname(base.rstrip("\\/"))
        return None

    # ---- Indirme listesi -------------------------------------------------
    def file_index(self, roots):
        """Kok klasorlerdeki dosyalar: {kucuk_harf_ad: [(yol, boyut), ...]} (45 sn onbellek)."""
        now = time.time()
        key = tuple(roots)
        with self._fidx_lock:
            if self._fidx and self._fidx[0] == key and now - self._fidx[1] < 45:
                return self._fidx[2]
            idx, count = {}, 0
            for r in roots:
                stack = [(r, 0)]
                while stack and count < 200000:
                    d, depth = stack.pop()
                    try:
                        it = os.scandir(d)
                    except OSError:
                        continue
                    with it:
                        for e in it:
                            try:
                                if e.is_dir(follow_symlinks=False):
                                    if depth < 3 and e.name.lower() != "dwnldata" and not e.name.startswith("."):
                                        stack.append((e.path, depth + 1))
                                elif e.is_file():
                                    idx.setdefault(e.name.lower(), []).append((e.path, e.stat().st_size))
                                    count += 1
                            except OSError:
                                continue
            self._fidx = (key, now, idx)
            return idx

    def list_downloads(self, limit, roots=()):
        entries = self.raw_entries()[:limit]
        tidx = self.temp_index()
        fidx = self.file_index(list(roots)) if roots else {}
        now = time.time()
        result = []
        with self._lock:
            for did, vals in entries:
                result.append(self._parse(did, vals, tidx, fidx, now))
        return result

    @staticmethod
    def _display_name(low, did, url):
        for k in ("fr_fncd", "filename"):
            v = low.get(k)
            if isinstance(v, str) and v.strip():
                n = v.split("?")[0].strip()
                if n:
                    return n
        local = low.get("localfilename")
        if isinstance(local, str) and local:
            return _basename_any(local)
        n = urllib.parse.unquote(_basename_any(urllib.parse.urlparse(url).path))
        return n or ("indirme_%d" % did)

    def _parse(self, did, vals, tidx, fidx, now):
        low = {k.lower(): v[0] for k, v in vals.items()}
        url = low.get("url0") if isinstance(low.get("url0"), str) else ""
        if "://" not in (url or ""):
            url = ""
            for k in sorted(low):
                if k.startswith("url") and isinstance(low[k], str) and "://" in low[k]:
                    url = low[k]
                    break
        name = self._display_name(low, did, url)
        size = _to_int(low.get("filesize")) or _to_int(low.get("frfilesize")) or None
        reg_done = _to_int(low.get("downloaded")) or 0
        code = _to_int(low.get("status"))

        status, done_bytes, speed, path = "baslamadi", reg_done, 0, ""
        if code == 3 or (size and reg_done >= size):
            status = "tamamlandi"
            done_bytes = size or reg_done
            cands = fidx.get(name.lower(), [])
            if size:
                cands = [c for c in cands if c[1] == size] or []
            if cands:
                path = cands[0][0]
            self._prev.pop(did, None)
        else:
            t = tidx.get("id:%d" % did)
            active = False
            if t:
                tbytes, mtime = t
                done_bytes = max(done_bytes, tbytes)
                active = now - mtime < 10
            prev = self._prev.get(did)
            if prev and done_bytes > prev[0] and now - prev[1] < 20:
                active = True
                speed = int((done_bytes - prev[0]) / max(now - prev[1], 0.5))
            if not prev or now - prev[1] > 0.5:
                self._prev[did] = (done_bytes, now)
            if active and not speed:
                speed = _to_int(low.get("speed")) or 0
            if active:
                status = "indiriliyor"
            elif done_bytes > 0 or t:
                status = "yarim"
            if size and done_bytes > size:
                done_bytes = size
        return {
            "id": did,
            "dosya": name,
            "url": url,
            "yol": path,
            "boyut": size,
            "inen": done_bytes,
            "hiz": speed,
            "durum": status,
            "idm_durum": code,
        }

    # Tanilama raporunda tam gosterilecek alanlar. Digerlerinin yalnizca ADI gosterilir
    # (cerez, parola, ozel basliklar, imzali linkler raporlara asla girmez).
    SAFE_FIELDS = {"localfilename", "localpath", "filename", "fr_fncd", "status", "queueid",
                   "categoryid", "dateadded", "lasttrydate", "filesize", "frfilesize",
                   "downloaded", "speed", "bsaved", "frctype", "fgdfe", "bgicompl", "host"}

    def debug_info(self, roots=()):
        entries = self.raw_entries()
        sample = []
        for did, vals in entries[:5]:
            safe, others = {}, []
            for name, (data, typ) in vals.items():
                if name.lower() in self.SAFE_FIELDS:
                    if isinstance(data, (bytes, bytearray)):
                        iv = _to_int(data)
                        shown = iv if iv is not None else "<%d bayt>" % len(data)
                    else:
                        shown = str(data)
                        if "?" in shown:  # link parametreleri (token vb.) gizlenir
                            shown = shown.split("?")[0] + "?<gizlendi>"
                        shown = shown[:160]
                    safe[name] = {"tip": typ, "deger": shown}
                else:
                    others.append(name)
            sample.append({"id": did, "degerler": safe, "diger_alan_adlari": sorted(others)})
        parsed = []
        for d in self.list_downloads(8, roots):
            d = dict(d)
            d["url"] = urllib.parse.urlsplit(d["url"]).netloc if d["url"] else ""
            parsed.append(d)
        status_counts = {}
        for _did, vals in entries:
            v = vals.get("Status")
            k = str(v[0]) if v else "yok"
            status_counts[k] = status_counts.get(k, 0) + 1
        root_vals = {k: (_reg_str(v[0]) or str(v[0]))[:160] for k, v in self._reg_root_values().items()
                     if "path" in k.lower() or k.lower().startswith("exe")}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_ROOT) as root:
                subkeys, i = [], 0
                while i < 2000:
                    try:
                        n = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    if not n.isdigit():
                        subkeys.append(n)
        except (OSError, NameError):
            subkeys = []
        base = self.temp_base()
        tnames = []
        if base:
            try:
                for e in os.scandir(base):
                    tnames.append(e.name)
                    if e.is_dir():
                        try:
                            tnames += [e.name + "\\" + x for x in os.listdir(e.path)[:10]]
                        except OSError:
                            pass
            except OSError:
                pass
        return {
            "kayit_sayisi": len(entries),
            "durum_kodlari": status_counts,
            "uygulamada_gorunen": parsed,
            "ornek_kayitlar": sample,
            "kok_degerler": root_vals,
            "alt_anahtarlar": subkeys[:50],
            "kategori_klasorleri": self.category_dirs(),
            "gecici_klasor": base,
            "gecici_klasor_icerik": tnames[:40],
            "pencere": self.window_diagnostics(),
        }


class FakeBackend(IdmBackend):
    """Windows/IDM olmadan test etmek icin sahte katman (gercek IDM kayit bicimiyle)."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.base = os.path.join(APP_DIR, "_sahte")
        self.dl = os.path.join(self.base, "Downloads")
        self.tmpbase = os.path.join(self.base, "Indirilenler")
        self.tmp = os.path.join(self.tmpbase, "DwnlData", "kullanici")
        for d in (os.path.join(self.dl, "Video"), os.path.join(self.dl, "Compressed"), self.tmp,
                  os.path.join(self.tmpbase, "Filmler")):
            os.makedirs(d, exist_ok=True)
        done = os.path.join(self.dl, "Video", "film.mp4")
        if not os.path.exists(done):
            with open(done, "wb") as f:
                f.write(os.urandom(300000))
        part = os.path.join(self.tmp, "nexus-284_cdn_12")
        os.makedirs(part, exist_ok=True)
        with open(os.path.join(part, "nexus-284_cdn"), "wb") as f:
            f.write(b"\0" * 50000)
        q = lambda n: (n.to_bytes(8, "little"), 3)  # REG_BINARY 8 bayt
        tmpname = lambda n, i: (os.path.join(self.tmp, "%s_%d" % (n, i), n), 1)
        self.entries = [
            (12, {"Url0": ("https://nexus-416.cdn.st/dld/4def?token=GIZLI", 1),
                  "FileName": ("81efaabf?token=GIZLI", 1), "FR_FNCD": ("Oyun.v1.0.zip", 1),
                  "LocalFileName": tmpname("nexus-284_cdn", 12), "FileSize": q(200000),
                  "Downloaded": q(20000), "Status": (1, 4), "Speed": (8269610, 4),
                  "U0_c": ("_gh_sess=GIZLI_CEREZ", 1)}),
            (11, {"Url0": ("https://example.com/film.mp4", 1), "FileName": ("film.mp4", 1),
                  "FR_FNCD": ("film.mp4", 1), "LocalFileName": tmpname("film", 11),
                  "FileSize": q(300000), "Downloaded": q(300000), "Status": (3, 4),
                  "Cookie": ("gizli=1", 1), "CstmHdrs": ("Authorization: GIZLI", 1)}),
            (10, {"Url0": ("https://example.com/belge%20yeni.pdf", 1), "Status": (0, 4)}),
        ]
        self.commands = []

    def exe_path(self):
        return "IDMan.exe (sahte)"

    def is_running(self):
        return True

    def _run(self, args):
        log("SAHTE IDM komutu: %s" % args)
        self.commands.append(args)

    def reveal(self, path):
        log("SAHTE klasor ac: %s" % path)
        self.commands.append(["reveal", path])

    def default_dir(self):
        return None

    def window_supported(self):
        return True

    def item_action(self, name, action):
        if name == "hata.zip":
            raise ApiError(409, "Bu indirme IDM penceresindeki listede görünmüyor.")
        log("SAHTE pencere eylemi: %s -> %s" % (action, name))
        self.commands.append([action, name])

    def global_action(self, action):
        log("SAHTE genel eylem: %s" % action)
        self.commands.append([action])

    def window_diagnostics(self):
        return {"bulundu": True, "sahte": True}

    def category_dirs(self):
        return [self.dl, os.path.join(self.dl, "Compressed")]

    def temp_base(self):
        return os.path.dirname(self.tmp)

    def raw_entries(self):
        return list(self.entries)

    def _reg_root_values(self):
        return {"ExePath": ("IDMan.exe (sahte)", 1), "TempPath": (self.tmpbase, 1)}


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.idm = FakeBackend(cfg) if FAKE else IdmBackend(cfg)
        self.fails = {}  # ip -> [sayi, kilit_bitis]
        self.fail_lock = threading.Lock()

    def roots(self):
        cands = list(self.cfg.get("indirme_klasorleri") or [])
        if not cands:
            d = self.idm.default_dir()
            if d:
                cands.append(d)
            cands += self.idm.category_dirs()
            cands.append(os.path.join(os.path.expanduser("~"), "Downloads"))
            tp = self.idm.temp_parent()
            if tp:
                try:
                    if any(e.name.lower() != "dwnldata" for e in os.scandir(tp)):
                        cands.append(tp)
                except OSError:
                    pass
        norm = []
        for c in cands:
            c = os.path.abspath(os.path.expandvars(os.path.expanduser(c)))
            if os.path.isdir(c):
                norm.append((c, os.path.normcase(os.path.realpath(c))))
        uniq, seen = [], set()
        for c, key in norm:
            if key not in seen:
                seen.add(key)
                uniq.append((c, key))
        # baska bir kokun alt klasoru olanlari ele (ör. Downloads\Compressed)
        out = [c for c, key in uniq
               if not any(k != key and key.startswith(k.rstrip("\\/") + os.sep) for _, k in uniq)]
        return out[:10]

    def folders(self):
        res = []
        for r in self.roots():
            res.append(r)
            try:
                subs = sorted(e.path for e in os.scandir(r)
                              if e.is_dir() and not e.name.startswith(".") and e.name.lower() != "dwnldata")
                res += subs[:30]
            except OSError:
                pass
        return res

    def resolve_in_root(self, root_idx, rel):
        roots = self.roots()
        try:
            root = roots[int(root_idx)]
        except (ValueError, IndexError, TypeError):
            raise ApiError(404, "Klasör bulunamadı")
        rel = (rel or "").replace("\\", "/").strip("/")
        full = os.path.realpath(os.path.join(root, *[p for p in rel.split("/") if p]))
        root_real = os.path.realpath(root)
        if os.path.normcase(os.path.commonpath([full, root_real])) != os.path.normcase(root_real):
            raise ApiError(403, "İzin verilmeyen yol")
        return root, full

    def path_for_download(self, did):
        for d in self.idm.list_downloads(100000, self.roots()):
            if d["id"] == did:
                if d["durum"] != "tamamlandi":
                    raise ApiError(409, "Bu indirme henüz tamamlanmamış")
                if d["yol"] and os.path.isfile(d["yol"]):
                    return d["yol"]
                raise ApiError(404, "Dosya bilgisayarda bulunamadı. Taşınmış ya da silinmiş olabilir; "
                                    "Dosyalar sekmesinden arayın.")
        raise ApiError(404, "İndirme bulunamadı")

    # ---- dogrulama -------------------------------------------------------
    def check_pin(self, ip, pin):
        now = time.time()
        with self.fail_lock:
            cnt, until = self.fails.get(ip, [0, 0])
            if until > now:
                raise ApiError(429, "Çok fazla hatalı PIN. %d saniye sonra tekrar deneyin." % int(until - now))
            if pin and secrets.compare_digest(str(pin), str(self.cfg["pin"])):
                self.fails.pop(ip, None)
                return
            cnt += 1
            until = now + 300 if cnt >= 8 else 0
            self.fails[ip] = [0 if until else cnt, until]
        log("Hatali PIN denemesi: %s" % ip)
        raise ApiError(401, "PIN hatalı")


def is_local_ip(ip):
    try:
        a = ipaddress.ip_address(ip)
        if getattr(a, "ipv4_mapped", None):
            a = a.ipv4_mapped
        return a.is_private or a.is_loopback or a.is_link_local
    except ValueError:
        return False


INVALID_FN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class Handler(BaseHTTPRequestHandler):
    server_version = "IDMUzaktan/" + VERSION
    app = None  # type: App

    def log_message(self, fmt, *args):
        pass  # kendi loglarimizi kullaniyoruz

    # ---- yardimcilar -----------------------------------------------------
    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ApiError(413, "İstek çok büyük")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            raise ApiError(400, "Geçersiz JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "Geçersiz JSON")
        return data

    def _dispatch(self, method):
        try:
            ip = self.client_address[0]
            if not is_local_ip(ip):
                raise ApiError(403, "Yalnızca yerel ağdan erişilebilir")
            u = urllib.parse.urlsplit(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            path = u.path.rstrip("/") or "/"

            if path == "/":
                return self._send_html()
            if path == "/api/ping":
                return self._send_json(200, {"uygulama": APP_ID, "surum": VERSION,
                                             "ad": self.app.cfg["bilgisayar_adi"]})
            self.app.check_pin(ip, self.headers.get("X-Pin") or q.get("pin"))
            route = ROUTES.get((method, path))
            if route is None:
                raise ApiError(404, "Bulunamadı")
            return route(self, q)
        except ApiError as e:
            self._send_json(e.code, {"hata": e.msg})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:  # beklenmeyen hata
            log("HATA: %r" % e)
            try:
                self._send_json(500, {"hata": "Sunucu hatası: %s" % e})
            except Exception:
                pass

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _send_html(self):
        body = ("<!doctype html><meta charset=utf-8><title>IDM Uzaktan</title>"
                "<body style='font-family:sans-serif;padding:2em'>"
                "<h2>IDM Uzaktan sunucusu calisiyor</h2>"
                "<p>Telefonunuzdaki IDM Uzaktan uygulamasindan baglanin.</p>"
                "<p>Surum %s</p></body>" % VERSION).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # ---- uc noktalar -----------------------------------------------------
    def api_info(self, q):
        a = self.app
        exe = a.idm.exe_path()
        roots = a.roots()
        self._send_json(200, {
            "ad": a.cfg["bilgisayar_adi"],
            "surum": VERSION,
            "idm_bulundu": bool(exe),
            "idm_yolu": exe,
            "idm_calisiyor": a.idm.is_running() if exe else False,
            "pencere_otomasyonu": a.idm.window_supported(),
            "kokler": [{"no": i, "ad": os.path.basename(r.rstrip("\\/")) or r, "yol": r}
                       for i, r in enumerate(roots)],
            "klasorler": a.folders(),
        })

    def api_downloads(self, q):
        try:
            limit = max(1, min(int(q.get("sinir") or self.app.cfg["liste_siniri"]), 5000))
        except ValueError:
            limit = 300
        items = self.app.idm.list_downloads(limit, self.app.roots())
        self._send_json(200, {"indirmeler": items, "zaman": int(time.time())})

    def api_add(self, q):
        d = self._read_json()
        url = str(d.get("url") or "").strip()
        p = urllib.parse.urlsplit(url)
        if p.scheme.lower() not in ("http", "https", "ftp") or not p.netloc:
            raise ApiError(400, "Geçerli bir http/https/ftp adresi girin")
        if any(c in url for c in "\r\n\"") or len(url) > 8000:
            raise ApiError(400, "Adres geçersiz karakter içeriyor")
        folder = str(d.get("klasor") or "").strip() or None
        if folder:
            folder = os.path.abspath(folder)
            if not os.path.isdir(folder):
                raise ApiError(400, "Klasör bulunamadı: %s" % folder)
        filename = str(d.get("dosya_adi") or "").strip() or None
        if filename:
            filename = INVALID_FN.sub("_", filename).strip(" .")
            if not filename:
                filename = None
        start = bool(d.get("hemen_baslat", True))
        self.app.idm.add_download(url, folder, filename, start)
        log("Yeni indirme (%s): %s" % ("hemen" if start else "kuyruk", url[:120]))
        self._send_json(200, {"tamam": True,
                              "mesaj": "IDM'e gönderildi" if start else "Kuyruğa eklendi"})

    def api_queue_start(self, q):
        self.app.idm.start_queue()
        self._send_json(200, {"tamam": True, "mesaj": "Kuyruk başlatıldı"})

    def _download_name(self, d):
        try:
            did = int(d.get("id"))
        except (TypeError, ValueError):
            raise ApiError(400, "Geçersiz id")
        name = self.app.idm.name_for_id(did)
        if not name:
            raise ApiError(404, "İndirme bulunamadı")
        return name

    def api_item_resume(self, q):
        name = self._download_name(self._read_json())
        self.app.idm.item_action(name, "devam")
        log("Devam ettirildi: %s" % name)
        self._send_json(200, {"tamam": True, "mesaj": "Devam ettiriliyor: %s" % name})

    def api_item_pause(self, q):
        name = self._download_name(self._read_json())
        self.app.idm.item_action(name, "durdur")
        log("Duraklatıldı: %s" % name)
        self._send_json(200, {"tamam": True, "mesaj": "Duraklatıldı: %s" % name})

    def api_stop_all(self, q):
        self.app.idm.global_action("tumunu_durdur")
        self._send_json(200, {"tamam": True, "mesaj": "Tüm indirmeler durduruldu"})

    def api_queue_stop(self, q):
        self.app.idm.global_action("kuyrugu_durdur")
        self._send_json(200, {"tamam": True, "mesaj": "Kuyruk durduruldu"})

    def api_open_idm(self, q):
        self.app.idm.open_idm()
        self._send_json(200, {"tamam": True, "mesaj": "IDM açıldı"})

    def api_reveal(self, q):
        d = self._read_json()
        if d.get("id") is not None:
            path = self.app.path_for_download(int(d["id"]))
        else:
            _, path = self.app.resolve_in_root(d.get("kok"), d.get("yol"))
            if not os.path.exists(path):
                raise ApiError(404, "Dosya bulunamadı")
        self.app.idm.reveal(path)
        self._send_json(200, {"tamam": True, "mesaj": "Bilgisayarda klasör açıldı"})

    def api_files(self, q):
        root, full = self.app.resolve_in_root(q.get("kok", 0), q.get("yol", ""))
        if not os.path.isdir(full):
            raise ApiError(404, "Klasör bulunamadı")
        entries = []
        try:
            for e in os.scandir(full):
                if e.name.startswith(".") or e.name.lower() in ("desktop.ini", "dwnldata"):
                    continue
                try:
                    st = e.stat()
                except OSError:
                    continue
                is_dir = e.is_dir()
                entries.append({"ad": e.name, "klasor": is_dir,
                                "boyut": 0 if is_dir else st.st_size, "tarih": int(st.st_mtime)})
        except PermissionError:
            raise ApiError(403, "Bu klasöre erişim izni yok")
        entries.sort(key=lambda x: (not x["klasor"], -x["tarih"]))
        rel = os.path.relpath(full, os.path.realpath(root)).replace("\\", "/")
        self._send_json(200, {"kok": int(q.get("kok", 0)), "yol": "" if rel == "." else rel,
                              "ogeler": entries[:2000]})

    def api_file(self, q):
        if q.get("id"):
            try:
                path = self.app.path_for_download(int(q["id"]))
            except ValueError:
                raise ApiError(400, "Geçersiz id")
        else:
            _, path = self.app.resolve_in_root(q.get("kok", 0), q.get("yol", ""))
        if not os.path.isfile(path):
            raise ApiError(404, "Dosya bulunamadı")
        self._stream_file(path)

    def api_debug(self, q):
        info = self.app.idm.debug_info(self.app.roots())
        info.update({"surum": VERSION, "platform": sys.platform,
                     "python": sys.version.split()[0], "idm_yolu": self.app.idm.exe_path(),
                     "kokler": self.app.roots()})
        self._send_json(200, info)

    def _stream_file(self, path):
        size = os.path.getsize(path)
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        partial = False
        if rng:
            m = re.fullmatch(r"\s*bytes=(\d*)-(\d*)\s*", rng)
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                partial = True
        length = end - start + 1 if size else 0
        name = os.path.basename(path)
        ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", name) or "dosya"
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Disposition", "attachment; filename=\"%s\"; filename*=UTF-8''%s"
                         % (ascii_name, urllib.parse.quote(name)))
        if partial:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        if self.command == "HEAD" or length == 0:
            return
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


ROUTES = {
    ("GET", "/api/bilgi"): Handler.api_info,
    ("GET", "/api/indirmeler"): Handler.api_downloads,
    ("POST", "/api/indirmeler"): Handler.api_add,
    ("POST", "/api/kuyruk/baslat"): Handler.api_queue_start,
    ("POST", "/api/idm/ac"): Handler.api_open_idm,
    ("POST", "/api/indirme/devam"): Handler.api_item_resume,
    ("POST", "/api/indirme/duraklat"): Handler.api_item_pause,
    ("POST", "/api/tumunu-durdur"): Handler.api_stop_all,
    ("POST", "/api/kuyruk/durdur"): Handler.api_queue_stop,
    ("POST", "/api/klasoru-ac"): Handler.api_reveal,
    ("GET", "/api/dosyalar"): Handler.api_files,
    ("GET", "/api/dosya"): Handler.api_file,
    ("GET", "/api/tani"): Handler.api_debug,
}


# ---------------------------------------------------------------------------
# Telefonun bilgisayari otomatik bulmasi (UDP)
# ---------------------------------------------------------------------------

def discovery_loop(cfg):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("", int(cfg["kesif_portu"])))
    except OSError as e:
        log("UYARI: Otomatik bulma portu acilamadi (%s). Telefonda IP'yi elle girin." % e)
        return
    reply = json.dumps({"uygulama": APP_ID, "ad": cfg["bilgisayar_adi"],
                        "port": int(cfg["port"]), "surum": VERSION}).encode("utf-8")
    while True:
        try:
            data, addr = s.recvfrom(1024)
            if data.strip() == DISCOVERY_MAGIC and is_local_ip(addr[0]):
                s.sendto(reply, addr)
        except OSError:
            time.sleep(0.5)


def local_ips():
    ips = set()
    try:
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.connect(("192.168.255.255", 1))  # paket gonderilmez, yalnizca arayuz secilir
        ips.add(u.getsockname()[0])
        u.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except OSError:
        pass
    return sorted(ip for ip in ips if is_local_ip(ip) and not ip.startswith("127."))


def main():
    cfg = load_config()
    Handler.app = App(cfg)
    port = int(cfg["port"])
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    except OSError as e:
        log("HATA: %d portu açılamadı (%s). Sunucu zaten çalışıyor olabilir." % (port, e))
        if sys.stdin and sys.stdin.isatty():
            input("Kapatmak için Enter'a basın...")
        sys.exit(1)
    httpd.daemon_threads = True
    threading.Thread(target=discovery_loop, args=(cfg,), daemon=True).start()

    exe = Handler.app.idm.exe_path()
    print("=" * 56)
    print("  IDM Uzaktan sunucusu  v%s" % VERSION)
    print("=" * 56)
    print("  Bilgisayar adı : %s" % cfg["bilgisayar_adi"])
    for ip in local_ips() or ["(bulunamadı)"]:
        print("  Adres          : %s:%d" % (ip, port))
    print("  PIN            : %s" % cfg["pin"])
    print("  IDM            : %s" % (exe or "BULUNAMADI - config.json'da idm_yolu'nu ayarlayın"))
    print("=" * 56)
    print("  Telefonda uygulamayı açın; bilgisayar otomatik bulunur.")
    print("  Kapatmak için bu pencereyi kapatın (ya da Ctrl+C).")
    print(flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
