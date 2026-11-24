@file:OptIn(ExperimentalMaterial3Api::class)

package com.idmuzaktan.app.ui

import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.LinkOff
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Replay
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.idmuzaktan.app.AppViewModel
import com.idmuzaktan.app.Connection
import com.idmuzaktan.app.DlStatus
import com.idmuzaktan.app.DownloadItem
import com.idmuzaktan.app.FileEntry
import kotlinx.coroutines.delay

@Composable
fun AppRoot(vm: AppViewModel) {
    val conn = vm.connection
    if (conn == null) ConnectScreen(vm) else MainScreen(vm, conn)
}

// ---------------------------------------------------------------------------
// Ana ekran
// ---------------------------------------------------------------------------

@Composable
fun MainScreen(vm: AppViewModel, conn: Connection) {
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var showAdd by remember { mutableStateOf(false) }
    var menuOpen by remember { mutableStateOf(false) }
    val snackbar = remember { SnackbarHostState() }
    val clipboard = LocalClipboardManager.current

    LaunchedEffect(Unit) {
        vm.messages.collect { snackbar.showSnackbar(it) }
    }

    // Uygulama ekrandayken listeyi duzenli yenile
    val lifecycleOwner = LocalLifecycleOwner.current
    LaunchedEffect(conn, lifecycleOwner) {
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
            vm.refreshInfo()
            while (true) {
                vm.loadDownloads(silent = true)
                val active = vm.downloads.any { it.status == DlStatus.DOWNLOADING }
                delay(if (active) 2_000L else 5_000L)
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("IDM Uzaktan", maxLines = 1)
                        Text(
                            vm.info?.name ?: conn.name,
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                        )
                    }
                },
                actions = {
                    IconButton(onClick = { vm.startQueue() }) {
                        Icon(Icons.Filled.PlayArrow, contentDescription = "Kuyruğu başlat")
                    }
                    Box {
                        IconButton(onClick = { menuOpen = true }) {
                            Icon(Icons.Filled.MoreVert, contentDescription = "Menü")
                        }
                        DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                            MenuItem("Kuyruğu başlat", Icons.Filled.PlayArrow) {
                                menuOpen = false; vm.startQueue()
                            }
                            MenuItem("IDM'i bilgisayarda aç", Icons.AutoMirrored.Filled.OpenInNew) {
                                menuOpen = false; vm.openIdm()
                            }
                            MenuItem("Yenile", Icons.Filled.Refresh) {
                                menuOpen = false; vm.refreshDownloads(); vm.refreshInfo()
                            }
                            MenuItem("Tanılama bilgisi", Icons.Filled.BugReport) {
                                menuOpen = false; vm.loadDiagnostics()
                            }
                            HorizontalDivider()
                            MenuItem("Bağlantıyı kes", Icons.Filled.LinkOff) {
                                menuOpen = false; vm.disconnect()
                            }
                        }
                    }
                },
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { showAdd = true },
                icon = { Icon(Icons.Filled.Add, contentDescription = null) },
                text = { Text("Yeni indirme") },
            )
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        Column(
            Modifier
                .padding(padding)
                .fillMaxSize()
        ) {
            TabRow(selectedTabIndex = tab) {
                Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("İndirmeler") })
                Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("Dosyalar") })
            }
            val info = vm.info
            if (info != null && !info.idmFound) {
                Banner(
                    Icons.Filled.Warning,
                    "Bilgisayarda IDM bulunamadı. Sunucu klasöründeki config.json dosyasında “idm_yolu” ayarını doldurun.",
                    MaterialTheme.colorScheme.errorContainer,
                    MaterialTheme.colorScheme.onErrorContainer,
                )
            } else if (info != null && !info.idmRunning) {
                Banner(
                    Icons.Filled.Info,
                    "IDM şu an bilgisayarda kapalı.",
                    MaterialTheme.colorScheme.surfaceVariant,
                    MaterialTheme.colorScheme.onSurfaceVariant,
                    actionLabel = "Aç",
                    onAction = { vm.openIdm() },
                )
            }
            when (tab) {
                0 -> DownloadsTab(vm)
                else -> FilesTab(vm)
            }
        }
    }

    // Yeni indirme penceresi (elle ya da "Paylas" menusunden)
    val pending = vm.pendingUrl
    if (showAdd || pending != null) {
        AddDownloadDialog(
            initialUrl = pending ?: "",
            folders = vm.info?.folders.orEmpty(),
            onDismiss = {
                showAdd = false
                vm.pendingUrl = null
            },
            onSubmit = { url, name, folder, now ->
                vm.addDownload(url, name, folder, now)
                showAdd = false
                vm.pendingUrl = null
            },
        )
    }

    vm.diagnostics?.let { text ->
        AlertDialog(
            onDismissRequest = { vm.diagnostics = null },
            title = { Text("Tanılama bilgisi") },
            text = {
                Column(
                    Modifier
                        .heightIn(max = 420.dp)
                        .verticalScroll(rememberScrollState())
                ) {
                    Text(
                        "Liste veya ilerleme yanlış görünüyorsa bu metni kopyalayıp geliştiriciye gönderin. Çerez/parola gibi bilgiler gizlenir.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Spacer(Modifier.height(8.dp))
                    SelectionContainer {
                        Text(text, fontFamily = FontFamily.Monospace, fontSize = 11.sp, lineHeight = 14.sp)
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { clipboard.setText(AnnotatedString(text)) }) { Text("Kopyala") }
            },
            dismissButton = {
                TextButton(onClick = { vm.diagnostics = null }) { Text("Kapat") }
            },
        )
    }
}

@Composable
private fun MenuItem(text: String, icon: ImageVector, onClick: () -> Unit) {
    DropdownMenuItem(
        text = { Text(text) },
        leadingIcon = { Icon(icon, contentDescription = null) },
        onClick = onClick,
    )
}

// ---------------------------------------------------------------------------
// Indirmeler sekmesi
// ---------------------------------------------------------------------------

private fun subtitle(d: DownloadItem): String {
    val size = d.size
    return when (d.status) {
        DlStatus.DONE -> listOfNotNull(size?.let { formatBytes(it) }, "Tamamlandı").joinToString(" · ")
        DlStatus.DOWNLOADING, DlStatus.PARTIAL -> buildList {
            d.progress?.let { add("%" + (it * 100).toInt()) }
            add(if (size != null) "${formatBytes(d.downloaded)} / ${formatBytes(size)}" else formatBytes(d.downloaded))
            if (d.status == DlStatus.DOWNLOADING && d.speed > 0) add(formatSpeed(d.speed))
            if (d.status == DlStatus.DOWNLOADING && size != null) formatEta(size - d.downloaded, d.speed)?.let { add(it) }
        }.joinToString(" · ")
        DlStatus.NOT_STARTED -> if (size != null) "${formatBytes(size)} · İndirilmedi" else "İndirilmedi"
    }
}

@Composable
fun DownloadsTab(vm: AppViewModel) {
    var filter by rememberSaveable { mutableIntStateOf(0) }
    var selectedId by remember { mutableStateOf<Int?>(null) }

    val all = vm.downloads
    val active = all.filter { it.status == DlStatus.DOWNLOADING || it.status == DlStatus.PARTIAL }
    val done = all.filter { it.status == DlStatus.DONE }
    val shown = when (filter) {
        1 -> active
        2 -> done
        else -> all
    }

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = 12.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            FilterChip(selected = filter == 0, onClick = { filter = 0 }, label = { Text("Tümü (${all.size})") })
            FilterChip(selected = filter == 1, onClick = { filter = 1 }, label = { Text("Devam eden (${active.size})") })
            FilterChip(selected = filter == 2, onClick = { filter = 2 }, label = { Text("Tamamlanan (${done.size})") })
        }

        PullToRefreshBox(
            isRefreshing = vm.refreshing,
            onRefresh = { vm.refreshDownloads() },
            modifier = Modifier.fillMaxSize(),
        ) {
            val err = vm.downloadsError
            when {
                !vm.downloadsLoaded && err == null ->
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }

                err != null && all.isEmpty() ->
                    EmptyState(Icons.Filled.CloudOff, "Bağlantı sorunu", err, "Tekrar dene") { vm.refreshDownloads() }

                shown.isEmpty() ->
                    EmptyState(
                        Icons.Filled.Download,
                        if (filter == 0) "IDM listesi boş" else "Bu filtrede indirme yok",
                        if (filter == 0) "Sağ alttaki “Yeni indirme” ile ya da başka bir uygulamadan “Paylaş” ile link gönderin." else null,
                    )

                else -> LazyColumn(
                    contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 4.dp, bottom = 96.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    if (err != null) {
                        item {
                            Banner(
                                Icons.Filled.CloudOff, err,
                                MaterialTheme.colorScheme.errorContainer,
                                MaterialTheme.colorScheme.onErrorContainer,
                            )
                        }
                    }
                    items(shown, key = { it.id }) { d ->
                        DownloadCard(d) { selectedId = d.id }
                    }
                }
            }
        }
    }

    val selected = selectedId?.let { id -> all.firstOrNull { it.id == id } }
    if (selected != null) {
        DownloadSheet(selected, vm) { selectedId = null }
    }
}

