package com.idmuzaktan.app

import android.app.Application
import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.launch

class AppViewModel(app: Application) : AndroidViewModel(app) {

    private val prefs = app.getSharedPreferences("baglanti", Context.MODE_PRIVATE)

    // ---- baglanti ----------------------------------------------------------
    var connection by mutableStateOf<Connection?>(loadConnection())
        private set
    private var api: IdmApi? = connection?.let { IdmApi(it) }

    var info by mutableStateOf<ServerInfo?>(null)
        private set

    var connecting by mutableStateOf(false)
        private set
    var connectError by mutableStateOf<String?>(null)
        private set

    var scanning by mutableStateOf(false)
        private set
    var found by mutableStateOf<List<FoundServer>>(emptyList())
        private set

    // ---- indirmeler --------------------------------------------------------
    var downloads by mutableStateOf<List<DownloadItem>>(emptyList())
        private set
    var downloadsLoaded by mutableStateOf(false)
        private set
    var downloadsError by mutableStateOf<String?>(null)
        private set
    var refreshing by mutableStateOf(false)
        private set

    // ---- dosyalar ----------------------------------------------------------
    var listing by mutableStateOf<FolderListing?>(null)
        private set
    var filesLoading by mutableStateOf(false)
        private set
    var filesError by mutableStateOf<String?>(null)
        private set

    // ---- diger -------------------------------------------------------------
    /** Paylas menusunden gelen link; ekleme penceresini acar. */
    var pendingUrl by mutableStateOf<String?>(null)

    var diagnostics by mutableStateOf<String?>(null)

    private val _messages = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val messages: SharedFlow<String> = _messages

    private fun toast(msg: String) {
        _messages.tryEmit(msg)
    }

    private fun loadConnection(): Connection? {
        val host = prefs.getString("host", null) ?: return null
        val pin = prefs.getString("pin", null) ?: return null
        return Connection(host, prefs.getInt("port", DEFAULT_PORT), pin, prefs.getString("ad", host) ?: host)
    }

    fun discover() {
        if (scanning) return
        scanning = true
        viewModelScope.launch {
            found = try {
                Discovery.discover()
            } catch (e: Exception) {
                emptyList()
            }
            scanning = false
        }
    }

    fun connect(host: String, port: Int, pin: String, name: String?) {
        val h = host.trim()
        if (h.isEmpty()) {
            connectError = "Bilgisayarın IP adresini girin"
            return
        }
        if (pin.length != 6) {
            connectError = "PIN 6 haneli olmalı (bilgisayardaki pencerede yazar)"
            return
        }
        connecting = true
        connectError = null
        viewModelScope.launch {
            val c = Connection(h, port, pin, name ?: h)
            try {
                val i = IdmApi(c).info()
                val named = c.copy(name = i.name)
                prefs.edit()
                    .putString("host", named.host)
                    .putInt("port", named.port)
                    .putString("pin", named.pin)
                    .putString("ad", named.name)
                    .putString("son_host", named.host)
                    .putInt("son_port", named.port)
                    .apply()
                api = IdmApi(named)
                connection = named
                info = i
                downloads = emptyList()
                downloadsLoaded = false
                listing = null
            } catch (e: Exception) {
                connectError = e.message ?: "Bağlanılamadı"
            } finally {
                connecting = false
            }
        }
    }

    /** Son kullanilan adres: baglanti ekraninda hazir doldurulur. */
    val lastHost: String get() = prefs.getString("son_host", "") ?: ""
    val lastPort: Int get() = prefs.getInt("son_port", DEFAULT_PORT)

    fun disconnect() {
        prefs.edit().remove("host").remove("pin").apply()
        api = null
        connection = null
        info = null
        downloads = emptyList()
        downloadsLoaded = false
        listing = null
        connectError = null
    }

    fun refreshInfo() {
        val a = api ?: return
        viewModelScope.launch {
            try {
                info = a.info()
            } catch (e: ApiException) {
                if (e.code == 401) handleAuthError(e) else downloadsError = e.message
            }
        }
    }

