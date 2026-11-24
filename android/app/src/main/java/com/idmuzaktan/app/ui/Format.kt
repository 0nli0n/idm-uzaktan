package com.idmuzaktan.app.ui

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val TR: Locale = Locale.forLanguageTag("tr-TR")

fun formatBytes(bytes: Long): String {
    if (bytes < 1024) return "$bytes B"
    val units = arrayOf("KB", "MB", "GB", "TB")
    var v = bytes / 1024.0
    var i = 0
    while (v >= 1024 && i < units.size - 1) {
        v /= 1024
        i++
    }
    return if (v >= 100) String.format(TR, "%.0f %s", v, units[i])
    else String.format(TR, "%.1f %s", v, units[i])
}

fun formatSpeed(bytesPerSec: Long): String = formatBytes(bytesPerSec) + "/sn"

fun formatDate(epochSec: Long): String =
    SimpleDateFormat("d MMM yyyy HH:mm", TR).format(Date(epochSec * 1000))

fun formatEta(remaining: Long, speed: Long): String? {
    if (speed <= 0 || remaining <= 0) return null
    val s = remaining / speed
    return when {
        s < 60 -> "${s} sn kaldı"
        s < 3600 -> "${s / 60} dk kaldı"
        else -> "${s / 3600} sa ${(s % 3600) / 60} dk kaldı"
    }
}
