package com.sky.stormrev

import android.content.Context
import android.graphics.PixelFormat
import android.opengl.GLSurfaceView
import android.util.Log
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10

/**
 * Owns the GLES 3 context. The engine keeps its own offscreen colour target, so
 * this surface is only used for the final blit and can stay at 8-bit RGBA.
 */
class StormGLSurfaceView(context: Context) : GLSurfaceView(context) {

    @Volatile
    var engineError: String? = null
        private set

    private val renderer = object : GLSurfaceView.Renderer {
        override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
            NativeBridge.shutdown()
            val ok = NativeBridge.initialize(context.applicationContext.assets)
            NativeBridge.ready = ok
            engineError = if (ok) null else "Gagal memuat aset storm/. Cek logcat (tag StormPort)."
            if (!ok) Log.e("StormPort", "native init failed")
        }

        override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
            NativeBridge.resize(width, height)
        }

        override fun onDrawFrame(gl: GL10?) {
            if (NativeBridge.ready) {
                NativeBridge.frame()
            } else {
                gl?.glClearColor(0.04f, 0.04f, 0.06f, 1.0f)
                gl?.glClear(GL10.GL_COLOR_BUFFER_BIT)
            }
        }
    }

    init {
        setEGLContextClientVersion(3)
        setEGLConfigChooser(8, 8, 8, 8, 16, 0)
        preserveEGLContextOnPause = false
        holder.setFormat(PixelFormat.RGBA_8888)
        setRenderer(renderer)
        renderMode = RENDERMODE_CONTINUOUSLY
    }

}
