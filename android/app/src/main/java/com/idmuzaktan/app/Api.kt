package com.idmuzaktan.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket
import java.net.SocketTimeoutException
import java.net.URL
import java.net.URLEncoder
import java.util.Collections

const val DEFAULT_PORT = 8765
const val DISCOVERY_PORT = 8766
private const val DISCOVERY_MAGIC = "IDMUZAKTAN_KESIF"
private const val APP_ID = "idmuzaktan"

// ---------------------------------------------------------------------------
// Veri modelleri
// ---------------------------------------------------------------------------

data class Connection(val host: String, val port: Int, val pin: String, val name: String)

data class RootFolder(val no: Int, val name: String, val path: String)

data class ServerInfo(
    val name: String,
    val version: String,
    val idmFound: Boolean,
    val idmPath: String?,
    val idmRunning: Boolean,
    val roots: List<RootFolder>,
    val folders: List<String>,
    val windowAutomation: Boolean,
)

enum class DlStatus { DONE, DOWNLOADING, PARTIAL, NOT_STARTED }

data class DownloadItem(
    val id: Int,
    val fileName: String,
    val url: String,
    val path: String,
    val size: Long?,
    val downloaded: Long,
    val speed: Long,
    val status: DlStatus,
) {
    val progress: Float?
        get() = if (size != null && size > 0) (downloaded.toFloat() / size).coerceIn(0f, 1f) else null
}

data class FileEntry(val name: String, val isDir: Boolean, val size: Long, val date: Long)

data class FolderListing(val root: Int, val path: String, val items: List<FileEntry>)

data class FoundServer(val name: String, val host: String, val port: Int)

class ApiException(message: String, val code: Int = 0) : Exception(message)

// ---------------------------------------------------------------------------
// Sunucu istemcisi
// ---------------------------------------------------------------------------

class IdmApi(private val conn: Connection) {

    private val base = "http://${conn.host}:${conn.port}"

    private fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")

