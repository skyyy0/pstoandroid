package com.sky.stormrev

import android.content.res.AssetManager

/**
 * Thin JNI surface. Every heavy call runs on the GL thread; input and thermal
 * data cross threads only through atomics on the native side.
 */
object NativeBridge {
    const val BUTTON_ATTACK = 1 shl 0
    const val BUTTON_CHAKRA = 1 shl 1
    const val BUTTON_GUARD = 1 shl 2
    const val BUTTON_JUMP = 1 shl 3
    const val BUTTON_DASH = 1 shl 4

    @Volatile
    var ready: Boolean = false

    init {
        System.loadLibrary("stormjni")
    }

    /**
     * [cores] and [ramMb] let the native governor seed a device profile before
     * the first frame: entry-level phones start below native resolution instead
     * of stuttering until the adaptive controller catches up.
     */
    external fun initialize(assetManager: AssetManager, cores: Int, ramMb: Int): Boolean
    external fun shutdown()
    external fun resize(width: Int, height: Int)
    external fun frame()
    external fun setInput(moveX: Float, moveY: Float, buttons: Int)
    external fun setThermal(celsius: Float)
    external fun resetMatch()
    external fun stats(): String
}
