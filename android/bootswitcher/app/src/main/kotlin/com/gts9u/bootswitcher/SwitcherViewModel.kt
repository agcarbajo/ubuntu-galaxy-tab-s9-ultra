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

data class UiState(
    val loading: Boolean = true,
    val hasRoot: Boolean = false,
    val current: BootSets.BootSet? = null,
    val sets: List<BootSets.BootSet> = emptyList(),
    val busy: Boolean = false,
    val log: List<String> = emptyList(),
    /** Set once every partition is written and verified, so the UI can offer the reboot. */
    val readyToReboot: BootSets.BootSet? = null,
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
            val sets = BootSets.discover()
            val live = BootSets.liveHashes()
            sets to BootSets.identify(live, sets)
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

        val (sets, current) = result
        _state.update { it.copy(loading = false, hasRoot = true, sets = sets, current = current) }
    }

    fun switchTo(set: BootSets.BootSet) = viewModelScope.launch {
        _state.update { it.copy(busy = true, log = emptyList(), error = null, readyToReboot = null) }

        val ok = withContext(Dispatchers.IO) {
            BootSets.write(set) { progress ->
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

        _state.update {
            it.copy(
                busy = false,
                readyToReboot = if (ok) set else null,
                // After a verified write the live partitions really are this
                // set's, so the card stops claiming the old system.
                current = if (ok) set else it.current,
            )
        }
    }

    fun reboot() = viewModelScope.launch {
        withContext(Dispatchers.IO) { BootSets.reboot() }
    }
}
