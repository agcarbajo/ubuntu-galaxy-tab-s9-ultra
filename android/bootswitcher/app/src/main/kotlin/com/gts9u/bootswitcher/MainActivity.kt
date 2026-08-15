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
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Android
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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

/** Ubuntu gets the desktop glyph; every Android ROM gets the Android one. */
private fun iconFor(set: BootSets.BootSet): ImageVector =
    if (set.id.lowercase().contains("ubuntu")) Icons.Filled.Computer else Icons.Filled.Android

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SwitcherScreen(vm: SwitcherViewModel = viewModel()) {
    val state by vm.state.collectAsStateWithLifecycle()

    Scaffold(topBar = { TopAppBar(title = { Text("Arranque dual") }) }) { inner ->
        Surface(
            Modifier
                .fillMaxSize()
                .padding(inner)
        ) {
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 24.dp, vertical = 16.dp),
                verticalArrangement = Arrangement.spacedBy(20.dp),
            ) {
                CurrentSystemCard(state)

                if (state.busy || state.log.isNotEmpty()) ProgressCard(state)

                state.sets.forEach { set ->
                    SystemCard(
                        set = set,
                        isCurrent = state.current?.id == set.id,
                        enabled = !state.busy && set.complete,
                        onSwitch = { vm.switchTo(set) },
                    )
                }

                if (state.hasRoot && state.sets.isEmpty()) {
                    Text(
                        "No hay ningún juego en ${BootSets.ROOT_DIR}. Cada sistema es " +
                            "una carpeta con boot.img, init_boot.img, vendor_boot.img y dtbo.img.",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }

                AnimatedVisibility(state.readyToReboot != null) {
                    Button(
                        onClick = { vm.reboot() },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(64.dp),
                        shape = RoundedCornerShape(20.dp),
                    ) {
                        Icon(Icons.Filled.RestartAlt, contentDescription = null)
                        Spacer(Modifier.width(12.dp))
                        Text("Reiniciar ahora", style = MaterialTheme.typography.titleMedium)
                    }
                }

                AddTileButton(enabled = !state.busy)

                FilledTonalButton(
                    onClick = { vm.refresh() },
                    enabled = !state.busy,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(56.dp),
                    shape = RoundedCornerShape(18.dp),
                ) {
                    Icon(Icons.Filled.Refresh, contentDescription = null)
                    Spacer(Modifier.width(12.dp))
                    Text("Volver a comprobar")
                }

                Text(
                    "Las imágenes se leen de ${BootSets.ROOT_DIR}. Sólo se tocan boot, " +
                        "init_boot, vendor_boot y dtbo; vbmeta no se toca nunca, porque " +
                        "cambiarlo borraría los datos de Android. El sistema de Android " +
                        "vive en super, que esta app tampoco toca: por eso One UI y " +
                        "LineageOS se turnan en ese hueco en vez de convivir.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
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
private fun AddTileButton(enabled: Boolean) {
    val context = LocalContext.current

    FilledTonalButton(
        onClick = {
            val manager = context.getSystemService(StatusBarManager::class.java) ?: return@FilledTonalButton
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
        enabled = enabled,
        modifier = Modifier
            .fillMaxWidth()
            .height(56.dp),
        shape = RoundedCornerShape(18.dp),
    ) {
        Icon(Icons.Filled.Add, contentDescription = null)
        Spacer(Modifier.width(12.dp))
        Text("Añadir a los ajustes rápidos")
    }
}

@Composable
private fun CurrentSystemCard(state: UiState) {
    val current = state.current
    val (title, body, icon) = when {
        state.loading -> Triple("Comprobando…", "Leyendo las particiones de arranque.", Icons.Filled.Refresh)
        !state.hasRoot -> Triple("Sin root", state.error ?: "Esta app necesita root.", Icons.Filled.Warning)
        current == null -> Triple(
            "Sistema desconocido",
            "Las particiones no coinciden con ningún juego guardado.",
            Icons.Filled.Warning,
        )
        else -> Triple(
            "Ahora arranca ${current.label}",
            "Las cuatro particiones coinciden con el juego guardado.",
            iconFor(current),
        )
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
            Icon(icon, contentDescription = null, Modifier.size(40.dp))
            Spacer(Modifier.width(20.dp))
            Column {
                Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(6.dp))
                Text(body, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

@Composable
private fun SystemCard(
    set: BootSets.BootSet,
    isCurrent: Boolean,
    enabled: Boolean,
    onSwitch: () -> Unit,
) {
    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(28.dp)) {
        Column(Modifier.padding(24.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(iconFor(set), contentDescription = null)
                Spacer(Modifier.width(16.dp))
                Text(set.label, style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.width(12.dp))
                if (isCurrent) Icon(Icons.Filled.Check, contentDescription = "en uso")
            }

            Spacer(Modifier.height(8.dp))
            Text(
                if (set.complete) "Juego completo y con los tamaños correctos."
                else "Faltan imágenes o tienen tamaños raros en ${set.dir}.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Spacer(Modifier.height(16.dp))
            Button(
                onClick = onSwitch,
                enabled = enabled && !isCurrent,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(56.dp),
                shape = RoundedCornerShape(18.dp),
            ) {
                Text(if (isCurrent) "Ya está puesto" else "Cambiar a ${set.label}")
            }
        }
    }
}

@Composable
private fun ProgressCard(state: UiState) {
    Card(
        Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(28.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (state.error != null) MaterialTheme.colorScheme.errorContainer
            else MaterialTheme.colorScheme.secondaryContainer,
        ),
    ) {
        Column(Modifier.padding(24.dp)) {
            if (state.busy) {
                LinearProgressIndicator(Modifier.fillMaxWidth())
                Spacer(Modifier.height(16.dp))
            }
            state.log.forEach { Text(it, style = MaterialTheme.typography.bodyMedium) }
        }
    }
}
