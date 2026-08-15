package com.gts9u.bootswitcher

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class SetStatus(
    val system: BootSets.System,
    val complete: Boolean,
)

data class UiState(
    val loading: Boolean = true,
    val hasRoot: Boolean = false,
    val current: BootSets.System? = null,
    val sets: List<SetStatus> = emptyList(),
    val busy: Boolean = false,
    val log: List<String> = emptyList(),
    /** Set once every partition is written and verified, so the UI can offer the reboot. */
    val readyToReboot: BootSets.System? = null,
    val error: String? = null,
)

class SwitcherViewModel : ViewModel() {

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() = viewModelScope.launch {
        _state.update { it.copy(loading = true, error = null, readyToReboot = null, log = emptyList()) }

        val result = withContext(Dispatchers.IO) {
            if (!Root.available()) return@withContext null
            val live = BootSets.liveHashes()
            val sets = BootSets.System.entries.associateWith { BootSets.setHashes(it) }
            Triple(live, sets, BootSets.identify(live, sets))
        }

        if (result == null) {
            _state.update {
                it.copy(
                    loading = false,
                    hasRoot = false,
                    error = "Sin acceso root. Concédeselo a esta app en Magisk, " +
                        "y recuerda que una petición que caduca queda guardada como denegada.",
                )
            }
            return@launch
        }

        val (_, sets, current) = result
        _state.update { s ->
            s.copy(
                loading = false,
                hasRoot = true,
                current = current,
                sets = BootSets.System.entries.map { system ->
                    SetStatus(system, complete = (sets[system]?.size ?: 0) == BootSets.PARTITIONS.size)
                },
            )
        }
    }

    fun switchTo(system: BootSets.System) = viewModelScope.launch {
        _state.update { it.copy(busy = true, log = emptyList(), error = null, readyToReboot = null) }

        val ok = withContext(Dispatchers.IO) {
            BootSets.write(system) { progress ->
                when (progress) {
                    is BootSets.Progress.Step ->
                        _state.update { it.copy(log = it.log + progress.message) }
                    is BootSets.Progress.Failed ->
                        _state.update { it.copy(log = it.log + progress.message, error = progress.message) }
                    BootSets.Progress.Done ->
                        _state.update { it.copy(log = it.log + "Las cuatro particiones coinciden.") }
                }
            }
        }

        _state.update { it.copy(busy = false, readyToReboot = if (ok) system else null) }
        if (ok) refresh0(system)
    }

    /** After a successful write the live partitions are the target's, so say so. */
    private fun refresh0(system: BootSets.System) {
        _state.update { it.copy(current = system) }
    }

    fun reboot() = viewModelScope.launch {
        withContext(Dispatchers.IO) { BootSets.reboot() }
    }
}
