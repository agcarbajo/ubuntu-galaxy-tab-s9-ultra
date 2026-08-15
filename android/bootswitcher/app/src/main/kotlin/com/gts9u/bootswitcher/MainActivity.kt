package com.gts9u.bootswitcher

import android.app.StatusBarManager
import android.content.ComponentName
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Android
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { BootSwitcherTheme { SwitcherScreen() } }
    }
}

/**
 * The theme.
 *
 * This wants to be `MaterialExpressiveTheme` with an expressive `MotionScheme`,
 * and cannot be yet: in material3 1.4.0 both are `internal`, and every 1.5.0
 * alpha that makes them public requires AGP 9.1 and compileSdk 37.  Until that
 * toolchain move is made, the expressive feel is carried by what stable does
 * expose — dynamic colour, generous corner radii, tonal containers and large
 * touch targets — and the swap is a one-function change here.
 */
@Composable
fun BootSwitcherTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val context = LocalContext.current
    val scheme = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        dark -> darkColorScheme()
        else -> lightColorScheme()
    }
    MaterialTheme(colorScheme = scheme, content = content)
}

private fun iconFor(set: BootSets.BootSet): ImageVector =
    if (set.id.lowercase().contains("ubuntu")) Icons.Filled.Computer else Icons.Filled.Android

private fun formatSize(bytes: Long): String {
    val gb = bytes / 1_000_000_000.0
    return if (gb >= 100) "%.0f GB".format(gb) else "%.1f GB".format(gb)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SwitcherScreen(vm: SwitcherViewModel = viewModel()) {
    val state by vm.state.collectAsStateWithLifecycle()
    var showAbout by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Arranque dual") },
                actions = {
                    IconButton(onClick = { showAbout = true }) {
                        Icon(Icons.Filled.Info, contentDescription = "Acerca de")
                    }
                },
            )
        },
    ) { inner ->
        Surface(
            Modifier
                .fillMaxSize()
                .padding(inner)
        ) {
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 20.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                HeroCard(state)

                if (state.busy || state.log.isNotEmpty()) ProgressCard(state)

                if (state.hasRoot && state.sets.isNotEmpty()) {
                    SectionTitle("Sistemas")
                    SystemsCard(state, onSwitch = { vm.switchTo(it) })
                }

                if (state.storage.isNotEmpty()) {
                    SectionTitle("Almacenamiento")
                    StorageCard(state)
                }

                AnimatedVisibility(state.readyToReboot != null) {
                    Button(
                        onClick = { vm.reboot() },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(60.dp),
                        shape = RoundedCornerShape(20.dp),
                    ) {
                        Icon(Icons.Filled.RestartAlt, contentDescription = null)
                        Spacer(Modifier.width(12.dp))
                        Text("Reiniciar ahora", style = MaterialTheme.typography.titleMedium)
                    }
                }

                SectionTitle("Ajustes")
                SettingsCard(enabled = !state.busy, onRefresh = { vm.refresh() })

                Text(
                    "Las imágenes se leen de ${BootSets.ROOT_DIR}. Sólo se tocan boot, " +
                        "init_boot, vendor_boot y dtbo; vbmeta no se toca nunca, porque " +
                        "cambiarlo borraría los datos de Android.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
            }
        }
    }

    if (showAbout) AboutDialog(onDismiss = { showAbout = false })
}

@Composable
private fun SectionTitle(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(start = 4.dp),
    )
}

@Composable
private fun HeroCard(state: UiState) {
    val current = state.current
    val (title, body, icon) = when {
        state.loading -> Triple("Comprobando…", "Leyendo las particiones de arranque.", Icons.Filled.Refresh)
        !state.hasRoot -> Triple("Sin root", state.error ?: "Esta app necesita root.", Icons.Filled.Warning)
        current == null -> Triple(
            "Sistema desconocido",
            "Las particiones no coinciden con ningún juego guardado.",
            Icons.Filled.Warning,
        )
        else -> Triple("Ahora arranca", current.label, iconFor(current))
    }

    val good = state.hasRoot && current != null
    Card(
        Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(28.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (good) MaterialTheme.colorScheme.primaryContainer
            else MaterialTheme.colorScheme.errorContainer,
        ),
    ) {
        Row(Modifier.padding(24.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier
                    .size(56.dp)
                    .clip(CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = null, Modifier.size(36.dp))
            }
            Spacer(Modifier.width(20.dp))
            Column {
                Text(
                    title,
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    body,
                    style = if (good) MaterialTheme.typography.headlineSmall
                    else MaterialTheme.typography.bodyMedium,
                    fontWeight = if (good) FontWeight.Bold else FontWeight.Normal,
                )
            }
        }
    }
}

