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

VERSION = "1.0.0"
APP_ID = "idmuzaktan"
DISCOVERY_MAGIC = b"IDMUZAKTAN_KESIF"

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "sunucu.log")

IS_WIN = os.name == "nt"
FAKE = os.environ.get("IDMUZAKTAN_FAKE") == "1"  # yalnizca test icin

if IS_WIN:
    import winreg  # noqa: E402

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


def _basename_any(p):
    return re.split(r"[\\/]", p.rstrip("\\/"))[-1] if p else ""


class IdmBackend:
    """Gercek IDM (Windows) ile konusan katman."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._prev = {}  # id -> (bytes, time) hiz hesabi icin
        self._lock = threading.Lock()

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

    def reveal(self, path):
        p = os.path.normpath(path).replace('"', "")
        subprocess.Popen('explorer /select,"%s"' % p)

    def default_dir(self):
        vals = self._reg_root_values()
        for name in ("LocalPathW", "LocalPath", "DefaultPath"):
            v = vals.get(name)
            if v and isinstance(v[0], str) and os.path.isdir(v[0]):
                return v[0]
        return None

    def temp_base(self):
        p = self.cfg.get("idm_gecici_klasor") or ""
        if p and os.path.isdir(p):
            return p
        vals = self._reg_root_values()
        for name in ("TempPath", "TempPathW"):
            v = vals.get(name)
            if v and isinstance(v[0], str) and os.path.isdir(v[0]):
                d = os.path.join(v[0], "DwnlData")
                return d if os.path.isdir(d) else v[0]
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

    def list_downloads(self, limit):
        entries = self.raw_entries()[:limit]
        tidx = self.temp_index()
        now = time.time()
        result = []
        with self._lock:
            for did, vals in entries:
                result.append(self._parse(did, vals, tidx, now))
        return result

    def _parse(self, did, vals, tidx, now):
        low = {k.lower(): v[0] for k, v in vals.items()}
        url = ""
        for k in sorted(low):
            if k.startswith("url") and isinstance(low[k], str) and "://" in low[k]:
                url = low[k]
                break
        local = low.get("localfilename") if isinstance(low.get("localfilename"), str) else ""
        fname = low.get("filename") if isinstance(low.get("filename"), str) else ""
        if not fname:
            fname = _basename_any(local) or urllib.parse.unquote(
                _basename_any(urllib.parse.urlparse(url).path)) or ("indirme_%d" % did)
        size = None
        for k in ("filesize", "totalsize", "size"):
            if k in low:
                size = _to_int(low[k])
                if size:
                    break
        size = size or None

        status, done_bytes, speed = "baslamadi", 0, 0
        if local and os.path.isfile(local):
            fsz = os.path.getsize(local)
            if size is None or fsz >= size:
                status, done_bytes = "tamamlandi", fsz
                size = size or fsz
        if status != "tamamlandi":
            stem = os.path.splitext(fname)[0].lower()
            t = tidx.get("id:%d" % did) or tidx.get("ad:" + fname.lower()) or tidx.get("ad:" + stem)
            if t:
                done_bytes, mtime = t
                status = "indiriliyor" if now - mtime < 10 else "yarim"
                prev = self._prev.get(did)
                if prev and now - prev[1] > 0.5 and done_bytes > prev[0]:
                    speed = int((done_bytes - prev[0]) / (now - prev[1]))
                if not prev or now - prev[1] > 0.5:
                    self._prev[did] = (done_bytes, now)
                if size and done_bytes > size:
                    done_bytes = size
        return {
            "id": did,
            "dosya": fname,
            "url": url,
            "yol": local,
            "boyut": size,
            "inen": done_bytes,
            "hiz": speed,
            "durum": status,
        }

    def debug_info(self):
        sample = []
        for did, vals in self.raw_entries()[:3]:
            items = {}
            for name, (data, typ) in vals.items():
                if any(s in name.lower() for s in SENSITIVE):
                    shown = "<gizlendi>"
                elif isinstance(data, (bytes, bytearray)):
                    shown = "<%d bayt ikili veri>" % len(data)
                else:
                    shown = str(data)[:160]
                items[name] = {"tip": typ, "deger": shown}
            sample.append({"id": did, "degerler": items})
        root_vals = {k: str(v[0])[:160] for k, v in self._reg_root_values().items()
                     if k.lower().endswith("path") or k.lower().startswith("exe")}
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
            "kayit_sayisi": len(self.raw_entries()),
            "ornek_kayitlar": sample,
            "kok_degerler": root_vals,
            "gecici_klasor": base,
            "gecici_klasor_icerik": tnames[:40],
        }


class FakeBackend(IdmBackend):
    """Windows/IDM olmadan test etmek icin sahte katman."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.base = os.path.join(APP_DIR, "_sahte")
        self.dl = os.path.join(self.base, "Downloads")
        self.tmp = os.path.join(self.base, "DwnlData", "kullanici")
        os.makedirs(os.path.join(self.dl, "Video"), exist_ok=True)
        os.makedirs(self.tmp, exist_ok=True)
        done = os.path.join(self.dl, "Video", "film.mp4")
        if not os.path.exists(done):
            with open(done, "wb") as f:
                f.write(os.urandom(300000))
        part = os.path.join(self.tmp, "ubuntu_12")
        os.makedirs(part, exist_ok=True)
        with open(os.path.join(part, "ubuntu.iso"), "wb") as f:
            f.write(b"\0" * 50000)
        self.entries = [
            (12, {"Url0": ("https://example.com/ubuntu.iso", 1), "FileName": ("ubuntu.iso", 1),
                  "LocalFileName": (os.path.join(self.dl, "ubuntu.iso"), 1), "FileSize": (200000, 4)}),
            (11, {"Url0": ("https://example.com/film.mp4", 1), "FileName": ("film.mp4", 1),
                  "LocalFileName": (done, 1), "FileSize": (300000, 4), "Cookies": ("gizli=1", 1)}),
            (10, {"Url0": ("https://example.com/belge%20yeni.pdf", 1)}),
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
        return self.dl

    def temp_base(self):
        return os.path.dirname(self.tmp)

    def raw_entries(self):
        return list(self.entries)

    def _reg_root_values(self):
        return {"ExePath": ("IDMan.exe (sahte)", 1)}


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
            cands.append(os.path.join(os.path.expanduser("~"), "Downloads"))
        out, seen = [], set()
        for c in cands:
            c = os.path.abspath(os.path.expandvars(os.path.expanduser(c)))
            key = os.path.normcase(os.path.realpath(c))
            if os.path.isdir(c) and key not in seen:
                seen.add(key)
                out.append(c)
        return out

    def folders(self):
        res = []
        for r in self.roots():
            res.append(r)
            try:
                subs = sorted(e.path for e in os.scandir(r) if e.is_dir() and not e.name.startswith("."))
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
        for d in self.idm.list_downloads(100000):
            if d["id"] == did:
                if d["durum"] == "tamamlandi" and d["yol"] and os.path.isfile(d["yol"]):
                    return d["yol"]
                raise ApiError(409, "Bu indirme henüz tamamlanmamış")
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
            "kokler": [{"no": i, "ad": os.path.basename(r.rstrip("\\/")) or r, "yol": r}
                       for i, r in enumerate(roots)],
            "klasorler": a.folders(),
        })

    def api_downloads(self, q):
        try:
            limit = max(1, min(int(q.get("sinir") or self.app.cfg["liste_siniri"]), 5000))
        except ValueError:
            limit = 300
        items = self.app.idm.list_downloads(limit)
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
                if e.name.startswith(".") or e.name.lower() == "desktop.ini":
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
        info = self.app.idm.debug_info()
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
