package com.sky.stormrev

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import java.io.File
import java.util.Locale

/**
 * Reads chipset temperature and the platform thermal status.
 *
 * Android does not expose SoC temperature to normal apps, so we try the public
 * sysfs thermal zones first (readable on many devices) and fall back to the
 * battery/skin sensor, which is always available. The platform thermal status
 * is used as a floor so throttling still reaches the engine when no temperature
 * sensor can be read.
 */
class ThermalMonitor(context: Context) {

    private val appContext = context.applicationContext
    private val powerManager =
        appContext.getSystemService(Context.POWER_SERVICE) as PowerManager
    private val handler = Handler(Looper.getMainLooper())
    private val zoneFiles = ArrayList<File>()

    @Volatile
    private var running = false

    @Volatile
    var celsius: Float = Float.NaN
        private set

    @Volatile
    var sourceLabel: String = "SOC"
        private set

    @Volatile
    var statusLabel: String = "NORMAL"
        private set

    @Volatile
    var thermalStatus: Int = 0
        private set

    private val statusListener: PowerManager.OnThermalStatusChangedListener? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            PowerManager.OnThermalStatusChangedListener { status ->
                thermalStatus = status
                statusLabel = labelFor(status)
            }
        } else {
            null
        }

    private val tick = object : Runnable {
        override fun run() {
            val soc = readZones()
            celsius = if (soc.isNaN()) batteryCelsius() else soc
            sourceLabel = if (soc.isNaN()) "BATERAI" else "SOC"
            NativeBridge.setThermal(engineCelsius())
            if (running) handler.postDelayed(this, 1000L)
        }
    }

    init {
        discoverZones()
    }

    fun start() {
        if (running) return
        running = true
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            statusListener?.let { powerManager.addThermalStatusListener(it) }
            thermalStatus = powerManager.currentThermalStatus
            statusLabel = labelFor(thermalStatus)
        }
        handler.post(tick)
    }

    fun stop() {
        running = false
        handler.removeCallbacks(tick)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            statusListener?.let { powerManager.removeThermalStatusListener(it) }
        }
    }

    private fun discoverZones() {
        val root = File("/sys/class/thermal")
        val entries = root.listFiles { file -> file.name.startsWith("thermal_zone") } ?: return
        for (entry in entries.sortedBy { it.name }) {
            val type = runCatching {
                File(entry, "type").readText().trim().lowercase(Locale.US)
            }.getOrNull() ?: continue
            val interesting = listOf("cpu", "gpu", "soc", "tsens", "skin", "battery", "ap")
                .any { type.contains(it) }
            if (!interesting) continue
            val tempFile = File(entry, "temp")
            if (tempFile.canRead()) zoneFiles.add(tempFile)
        }
    }

    private fun readZones(): Float {
        var hottest = Float.NaN
        for (file in zoneFiles) {
            val raw = runCatching { file.readText().trim().toFloat() }.getOrNull() ?: continue
            val value = if (raw > 1000f) raw / 1000f else raw
            if (value < 5f || value > 120f) continue
            if (hottest.isNaN() || value > hottest) hottest = value
        }
        return hottest
    }

    private fun batteryCelsius(): Float {
        val intent = appContext.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            ?: return Float.NaN
        val tenths = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
        return if (tenths == Int.MIN_VALUE) Float.NaN else tenths / 10f
    }

    /** Temperature handed to the native governor: measured or status floor. */
    private fun engineCelsius(): Float {
        val floor = when (thermalStatus) {
            PowerManager.THERMAL_STATUS_LIGHT -> 56f
            PowerManager.THERMAL_STATUS_MODERATE -> 64f
            PowerManager.THERMAL_STATUS_SEVERE -> 72f
            PowerManager.THERMAL_STATUS_CRITICAL -> 80f
            PowerManager.THERMAL_STATUS_EMERGENCY,
            PowerManager.THERMAL_STATUS_SHUTDOWN -> 88f
            else -> Float.NaN
        }
        val measured = celsius
        return when {
            measured.isNaN() && floor.isNaN() -> -1000f
            measured.isNaN() -> floor
            floor.isNaN() -> measured
            else -> maxOf(measured, floor)
        }
    }

    private fun labelFor(status: Int): String = when (status) {
        PowerManager.THERMAL_STATUS_LIGHT -> "HANGAT"
        PowerManager.THERMAL_STATUS_MODERATE -> "PANAS"
        PowerManager.THERMAL_STATUS_SEVERE -> "THROTTLE"
        PowerManager.THERMAL_STATUS_CRITICAL -> "KRITIS"
        PowerManager.THERMAL_STATUS_EMERGENCY,
        PowerManager.THERMAL_STATUS_SHUTDOWN -> "DARURAT"
        else -> "NORMAL"
    }
}