@Composable
private fun SystemsCard(state: UiState, onSwitch: (BootSets.BootSet) -> Unit) {
    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(24.dp)) {
        // The running system first: it answers "where am I", and the rest of
        // the list is then plainly "where else can I go".
        val ordered = state.sets.sortedBy { it.id != state.current?.id }
        ordered.forEachIndexed { index, set ->
            val isCurrent = set.id == state.current?.id
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(iconFor(set), contentDescription = null)
                Spacer(Modifier.width(16.dp))
                Column(Modifier.weight(1f)) {
                    Text(set.label, style = MaterialTheme.typography.titleMedium)
                    Text(
                        when {
                            isCurrent -> "En uso ahora"
                            set.complete -> "Listo para arrancar"
                            else -> "Le faltan imágenes o tienen un tamaño raro"
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.width(12.dp))
                if (isCurrent) {
                    Icon(
                        Icons.Filled.Check,
                        contentDescription = "en uso",
                        tint = MaterialTheme.colorScheme.primary,
                    )
                } else if (set.complete) {
                    FilledTonalButton(
                        onClick = { onSwitch(set) },
                        enabled = !state.busy,
                        shape = RoundedCornerShape(16.dp),
                    ) { Text("Cambiar") }
                }
            }
            if (index != ordered.lastIndex) {
                HorizontalDivider(Modifier.padding(horizontal = 20.dp))
            }
        }
    }
}