@Composable
private fun DownloadCard(d: DownloadItem, onClick: () -> Unit) {
    ElevatedCard(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                FileTypeIcon(d.fileName)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        d.fileName,
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(Modifier.height(2.dp))
                    Text(
                        subtitle(d),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Spacer(Modifier.width(8.dp))
                StatusPill(d.status)
            }
            if (d.status == DlStatus.DOWNLOADING || d.status == DlStatus.PARTIAL) {
                Spacer(Modifier.height(10.dp))
                val p = d.progress
                val barModifier = Modifier
                    .fillMaxWidth()
                    .height(6.dp)
                    .clip(RoundedCornerShape(3.dp))
                if (p != null) {
                    LinearProgressIndicator(progress = { p }, modifier = barModifier)
                } else if (d.status == DlStatus.DOWNLOADING) {
                    LinearProgressIndicator(modifier = barModifier)
                }
            }
        }
    }
}

@Composable
private fun SheetAction(icon: ImageVector, text: String, onClick: () -> Unit) {
    ListItem(
        headlineContent = { Text(text) },
        leadingContent = { Icon(icon, contentDescription = null) },
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        modifier = Modifier.clickable(onClick = onClick),
    )
}

private fun parentDir(windowsPath: String): String? {
    val i = windowsPath.lastIndexOfAny(charArrayOf('\\', '/'))
    return if (i > 0) windowsPath.substring(0, i) else null
}