    private fun handleAuthError(e: ApiException) {
        val msg = (e.message ?: "PIN hatalı") + " — PIN değişmiş olabilir, tekrar bağlanın."
        disconnect()
        connectError = msg
    }

    /** silent=true: arka plan yenilemesi (yukleniyor gostergesi yok). */
    suspend fun loadDownloads(silent: Boolean) {
        val a = api ?: return
        if (!silent) refreshing = true
        try {
            downloads = a.downloads()
            downloadsError = null
            downloadsLoaded = true
            if (info == null) info = a.info()
        } catch (e: ApiException) {
            if (e.code == 401) handleAuthError(e) else downloadsError = e.message
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            downloadsError = e.message
        } finally {
            refreshing = false
        }
    }

    fun refreshDownloads() {
        viewModelScope.launch { loadDownloads(silent = false) }
    }

    private fun action(block: suspend (IdmApi) -> String, after: (() -> Unit)? = null) {
        val a = api ?: return
        viewModelScope.launch {
            try {
                toast(block(a))
                after?.invoke()
                loadDownloads(silent = true)
            } catch (e: ApiException) {
                if (e.code == 401) handleAuthError(e) else toast(e.message ?: "Hata")
            } catch (e: Exception) {
                toast(e.message ?: "Hata")
            }
        }
    }

    fun addDownload(url: String, fileName: String?, folder: String?, startNow: Boolean) =
        action({ it.addDownload(url, fileName, folder, startNow) })

    fun startQueue() = action({ it.startQueue() })
    fun openIdm() = action({ it.openIdm() }, after = { refreshInfo() })
    fun reveal(item: DownloadItem) = action({ it.revealDownload(item.id) })
    fun reveal(root: Int, path: String) = action({ it.revealFile(root, path) })

    fun loadDiagnostics() {
        val a = api ?: return
        diagnostics = "Yükleniyor…"
        viewModelScope.launch {
            diagnostics = try {
                a.diagnostics()
            } catch (e: Exception) {
                "Hata: ${e.message}"
            }
        }
    }

    // ---- dosya gezgini ---------------------------------------------------
    fun openFolder(root: Int, path: String) {
        val a = api ?: return
        filesLoading = true
        filesError = null
        viewModelScope.launch {
            try {
                listing = a.files(root, path)
            } catch (e: ApiException) {
                if (e.code == 401) handleAuthError(e) else filesError = e.message
            } catch (e: Exception) {
                filesError = e.message
            } finally {
                filesLoading = false
            }
        }
    }

    fun folderUp() {
        val l = listing ?: return
        if (l.path.isEmpty()) return
        openFolder(l.root, l.path.substringBeforeLast('/', ""))
    }

    // ---- telefona indirme ------------------------------------------------
    fun downloadToPhone(item: DownloadItem) {
        val a = api ?: return
        enqueuePhoneDownload(a.downloadUrlForId(item.id), item.fileName, a.pin)
    }

    fun downloadToPhone(root: Int, path: String, name: String) {
        val a = api ?: return
        enqueuePhoneDownload(a.downloadUrlForFile(root, path), name, a.pin)
    }

    private fun enqueuePhoneDownload(url: String, name: String, pin: String) {
        val ctx = getApplication<Application>()
        val safe = name.replace(Regex("[\\\\/:*?\"<>|]"), "_").ifBlank { "dosya" }
        try {
            val req = DownloadManager.Request(Uri.parse(url))
                .addRequestHeader("X-Pin", pin)
                .setTitle(safe)
                .setDescription("Bilgisayardan aktarılıyor")
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "IDM Uzaktan/$safe")
            } else {
                req.setDestinationInExternalFilesDir(ctx, Environment.DIRECTORY_DOWNLOADS, safe)
            }
            val dm = ctx.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            dm.enqueue(req)
            toast("Telefona indiriliyor: İndirilenler/IDM Uzaktan")
        } catch (e: Exception) {
            toast("Telefona indirilemedi: ${e.message}")
        }
    }
}