@Composable
private fun StorageCard(state: UiState) {
    val android = state.storage["android"]
    val linux = state.storage["linux"]
    val total = (android?.total ?: 0L) + (linux?.total ?: 0L)
    if (total <= 0L) return

    val androidUsed = MaterialTheme.colorScheme.primary
    val androidFree = MaterialTheme.colorScheme.primary.copy(alpha = 0.28f)
    val linuxColor = MaterialTheme.colorScheme.tertiary.copy(alpha = 0.65f)

    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(24.dp)) {
        Column(Modifier.padding(20.dp)) {
            // One bar for the whole disk, split by system, so the trade-off
            // between the two is visible at a glance.
            // Clipping the canvas itself rounds the ends, so the segments can
            // be plain rectangles butted against each other.
            Canvas(
                Modifier
                    .fillMaxWidth()
                    .height(18.dp)
                    .clip(RoundedCornerShape(9.dp))
            ) {
                var x = 0f
                val segments = buildList {
                    android?.let {
                        if (it.known) {
                            add((it.used.toFloat() / total) to androidUsed)
                            add(((it.total - it.used).toFloat() / total) to androidFree)
                        } else add((it.total.toFloat() / total) to androidFree)
                    }
                    linux?.let { add((it.total.toFloat() / total) to linuxColor) }
                }
                drawRect(Color.Gray.copy(alpha = 0.20f), size = size)
                segments.forEach { (fraction, colour) ->
                    val span = size.width * fraction
                    drawRect(colour, topLeft = Offset(x, 0f), size = Size(span, size.height))
                    x += span
                }
            }

            Spacer(Modifier.height(14.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                android?.let {
                    LegendItem(androidUsed, "Android", "${formatSize(it.used)} de ${formatSize(it.total)}")
                }
                linux?.let { LegendItem(linuxColor, "Linux", formatSize(it.total)) }
            }
            Spacer(Modifier.height(10.dp))
            Text(
                "El uso de Linux no se puede leer desde Android: su partición usa ext4.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun LegendItem(colour: Color, title: String, detail: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier
                .size(12.dp)
                .clip(CircleShape)
        ) {
            Canvas(Modifier.fillMaxSize()) { drawRect(colour, size = size) }
        }
        Spacer(Modifier.width(8.dp))
        Column {
            Text(title, style = MaterialTheme.typography.labelLarge)
            Text(
                detail,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun SettingsCard(enabled: Boolean, onRefresh: () -> Unit) {
    val context = LocalContext.current
    val prefs = remember { Prefs(context) }
    var skip by remember { mutableStateOf(prefs.skipConfirmation) }

    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(24.dp)) {
        Column {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("Reiniciar sin preguntar", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "El botón de los ajustes rápidos cambia de sistema en cuanto lo tocas.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.width(12.dp))
                Switch(
                    checked = skip,
                    onCheckedChange = {
                        skip = it
                        prefs.skipConfirmation = it
                    },
                )
            }

            HorizontalDivider(Modifier.padding(horizontal = 20.dp))
            AddTileRow()
            HorizontalDivider(Modifier.padding(horizontal = 20.dp))

            TextButton(
                onClick = onRefresh,
                enabled = enabled,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(56.dp),
                shape = RoundedCornerShape(0.dp),
            ) {
                Icon(Icons.Filled.Refresh, contentDescription = null)
                Spacer(Modifier.width(12.dp))
                Text("Volver a comprobar")
            }
        }
    }
}

/**
 * Asks the system to offer the quick settings tile.
 *
 * One UI keeps its own quick settings layout, so writing AOSP's
 * `sysui_qs_tiles` does nothing: SystemUI puts it straight back. This is the
 * supported route — the system shows its own prompt and the owner accepts it.
 */
@Composable
private fun AddTileRow() {
    val context = LocalContext.current

    TextButton(
        onClick = {
            val manager = context.getSystemService(StatusBarManager::class.java) ?: return@TextButton
            manager.requestAddTileService(
                ComponentName(context, BootSwitchTile::class.java),
                context.getString(R.string.tile_label),
                android.graphics.drawable.Icon.createWithResource(context, R.drawable.ic_tile_dualboot),
                context.mainExecutor,
                { result ->
                    val message = when (result) {
                        StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ADDED ->
                            "Añadido a los ajustes rápidos."
                        StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ALREADY_ADDED ->
                            "Ya estaba en los ajustes rápidos."
                        StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_NOT_ADDED ->
                            "No se añadió."
                        else -> "El sistema no aceptó la petición."
                    }
                    Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
                },
            )
        },
        modifier = Modifier
            .fillMaxWidth()
            .height(56.dp),
        shape = RoundedCornerShape(0.dp),
    ) {
        Icon(Icons.Filled.Add, contentDescription = null)
        Spacer(Modifier.width(12.dp))
        Text("Añadir a los ajustes rápidos")
    }
}

@Composable
private fun AboutDialog(onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("Cerrar") } },
        icon = { Icon(Icons.Filled.Info, contentDescription = null) },
        title = { Text("Arranque dual") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    "Cambia entre los sistemas instalados en este Galaxy Tab S9 Ultra " +
                        "reemplazando las cuatro particiones de arranque y reiniciando.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    "Cada imagen se comprueba por tamaño antes de escribirla y la " +
                        "partición se relee después. Si algo no coincide, para y no reinicia.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    "Nunca toca vbmeta ni super: lo primero borraría los datos de " +
                        "Android, y en lo segundo vive su sistema.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    "Parte del port de Ubuntu 24.04 para SM-X910.\n" +
                        "github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
    )
}

@Composable
private fun ProgressCard(state: UiState) {
    Card(
        Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (state.error != null) MaterialTheme.colorScheme.errorContainer
            else MaterialTheme.colorScheme.secondaryContainer,
        ),
    ) {
        Column(Modifier.padding(20.dp)) {
            if (state.busy) {
                LinearProgressIndicator(Modifier.fillMaxWidth())
                Spacer(Modifier.height(14.dp))
            }
            state.log.forEach {
                Text(it, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}
