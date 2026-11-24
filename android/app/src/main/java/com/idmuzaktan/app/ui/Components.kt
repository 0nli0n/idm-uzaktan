package com.idmuzaktan.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.filled.Android
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material.icons.filled.Archive
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.idmuzaktan.app.DlStatus

fun iconForFile(name: String): ImageVector {
    return when (name.substringAfterLast('.', "").lowercase()) {
        "mp4", "mkv", "avi", "mov", "wmv", "webm", "flv", "m4v", "ts" -> Icons.Filled.Movie
        "mp3", "flac", "wav", "m4a", "aac", "ogg", "opus", "wma" -> Icons.Filled.MusicNote
        "jpg", "jpeg", "png", "gif", "webp", "bmp", "heic", "svg" -> Icons.Filled.Image
        "zip", "rar", "7z", "tar", "gz", "xz", "bz2", "iso" -> Icons.Filled.Archive
        "apk", "xapk", "apks" -> Icons.Filled.Android
        "exe", "msi", "bat", "cmd", "appx", "msix" -> Icons.Filled.Apps
        "pdf" -> Icons.Filled.PictureAsPdf
        "doc", "docx", "txt", "xls", "xlsx", "ppt", "pptx", "epub", "odt", "rtf" -> Icons.Filled.Description
        else -> Icons.AutoMirrored.Filled.InsertDriveFile
    }
}

@Composable
fun FileTypeIcon(name: String, modifier: Modifier = Modifier) {
    Box(
        modifier
            .size(40.dp)
            .background(MaterialTheme.colorScheme.primaryContainer, CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            iconForFile(name),
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onPrimaryContainer,
            modifier = Modifier.size(22.dp),
        )
    }
}

@Composable
fun StatusPill(status: DlStatus) {
    val cs = MaterialTheme.colorScheme
    val (label, bg, fg) = when (status) {
        DlStatus.DONE -> Triple("Tamamlandı", cs.secondaryContainer, cs.onSecondaryContainer)
        DlStatus.DOWNLOADING -> Triple("İndiriliyor", cs.primaryContainer, cs.onPrimaryContainer)
        DlStatus.PARTIAL -> Triple("Yarım", cs.tertiaryContainer, cs.onTertiaryContainer)
        DlStatus.NOT_STARTED -> Triple("Başlamadı", cs.surfaceVariant, cs.onSurfaceVariant)
    }
    Surface(color = bg, contentColor = fg, shape = RoundedCornerShape(50)) {
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
        )
    }
}

/** Kaydirilabilir bos durum (asagi cekip yenileme calissin diye). */
@Composable
fun EmptyState(icon: ImageVector, title: String, message: String? = null, actionLabel: String? = null, onAction: (() -> Unit)? = null) {
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Spacer(Modifier.size(48.dp))
        Icon(icon, null, Modifier.size(48.dp), tint = MaterialTheme.colorScheme.outline)
        Spacer(Modifier.size(12.dp))
        Text(title, style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
        if (message != null) {
            Spacer(Modifier.size(6.dp))
            Text(
                message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }
        if (actionLabel != null && onAction != null) {
            Spacer(Modifier.size(8.dp))
            TextButton(onClick = onAction) { Text(actionLabel) }
        }
    }
}

@Composable
fun Banner(
    icon: ImageVector,
    text: String,
    container: Color,
    content: Color,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    Surface(
        color = container,
        contentColor = content,
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Row(Modifier.padding(start = 12.dp, end = 4.dp, top = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, null, Modifier.size(20.dp))
            Spacer(Modifier.width(10.dp))
            Text(text, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
            if (actionLabel != null && onAction != null) {
                TextButton(onClick = onAction) { Text(actionLabel, color = content) }
            }
        }
    }
}
