package com.gts9u.bootswitcher

import android.app.StatusBarManager
import android.content.ComponentName
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
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
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
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
    if (BootSets.isLinux(set)) Icons.Filled.Computer else Icons.Filled.Android

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
                title = { Text(stringResource(R.string.app_name)) },
                actions = {
                    IconButton(onClick = { showAbout = true }) {
                        Icon(Icons.Filled.Info, contentDescription = stringResource(R.string.about))
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

                // Nothing pops up any more, so this is where a run says it is
                // happening and, more to the point, where it says it failed.
                if (state.busy || state.runError != null) {
                    RunCard(state, onConsole = { vm.reopenProgress() })
                }

                if (state.hasRoot && state.sets.isNotEmpty()) {
                    SectionTitle(stringResource(R.string.section_systems))
                    SystemsCard(
                        state,
                        onStage = { vm.stage(it) },
                        onReboot = { vm.rebootInto(it) },
                        onConsole = { vm.reopenProgress() },
                    )
                }

                if (state.storage.isNotEmpty()) {
                    SectionTitle(stringResource(R.string.section_storage))
                    StorageCard(state)
                }

                SectionTitle(stringResource(R.string.section_settings))
                SettingsCard(
                    enabled = !state.busy,
                    canSwitch = state.canSwitch,
                    onRefresh = { vm.refresh() },
                )
                Spacer(Modifier.height(8.dp))
            }
        }
    }

    if (showAbout) AboutDialog(onDismiss = { showAbout = false })
    if (state.showProgress) ConsoleDialog(state, onDismiss = { vm.dismissProgress() })
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
    val running = state.running
    val (title, body, icon) = when {
        state.loading -> Triple(
            stringResource(R.string.hero_checking),
            stringResource(R.string.hero_checking_body),
            Icons.Filled.Refresh,
        )
        !state.hasRoot -> Triple(
            stringResource(R.string.hero_no_root),
            stringResource(R.string.error_no_root),
            Icons.Filled.Warning,
        )
        running == null -> Triple(
            stringResource(R.string.hero_unknown),
            stringResource(R.string.hero_unknown_body),
            Icons.Filled.Warning,
        )
        else -> Triple(stringResource(R.string.hero_running), running.label, iconFor(running))
    }

    val good = state.hasRoot && running != null
    // Checking is not a failure: asking for root can take a few seconds, and
    // painting the card red while it waits reads as "something is wrong".
    val bad = !state.loading && !good
    Card(
        Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(28.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (bad) MaterialTheme.colorScheme.errorContainer
            else MaterialTheme.colorScheme.primaryContainer,
        ),
    ) {
        Column {
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

            // A staged switch is the one thing that is true of the tablet but
            // invisible on it, so it is said here rather than only in the list.
            if (state.staged && state.nextBoot != null) {
                HorizontalDivider(Modifier.padding(horizontal = 24.dp))
                Row(
                    Modifier.padding(horizontal = 24.dp, vertical = 16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Filled.RestartAlt, contentDescription = null, Modifier.size(20.dp))
                    Spacer(Modifier.width(12.dp))
                    Text(
                        stringResource(R.string.hero_next, state.nextBoot.label),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }
        }
    }
}

/**
 * A run in progress, or the one that failed.
 *
 * Success says nothing here: the rows below already change to say which system
 * boots next, and a card repeating it would be one more thing to dismiss. A
 * failure is the opposite — it has to be impossible to miss, because the
 * tablet may be holding three of four partitions from a system it is not
 * running, and that only matters at the next restart.
 */
@Composable
private fun RunCard(state: UiState, onConsole: () -> Unit) {
    val failed = state.runError != null
    Card(
        Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (failed) MaterialTheme.colorScheme.errorContainer
            else MaterialTheme.colorScheme.secondaryContainer,
        ),
    ) {
        Row(
            Modifier.padding(horizontal = 20.dp, vertical = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (failed) {
                Icon(Icons.Filled.Warning, contentDescription = null)
            } else {
                CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
            }
            Spacer(Modifier.width(16.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    stringResource(
                        if (failed) R.string.progress_failed_title
                        else R.string.progress_title
                    ),
                    style = MaterialTheme.typography.titleMedium,
                )
                if (failed) {
                    Text(
                        stringResource(state.runError!!, state.runErrorArg),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            Spacer(Modifier.width(12.dp))
            IconButton(onClick = onConsole) {
                Icon(
                    Icons.Filled.Terminal,
                    contentDescription = stringResource(R.string.action_console),
                )
            }
        }
    }
}

@Composable
private fun SystemsCard(
    state: UiState,
    onStage: (BootSets.BootSet) -> Unit,
    onReboot: (BootSets.BootSet) -> Unit,
    onConsole: () -> Unit,
) {
    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(24.dp)) {
        // The running system first: it answers "where am I", and the rest of
        // the list is then plainly "where else can I go".
        val ordered = state.sets.sortedBy { it.id != state.running?.id }
        ordered.forEachIndexed { index, set ->
            val isRunning = set.id == state.running?.id
            val isNext = set.id == state.nextBoot?.id

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
                            isRunning -> stringResource(R.string.state_in_use)
                            isNext -> stringResource(R.string.state_next_boot)
                            set.complete -> stringResource(R.string.state_ready)
                            else -> stringResource(R.string.state_incomplete)
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = if (isNext && !isRunning) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.width(12.dp))

                when {
                    // Running and nothing pending: there is nowhere to go from
                    // this row, so it only reports.
                    isRunning && isNext -> Icon(
                        Icons.Filled.Check,
                        contentDescription = stringResource(R.string.state_in_use),
                        tint = MaterialTheme.colorScheme.primary,
                    )

                    // Running while another system is staged: this is the only
                    // way back, so undoing has to live here.
                    isRunning -> TextButton(
                        onClick = { onStage(set) },
                        enabled = !state.busy,
                    ) { Text(stringResource(R.string.action_cancel)) }

                    set.complete -> Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        // Only offered once there is something to look at.
                        IconButton(
                            onClick = onConsole,
                            enabled = state.hasRun || state.busy,
                        ) {
                            Icon(
                                Icons.Filled.Terminal,
                                contentDescription = stringResource(R.string.action_console),
                            )
                        }

                        // Already written: greyed out, because pressing it
                        // again would rewrite four identical partitions.
                        FilledTonalButton(
                            onClick = { onStage(set) },
                            enabled = !state.busy && !isNext,
                            shape = RoundedCornerShape(16.dp),
                        ) { Text(stringResource(R.string.action_stage)) }

                        Button(
                            onClick = { onReboot(set) },
                            enabled = !state.busy,
                            shape = RoundedCornerShape(16.dp),
                        ) {
                            Icon(
                                Icons.Filled.RestartAlt,
                                contentDescription = null,
                                Modifier.size(18.dp),
                            )
                            Spacer(Modifier.width(8.dp))
                            Text(stringResource(R.string.action_reboot))
                        }
                    }
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
                    LegendItem(
                        androidUsed,
                        stringResource(R.string.storage_android),
                        stringResource(
                            R.string.storage_used_of,
                            formatSize(it.used),
                            formatSize(it.total),
                        ),
                    )
                }
                linux?.let {
                    LegendItem(
                        linuxColor,
                        stringResource(R.string.storage_linux),
                        formatSize(it.total),
                    )
                }
            }
            Spacer(Modifier.height(10.dp))
            Text(
                stringResource(R.string.storage_note),
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

/**
 * The settings, minus the ones that would configure nothing.
 *
 * Both the skip-confirmation switch and the add-tile row exist only to set up
 * the quick settings tile, and that tile has nothing to switch to on a tablet
 * with a single system. Showing them there would be offering a preference
 * about something that cannot happen. Rechecking stays: it is how a tablet
 * that has just been given a second system notices.
 */
@Composable
private fun SettingsCard(enabled: Boolean, canSwitch: Boolean, onRefresh: () -> Unit) {
    val context = LocalContext.current
    val prefs = remember { Prefs(context) }
    var skip by remember { mutableStateOf(prefs.skipConfirmation) }

    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(24.dp)) {
        Column {
            if (canSwitch) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        stringResource(R.string.settings_skip_title),
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        stringResource(R.string.settings_skip_body),
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
            }

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
                Text(stringResource(R.string.settings_refresh))
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
    val label = stringResource(R.string.tile_label)
    val added = stringResource(R.string.tile_added)
    val already = stringResource(R.string.tile_already_added)
    val rejected = stringResource(R.string.tile_rejected)
    val failed = stringResource(R.string.tile_request_failed)

    TextButton(
        onClick = {
            val manager = context.getSystemService(StatusBarManager::class.java) ?: return@TextButton
            manager.requestAddTileService(
                ComponentName(context, BootSwitchTile::class.java),
                label,
                android.graphics.drawable.Icon.createWithResource(context, R.drawable.ic_tile_dualboot),
                context.mainExecutor,
                { result ->
                    val message = when (result) {
                        StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ADDED -> added
                        StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ALREADY_ADDED -> already
                        StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_NOT_ADDED -> rejected
                        else -> failed
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
        Text(stringResource(R.string.settings_add_tile))
    }
}

@Composable
private fun AboutDialog(onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.close)) }
        },
        icon = { Icon(Icons.Filled.Info, contentDescription = null) },
        title = { Text(stringResource(R.string.app_name)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    stringResource(R.string.about_what),
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    stringResource(R.string.about_checks),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    stringResource(R.string.about_untouched, BootSets.ROOT_DIR),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    stringResource(R.string.about_project),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
    )
}

/**
 * Which partition is being written, for whoever asks.
 *
 * Never opened on its own.  Writing four partitions is a few seconds' work
 * whose only interesting outcome is whether it worked, and the card on the
 * screen says that already; a dialog appearing by itself would be something to
 * dismiss rather than something to read.  This is here for the times it did
 * not work, and for anyone who simply wants to watch.
 *
 * The whole job is known before it starts, so all four rows are laid out from
 * the first frame and only their state changes: nothing grows, and the layout
 * does not jump while the tablet is being written to.
 */
@Composable
private fun ConsoleDialog(state: UiState, onDismiss: () -> Unit) {
    val failed = state.runError != null
    val done = state.finished && !failed

    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.close)) }
        },
        icon = {
            Icon(
                if (failed) Icons.Filled.Warning else Icons.Filled.RestartAlt,
                contentDescription = null,
            )
        },
        title = {
            Text(
                stringResource(
                    when {
                        failed -> R.string.progress_failed_title
                        done -> R.string.progress_done_title
                        else -> R.string.progress_title
                    }
                )
            )
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                val fraction = state.written.size / BootSets.PARTITIONS.size.toFloat()
                LinearProgressIndicator(
                    progress = { fraction },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(6.dp)
                        .clip(RoundedCornerShape(3.dp)),
                    color = if (failed) MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.primary,
                )
                Spacer(Modifier.height(6.dp))
                BootSets.PARTITIONS.forEach { part ->
                    PartitionRow(
                        name = part.name,
                        verified = part.name in state.written,
                        active = part.name == state.writing,
                    )
                }

                Spacer(Modifier.height(6.dp))
                when {
                    failed -> {
                        Text(
                            stringResource(state.runError!!, state.runErrorArg),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.error,
                        )
                        if (state.runErrorDetail.isNotBlank()) {
                            Text(
                                state.runErrorDetail,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    done && state.nextBoot != null -> Text(
                        stringResource(
                            if (state.staged) R.string.progress_staged
                            else R.string.progress_reverted,
                            state.nextBoot.label,
                        ),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }
        },
    )
}

@Composable
private fun PartitionRow(name: String, verified: Boolean, active: Boolean) {
    Row(
        Modifier
            .fillMaxWidth()
            .height(36.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(20.dp), contentAlignment = Alignment.Center) {
            when {
                verified -> Icon(
                    Icons.Filled.Check,
                    contentDescription = null,
                    Modifier.size(18.dp),
                    tint = MaterialTheme.colorScheme.primary,
                )
                active -> CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                else -> Box(
                    Modifier
                        .size(8.dp)
                        .clip(CircleShape)
                ) {
                    val idle = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.35f)
                    Canvas(Modifier.fillMaxSize()) { drawRect(idle, size = size) }
                }
            }
        }
        Spacer(Modifier.width(14.dp))
        Text(
            name,
            style = MaterialTheme.typography.bodyMedium,
            color = if (verified || active) MaterialTheme.colorScheme.onSurface
            else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
