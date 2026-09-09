package com.gts9u.bootswitcher

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class UiState(
    val loading: Boolean = true,
    val maintenanceLog: String = "",
    val hasRoot: Boolean = false,
    /** The system this app is running on. */
    val running: BootSets.BootSet? = null,
    /** The system the boot partitions will start. */
    val nextBoot: BootSets.BootSet? = null,
    val sets: List<BootSets.BootSet> = emptyList(),
    val storage: Map<String, BootSets.Share> = emptyMap(),
    val busy: Boolean = false,
    /** The partition being written right now, and the ones already verified. */
    val writing: String? = null,
    val written: List<String> = emptyList(),
    /** True once a write has ended, so the progress dialog can show a verdict. */
    val finished: Boolean = false,
    /** True once anything has been written this session: the console has something to show. */
    val hasRun: Boolean = false,
    /**
     * Whether the console is on screen.
     *
     * Only ever opened by asking for it: writing four partitions takes a few
     * seconds and the card already says it is working, so a dialog in the way
     * would be something to dismiss rather than something to read.
     */
    val showProgress: Boolean = false,
    val runError: Int? = null,
    val runErrorArg: String = "",
    val runErrorDetail: String = "",
) {
    /** Written but not yet booted: only a restart is missing. */
    val staged: Boolean
        get() = running != null && nextBoot != null && running.id != nextBoot.id

    /**
     * Whether there is anywhere to switch to.
     *
     * With a single system the quick settings tile has nothing to offer, so
     * the settings that only configure it are hidden rather than shown broken.
     */
    val canSwitch: Boolean
        get() = sets.count { it.complete } >= 2
}

class SwitcherViewModel(app: Application) : AndroidViewModel(app) {

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    fun refresh() = viewModelScope.launch {
        if (_state.value.loading && _state.value.hasRoot || _state.value.busy) return@launch
        _state.update { it.copy(loading = true) }

        val context = getApplication<Application>()
        val snapshot = withContext(Dispatchers.IO) {
            if (!Root.available()) return@withContext null

            val shot = BootState.read(context)
            shot to BootSets.storage()
        }

        if (snapshot == null) {
            _state.update { it.copy(loading = false, hasRoot = false) }
            return@launch
        }

        val (shot, storage) = snapshot
        _state.update {
            it.copy(
                loading = false,
                hasRoot = true,
                sets = shot.sets,
                running = shot.running,
                nextBoot = shot.nextBoot,
                storage = storage,
                maintenanceLog = BootMaintenance.log(context),
                hasRun = true,
            )
        }
    }

    /** Writes a set's images to the boot partitions without restarting. */
    fun stage(set: BootSets.BootSet) = apply(set, thenReboot = false)

    /**
     * Restarts into a set, writing it first only if it is not already there.
     *
     * A staged switch has already done the writing, so this is just a restart:
     * rewriting identical images would be four pointless partition writes.
     */
    fun rebootInto(set: BootSets.BootSet) = apply(set, thenReboot = true)

    /**
     * Hides the console without throwing the run away.
     *
     * What happened is kept so the console button can bring it back: the whole
     * point of not showing the detail is that it stays available.
     */
    fun dismissProgress() {
        _state.update { it.copy(showProgress = false) }
    }

    fun reopenProgress() {
        _state.update { it.copy(showProgress = true) }
    }

    private fun apply(set: BootSets.BootSet, thenReboot: Boolean) = viewModelScope.launch {
        if (_state.value.busy || _state.value.loading) return@launch
        val before = _state.value

        if (before.nextBoot?.id == set.id) {
            if (thenReboot) withContext(Dispatchers.IO) {
                synchronized(BootSets) {
                    if (BootMaintenance.beforeSwitch()) BootSets.reboot()
                }
            }
            return@launch
        }

        _state.update {
            it.copy(
                busy = true,
                writing = null,
                written = emptyList(),
                finished = false,
                runError = null,
                runErrorArg = "",
                runErrorDetail = "",
            )
        }

        val ok = withContext(Dispatchers.IO) {
            BootSets.write(set) { progress ->
                when (progress) {
                    is BootSets.Progress.Writing ->
                        _state.update { it.copy(writing = progress.part) }
                    is BootSets.Progress.Verified ->
                        _state.update {
                            it.copy(writing = null, written = it.written + progress.part)
                        }
                    is BootSets.Progress.Failed ->
                        _state.update {
                            it.copy(
                                writing = null,
                                runError = progress.text,
                                runErrorArg = progress.arg,
                                runErrorDetail = progress.detail,
                            )
                        }
                    BootSets.Progress.Done -> Unit
                }
            }
        }

        if (ok) {
            // The partitions really are this set's now, so the note about what
            // is still running has to be filed before the UI is told anything.
            BootState.stage(getApplication(), before.running, set)
        }

        _state.update {
            it.copy(
                busy = false,
                finished = true,
                hasRun = true,
                nextBoot = if (ok) set else it.nextBoot,
                maintenanceLog = BootMaintenance.log(getApplication()),
            )
        }

        if (ok && thenReboot) withContext(Dispatchers.IO) { BootSets.reboot() }
    }
}
