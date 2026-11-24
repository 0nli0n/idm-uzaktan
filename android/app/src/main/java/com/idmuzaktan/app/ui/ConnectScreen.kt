@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.idmuzaktan.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.idmuzaktan.app.AppViewModel
import com.idmuzaktan.app.DEFAULT_PORT

@Composable
fun ConnectScreen(vm: AppViewModel) {
    var host by rememberSaveable { mutableStateOf(vm.lastHost) }
    var port by rememberSaveable { mutableStateOf(vm.lastPort.toString()) }
    var pin by rememberSaveable { mutableStateOf("") }
    var name by rememberSaveable { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) { vm.discover() }
    LaunchedEffect(vm.found) {
        val only = vm.found.singleOrNull()
        if (only != null && (host.isBlank() || host == only.host)) {
            host = only.host
            port = only.port.toString()
            name = only.name
        }
    }

    Scaffold { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .imePadding()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Spacer(Modifier.height(8.dp))
            Icon(
                Icons.Filled.Computer,
                contentDescription = null,
                modifier = Modifier.size(52.dp),
                tint = MaterialTheme.colorScheme.primary,
            )
            Text("Bilgisayara bağlan", style = MaterialTheme.typography.headlineSmall)
            Text(
                "Bilgisayarda “baslat.bat” dosyasını çalıştırın. Telefon ve bilgisayar aynı Wi-Fi ağında olmalı.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            if (vm.pendingUrl != null) {
                Banner(
                    icon = Icons.Filled.Link,
                    text = "Bağlandıktan sonra paylaştığınız link eklenecek.",
                    container = MaterialTheme.colorScheme.secondaryContainer,
                    content = MaterialTheme.colorScheme.onSecondaryContainer,
                )
            }

            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(vertical = 8.dp)) {
                    Row(
                        Modifier.padding(start = 16.dp, end = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Filled.Wifi, null, Modifier.size(20.dp), tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(8.dp))
                        Text("Ağdaki bilgisayarlar", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                        if (vm.scanning) {
                            CircularProgressIndicator(Modifier.padding(12.dp).size(20.dp), strokeWidth = 2.dp)
                        } else {
                            TextButton(onClick = { vm.discover() }) { Text("Tekrar ara") }
                        }
                    }
                    if (vm.scanning && vm.found.isEmpty()) {
                        Text(
                            "Aranıyor…",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                        )
                    } else if (vm.found.isEmpty()) {
                        Text(
                            "Bulunamadı. Sunucunun açık olduğundan emin olun ya da IP adresini aşağıya elle girin.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                        )
                    }
                    vm.found.forEach { f ->
                        ListItem(
                            headlineContent = { Text(f.name) },
                            supportingContent = { Text("${f.host}:${f.port}") },
                            leadingContent = { Icon(Icons.Filled.Computer, null) },
                            trailingContent = {
                                if (host == f.host) {
                                    Icon(Icons.Filled.CheckCircle, "Seçili", tint = MaterialTheme.colorScheme.primary)
                                }
                            },
                            colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                            modifier = Modifier.clickable {
                                host = f.host
                                port = f.port.toString()
                                name = f.name
                            },
                        )
                    }
                }
            }

            OutlinedTextField(
                value = host,
                onValueChange = {
                    host = it.trim()
                    name = null
                },
                label = { Text("Bilgisayarın IP adresi") },
                placeholder = { Text("ör. 192.168.1.20") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = port,
                onValueChange = { v -> port = v.filter { it.isDigit() }.take(5) },
                label = { Text("Port") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = pin,
                onValueChange = { v -> pin = v.filter { it.isDigit() }.take(6) },
                label = { Text("PIN") },
                supportingText = { Text("Bilgisayardaki sunucu penceresinde yazan 6 haneli kod") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                modifier = Modifier.fillMaxWidth(),
            )

            vm.connectError?.let {
                Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
            }

            Button(
                onClick = { vm.connect(host, port.toIntOrNull() ?: DEFAULT_PORT, pin, name) },
                enabled = !vm.connecting,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
            ) {
                if (vm.connecting) {
                    CircularProgressIndicator(
                        Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                } else {
                    Text("Bağlan")
                }
            }

            Text(
                "Bilgisayar bulunamıyorsa: sunucu klasöründeki “guvenlik_duvari_izni.bat” dosyasını çalıştırın ve Wi-Fi ağınızın Windows'ta “Özel ağ” olarak ayarlı olduğundan emin olun.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