@Composable
private fun DownloadSheet(d: DownloadItem, vm: AppViewModel, onDismiss: () -> Unit) {
    val clipboard = LocalClipboardManager.current
    val context = LocalContext.current
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.padding(horizontal = 20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                FileTypeIcon(d.fileName)
                Spacer(Modifier.width(12.dp))
                Text(d.fileName, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            }
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                StatusPill(d.status)
                Spacer(Modifier.width(8.dp))
                Text(subtitle(d), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            d.progress?.let { p ->
                if (d.status != DlStatus.DONE && d.status != DlStatus.NOT_STARTED) {
                    Spacer(Modifier.height(10.dp))
                    LinearProgressIndicator(progress = { p }, modifier = Modifier.fillMaxWidth())
                }
            }
            if (d.path.isNotBlank()) {
                Spacer(Modifier.height(10.dp))
                Text("Bilgisayardaki yeri", style = MaterialTheme.typography.labelMedium)
                Text(d.path, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (d.url.isNotBlank()) {
                Spacer(Modifier.height(8.dp))
                Text("Bağlantı", style = MaterialTheme.typography.labelMedium)
                Text(
                    d.url,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        HorizontalDivider()
        if (d.status == DlStatus.DONE) {
            SheetAction(Icons.Filled.PhoneAndroid, "Telefona indir") {
                vm.downloadToPhone(d); onDismiss()
            }
            SheetAction(Icons.Filled.FolderOpen, "Bilgisayarda klasörünü aç") {
                vm.reveal(d); onDismiss()
            }
        } else {
            SheetAction(Icons.Filled.PlayArrow, "Kuyruğu başlat") {
                vm.startQueue(); onDismiss()
            }
        }
        if (d.url.isNotBlank()) {
            SheetAction(Icons.Filled.Replay, "Yeniden indir (yeni kopya)") {
                vm.addDownload(d.url, null, parentDir(d.path), true); onDismiss()
            }
            SheetAction(Icons.Filled.ContentCopy, "Bağlantıyı kopyala") {
                clipboard.setText(AnnotatedString(d.url)); onDismiss()
            }
            SheetAction(Icons.Filled.Share, "Bağlantıyı paylaş") {
                val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, d.url)
                context.startActivity(Intent.createChooser(send, null))
                onDismiss()
            }
        }
        Spacer(Modifier.height(16.dp))
    }
}

// ---------------------------------------------------------------------------
// Dosyalar sekmesi
// ---------------------------------------------------------------------------

private fun joinPath(base: String, name: String) = if (base.isEmpty()) name else "$base/$name"

@Composable
fun FilesTab(vm: AppViewModel) {
    val info = vm.info
    val listing = vm.listing
    var selected by remember { mutableStateOf<FileEntry?>(null) }

    LaunchedEffect(info?.roots) {
        if (vm.listing == null && info != null && info.roots.isNotEmpty()) vm.openFolder(info.roots.first().no, "")
    }
    BackHandler(enabled = listing != null && listing.path.isNotEmpty()) { vm.folderUp() }

    Column(Modifier.fillMaxSize()) {
        if (info == null) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            return@Column
        }
        if (info.roots.isEmpty()) {
            EmptyState(
                Icons.Filled.Folder,
                "Gösterilecek klasör yok",
                "Sunucu klasöründeki config.json dosyasında “indirme_klasorleri” ayarını kontrol edin.",
            )
            return@Column
        }
        if (info.roots.size > 1) {
            Row(
                Modifier
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 12.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                info.roots.forEach { r ->
                    FilterChip(
                        selected = listing?.root == r.no,
                        onClick = { vm.openFolder(r.no, "") },
                        label = { Text(r.name) },
                    )
                }
            }
        }

        Row(Modifier.padding(horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { vm.folderUp() }, enabled = listing?.path?.isNotEmpty() == true) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Üst klasör")
            }
            val rootName = info.roots.firstOrNull { it.no == listing?.root }?.name ?: ""
            val crumbs = listOf(rootName) + (listing?.path?.split('/')?.filter { it.isNotEmpty() } ?: emptyList())
            Text(
                crumbs.joinToString(" › "),
                style = MaterialTheme.typography.titleSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            if (vm.filesLoading) {
                CircularProgressIndicator(Modifier.padding(12.dp).size(20.dp), strokeWidth = 2.dp)
            } else {
                IconButton(onClick = { listing?.let { vm.openFolder(it.root, it.path) } }) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Yenile")
                }
            }
        }
        HorizontalDivider()

        vm.filesError?.let {
            Banner(Icons.Filled.CloudOff, it, MaterialTheme.colorScheme.errorContainer, MaterialTheme.colorScheme.onErrorContainer)
        }

        if (listing == null) return@Column
        if (listing.items.isEmpty() && !vm.filesLoading) {
            EmptyState(Icons.Filled.FolderOpen, "Bu klasör boş")
            return@Column
        }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 96.dp)) {
            items(listing.items, key = { (if (it.isDir) "d:" else "f:") + it.name }) { e ->
                ListItem(
                    headlineContent = { Text(e.name, maxLines = 2, overflow = TextOverflow.Ellipsis) },
                    supportingContent = {
                        Text(if (e.isDir) formatDate(e.date) else "${formatBytes(e.size)} · ${formatDate(e.date)}")
                    },
                    leadingContent = {
                        if (e.isDir) {
                            Icon(
                                Icons.Filled.Folder,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(40.dp).padding(4.dp),
                            )
                        } else {
                            FileTypeIcon(e.name)
                        }
                    },
                    modifier = Modifier.clickable {
                        if (e.isDir) vm.openFolder(listing.root, joinPath(listing.path, e.name)) else selected = e
                    },
                )
            }
        }
    }

    val sel = selected
    if (sel != null && listing != null) {
        val path = joinPath(listing.path, sel.name)
        ModalBottomSheet(onDismissRequest = { selected = null }) {
            Row(Modifier.padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                FileTypeIcon(sel.name)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(sel.name, style = MaterialTheme.typography.titleMedium)
                    Text(
                        "${formatBytes(sel.size)} · ${formatDate(sel.date)}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Spacer(Modifier.height(8.dp))
            HorizontalDivider()
            SheetAction(Icons.Filled.PhoneAndroid, "Telefona indir") {
                vm.downloadToPhone(listing.root, path, sel.name); selected = null
            }
            SheetAction(Icons.Filled.FolderOpen, "Bilgisayarda klasörde göster") {
                vm.reveal(listing.root, path); selected = null
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

// ---------------------------------------------------------------------------
// Yeni indirme penceresi
// ---------------------------------------------------------------------------

private fun isValidUrl(s: String): Boolean {
    val t = s.trim()
    return (t.startsWith("http://", true) || t.startsWith("https://", true) || t.startsWith("ftp://", true)) &&
        t.length > 8 && t.none { it.isWhitespace() }
}

@Composable
fun AddDownloadDialog(
    initialUrl: String,
    folders: List<String>,
    onDismiss: () -> Unit,
    onSubmit: (url: String, fileName: String?, folder: String?, startNow: Boolean) -> Unit,
) {
    var url by remember(initialUrl) { mutableStateOf(initialUrl) }
    var name by remember { mutableStateOf("") }
    var folder by remember { mutableStateOf<String?>(null) }
    var folderMenu by remember { mutableStateOf(false) }
    val clipboard = LocalClipboardManager.current
    val valid = isValidUrl(url)

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Yeni indirme") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it },
                    label = { Text("İndirme bağlantısı") },
                    placeholder = { Text("https://…") },
                    maxLines = 4,
                    isError = url.isNotBlank() && !valid,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    trailingIcon = {
                        IconButton(onClick = {
                            clipboard.getText()?.text?.trim()?.let { if (it.isNotEmpty()) url = it }
                        }) {
                            Icon(Icons.Filled.ContentPaste, contentDescription = "Yapıştır")
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Dosya adı (isteğe bağlı)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Box {
                    OutlinedButton(onClick = { folderMenu = true }, modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.Filled.Folder, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(8.dp))
                        Text(
                            folder ?: "Kayıt yeri: IDM varsayılanı",
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f),
                        )
                    }
                    DropdownMenu(expanded = folderMenu, onDismissRequest = { folderMenu = false }) {
                        DropdownMenuItem(
                            text = { Text("IDM varsayılanı (dosya türüne göre)") },
                            onClick = { folder = null; folderMenu = false },
                        )
                        folders.forEach { f ->
                            DropdownMenuItem(
                                text = { Text(f, maxLines = 2, overflow = TextOverflow.Ellipsis) },
                                onClick = { folder = f; folderMenu = false },
                            )
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                enabled = valid,
                onClick = { onSubmit(url.trim(), name.trim().ifBlank { null }, folder, true) },
            ) { Text("Hemen indir") }
        },
        dismissButton = {
            Row {
                TextButton(onClick = onDismiss) { Text("İptal") }
                TextButton(
                    enabled = valid,
                    onClick = { onSubmit(url.trim(), name.trim().ifBlank { null }, folder, false) },
                ) { Text("Kuyruğa ekle") }
            }
        },
    )
}