    private fun request(method: String, path: String, body: JSONObject? = null, readTimeout: Int = 10_000): JSONObject {
        val c = try {
            URL(base + path).openConnection() as HttpURLConnection
        } catch (e: Exception) {
            throw ApiException("Geçersiz adres: ${conn.host}")
        }
        try {
            c.requestMethod = method
            c.connectTimeout = 4_000
            c.readTimeout = readTimeout
            c.useCaches = false
            c.setRequestProperty("X-Pin", conn.pin)
            c.setRequestProperty("Accept", "application/json")
            if (body != null) {
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                c.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val code = c.responseCode
            val stream = if (code in 200..299) c.inputStream else c.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            val json = try {
                JSONObject(text)
            } catch (e: JSONException) {
                JSONObject()
            }
            if (code !in 200..299) {
                val msg = json.optString("hata", "")
                throw ApiException(if (msg.isNotBlank()) msg else "Sunucu hatası ($code)", code)
            }
            return json
        } catch (e: ApiException) {
            throw e
        } catch (e: IOException) {
            throw ApiException("Bilgisayara ulaşılamadı. Sunucu açık mı, telefon aynı Wi-Fi'da mı?")
        } finally {
            c.disconnect()
        }
    }

    suspend fun info(): ServerInfo = withContext(Dispatchers.IO) {
        val o = request("GET", "/api/bilgi")
        val roots = mutableListOf<RootFolder>()
        o.optJSONArray("kokler")?.forEachObject {
            roots += RootFolder(it.optInt("no"), it.optString("ad"), it.optString("yol"))
        }
        val folders = mutableListOf<String>()
        o.optJSONArray("klasorler")?.let { arr ->
            for (i in 0 until arr.length()) folders += arr.optString(i)
        }
        ServerInfo(
            name = o.optString("ad", conn.name),
            version = o.optString("surum"),
            idmFound = o.optBoolean("idm_bulundu"),
            idmPath = if (o.isNull("idm_yolu")) null else o.optString("idm_yolu"),
            idmRunning = o.optBoolean("idm_calisiyor"),
            roots = roots,
            folders = folders,
            windowAutomation = o.optBoolean("pencere_otomasyonu", false),
        )
    }

    suspend fun downloads(): List<DownloadItem> = withContext(Dispatchers.IO) {
        val o = request("GET", "/api/indirmeler")
        val list = mutableListOf<DownloadItem>()
        o.optJSONArray("indirmeler")?.forEachObject {
            list += DownloadItem(
                id = it.optInt("id"),
                fileName = it.optString("dosya"),
                url = it.optString("url"),
                path = it.optString("yol"),
                size = if (it.isNull("boyut")) null else it.optLong("boyut"),
                downloaded = it.optLong("inen"),
                speed = it.optLong("hiz"),
                status = when (it.optString("durum")) {
                    "tamamlandi" -> DlStatus.DONE
                    "indiriliyor" -> DlStatus.DOWNLOADING
                    "yarim" -> DlStatus.PARTIAL
                    else -> DlStatus.NOT_STARTED
                },
            )
        }
        list
    }

    suspend fun addDownload(url: String, fileName: String?, folder: String?, startNow: Boolean): String =
        withContext(Dispatchers.IO) {
            val body = JSONObject()
                .put("url", url)
                .put("hemen_baslat", startNow)
            if (!fileName.isNullOrBlank()) body.put("dosya_adi", fileName)
            if (!folder.isNullOrBlank()) body.put("klasor", folder)
            request("POST", "/api/indirmeler", body).optString("mesaj", "Gönderildi")
        }

    suspend fun startQueue(): String = withContext(Dispatchers.IO) {
        request("POST", "/api/kuyruk/baslat").optString("mesaj", "Tamam")
    }

    suspend fun pause(id: Int): String = withContext(Dispatchers.IO) {
        request("POST", "/api/indirme/duraklat", JSONObject().put("id", id), readTimeout = 20_000)
            .optString("mesaj", "Duraklatıldı")
    }

    suspend fun resume(id: Int): String = withContext(Dispatchers.IO) {
        request("POST", "/api/indirme/devam", JSONObject().put("id", id), readTimeout = 25_000)
            .optString("mesaj", "Devam ettiriliyor")
    }

    suspend fun stopAll(): String = withContext(Dispatchers.IO) {
        request("POST", "/api/tumunu-durdur", readTimeout = 20_000).optString("mesaj", "Durduruldu")
    }

    suspend fun stopQueue(): String = withContext(Dispatchers.IO) {
        request("POST", "/api/kuyruk/durdur", readTimeout = 20_000).optString("mesaj", "Kuyruk durduruldu")
    }

    suspend fun openIdm(): String = withContext(Dispatchers.IO) {
        request("POST", "/api/idm/ac").optString("mesaj", "Tamam")
    }

    suspend fun revealDownload(id: Int): String = withContext(Dispatchers.IO) {
        request("POST", "/api/klasoru-ac", JSONObject().put("id", id)).optString("mesaj", "Tamam")
    }

    suspend fun revealFile(root: Int, path: String): String = withContext(Dispatchers.IO) {
        request("POST", "/api/klasoru-ac", JSONObject().put("kok", root).put("yol", path))
            .optString("mesaj", "Tamam")
    }

    suspend fun files(root: Int, path: String): FolderListing = withContext(Dispatchers.IO) {
        val o = request("GET", "/api/dosyalar?kok=$root&yol=${enc(path)}")
        val items = mutableListOf<FileEntry>()
        o.optJSONArray("ogeler")?.forEachObject {
            items += FileEntry(it.optString("ad"), it.optBoolean("klasor"), it.optLong("boyut"), it.optLong("tarih"))
        }
        FolderListing(o.optInt("kok", root), o.optString("yol", path), items)
    }

    suspend fun diagnostics(): String = withContext(Dispatchers.IO) {
        request("GET", "/api/tani", readTimeout = 20_000).toString(2)
    }

    /** Android'in indirme yoneticisine verilecek adresler (PIN basliktan da gonderilir). */
    fun downloadUrlForId(id: Int) = "$base/api/dosya?id=$id"
    fun downloadUrlForFile(root: Int, path: String) = "$base/api/dosya?kok=$root&yol=${enc(path)}"
    val pin: String get() = conn.pin
}

private inline fun JSONArray.forEachObject(block: (JSONObject) -> Unit) {
    for (i in 0 until length()) {
        val o = optJSONObject(i) ?: continue
        block(o)
    }
}

// ---------------------------------------------------------------------------
// Bilgisayari agda otomatik bulma
// ---------------------------------------------------------------------------

object Discovery {

