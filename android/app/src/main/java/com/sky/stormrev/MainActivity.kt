package com.sky.stormrev

import android.app.Activity
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout

class MainActivity : Activity() {

    private lateinit var surfaceView: StormGLSurfaceView
    private lateinit var overlay: TouchOverlayView
    private lateinit var loading: LoadingScreen
    private var thermal: ThermalMonitor? = null

    private val handler = Handler(Looper.getMainLooper())
    private var startedAt = 0L

    /** Reveals the HUD once the native engine has loaded its first frame. */
    private val readyPoll = object : Runnable {
        override fun run() {
            val elapsed = SystemClock.uptimeMillis() - startedAt
            if (NativeBridge.ready) {
                if (elapsed >= 1100L) {
                    overlay.visibility = View.VISIBLE
                    loading.dismiss()
                    return
                }
            } else if (elapsed > 20_000L) {
                loading.showError()
            }
            handler.postDelayed(this, 80L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            window.attributes.layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }

        val root = FrameLayout(this)
        surfaceView = StormGLSurfaceView(this)
        root.addView(
            surfaceView,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )

        val monitor = ThermalMonitor(this)
        thermal = monitor
        overlay = TouchOverlayView(this, monitor)
        // The controls must not appear (or accept input) before the arena is up.
        overlay.visibility = View.INVISIBLE
        root.addView(
            overlay,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )

        loading = LoadingScreen(this)
        root.addView(
            loading,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )

        setContentView(root)
        applyImmersiveMode()

        startedAt = SystemClock.uptimeMillis()
        handler.post(readyPoll)
    }

    override fun onResume() {
        super.onResume()
        surfaceView.onResume()
        thermal?.start()
        applyImmersiveMode()
        // The GL context (and therefore the engine) is recreated on resume; keep
        // watching until the HUD has been revealed at least once.
        if (overlay.visibility != View.VISIBLE) {
            handler.removeCallbacks(readyPoll)
            handler.post(readyPoll)
        }
    }

    override fun onPause() {
        thermal?.stop()
        surfaceView.onPause()
        handler.removeCallbacks(readyPoll)
        super.onPause()
    }

    override fun onDestroy() {
        handler.removeCallbacks(readyPoll)
        super.onDestroy()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) applyImmersiveMode()
    }

    @Suppress("DEPRECATION")
    private fun applyImmersiveMode() {
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                or View.SYSTEM_UI_FLAG_FULLSCREEN
                or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
            )
    }
}