    private fun ipv4Interfaces(): List<Pair<Inet4Address, Short>> {
        val result = mutableListOf<Pair<Inet4Address, Short>>()
        val ifaces = try {
            NetworkInterface.getNetworkInterfaces()?.let { Collections.list(it) } ?: emptyList()
        } catch (e: Exception) {
            emptyList()
        }
        for (ni in ifaces) {
            try {
                if (!ni.isUp || ni.isLoopback) continue
            } catch (e: Exception) {
                continue
            }
            for (ia in ni.interfaceAddresses) {
                val a = ia.address
                if (a is Inet4Address && a.isSiteLocalAddress) result += a to ia.networkPrefixLength
            }
        }
        return result
    }

    private fun broadcastTargets(): Set<InetAddress> {
        val set = linkedSetOf<InetAddress>()
        try {
            set += InetAddress.getByName("255.255.255.255")
        } catch (ignored: Exception) {
        }
        try {
            val ifaces = NetworkInterface.getNetworkInterfaces()?.let { Collections.list(it) } ?: emptyList()
            for (ni in ifaces) {
                if (!ni.isUp || ni.isLoopback) continue
                for (ia in ni.interfaceAddresses) ia.broadcast?.let { set += it }
            }
        } catch (ignored: Exception) {
        }
        return set
    }

    /** UDP yayini ile ara (hizli). */
    private fun udpScan(timeoutMs: Long): List<FoundServer> {
        val found = LinkedHashMap<String, FoundServer>()
        try {
            DatagramSocket().use { s ->
                s.broadcast = true
                s.soTimeout = 300
                val msg = DISCOVERY_MAGIC.toByteArray(Charsets.UTF_8)
                val targets = broadcastTargets()
                val end = System.currentTimeMillis() + timeoutMs
                var lastSend = 0L
                val buf = ByteArray(2048)
                while (System.currentTimeMillis() < end) {
                    val now = System.currentTimeMillis()
                    if (now - lastSend > 700) {
                        for (t in targets) {
                            try {
                                s.send(DatagramPacket(msg, msg.size, t, DISCOVERY_PORT))
                            } catch (ignored: Exception) {
                            }
                        }
                        lastSend = now
                    }
                    val p = DatagramPacket(buf, buf.size)
                    try {
                        s.receive(p)
                        val o = JSONObject(String(p.data, 0, p.length, Charsets.UTF_8))
                        if (o.optString("uygulama") == APP_ID) {
                            val host = p.address.hostAddress ?: continue
                            found[host] = FoundServer(o.optString("ad", host), host, o.optInt("port", DEFAULT_PORT))
                        }
                    } catch (ignored: SocketTimeoutException) {
                    } catch (ignored: JSONException) {
                    }
                }
            }
        } catch (ignored: Exception) {
        }
        return found.values.toList()
    }

    /** UDP engelliyse: alt agdaki tum adresleri dene (yavas ama saglam). */
    private suspend fun tcpScan(): List<FoundServer> = coroutineScope {
        val own = ipv4Interfaces().firstOrNull { it.second.toInt() in 16..30 } ?: return@coroutineScope emptyList()
        val b = own.first.address
        // /24'ten buyuk aglarda yalnizca telefonun bulundugu /24'u tara
        val prefix = "${b[0].toInt() and 255}.${b[1].toInt() and 255}.${b[2].toInt() and 255}."
        val sem = Semaphore(48)
        (1..254).map { i ->
            async(Dispatchers.IO) {
                sem.withPermit {
                    val host = prefix + i
                    if (host == own.first.hostAddress) return@withPermit null
                    try {
                        Socket().use { it.connect(InetSocketAddress(host, DEFAULT_PORT), 350) }
                        ping(host, DEFAULT_PORT)
                    } catch (ignored: Exception) {
                        null
                    }
                }
            }
        }.awaitAll().filterNotNull()
    }

    private fun ping(host: String, port: Int): FoundServer? {
        val c = URL("http://$host:$port/api/ping").openConnection() as HttpURLConnection
        return try {
            c.connectTimeout = 1_000
            c.readTimeout = 1_500
            if (c.responseCode != 200) return null
            val o = JSONObject(c.inputStream.bufferedReader().use { it.readText() })
            if (o.optString("uygulama") == APP_ID) FoundServer(o.optString("ad", host), host, port) else null
        } catch (ignored: Exception) {
            null
        } finally {
            c.disconnect()
        }
    }

    suspend fun discover(): List<FoundServer> = withContext(Dispatchers.IO) {
        val udp = udpScan(2_000)
        if (udp.isNotEmpty()) udp else tcpScan()
    }
}
