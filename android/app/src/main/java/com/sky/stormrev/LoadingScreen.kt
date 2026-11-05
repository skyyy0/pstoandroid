package com.sky.stormrev

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.os.SystemClock
import android.view.View

/**
 * Loading screen shown while the engine loads the arena, bakes the pose palette
 * and compiles the GLES programs. It also carries the port credit: this is a
 * fan-made native port, built and maintained by sky.
 *
 * Drawn with Canvas on purpose - no extra dependency, and it keeps the loading
 * frame budget empty for the engine that is initialising behind it.
 */
class LoadingScreen(context: Context) : View(context) {

    private val density = resources.displayMetrics.density
    private val scaled = resources.displayMetrics.scaledDensity
    private fun dp(value: Float) = value * density
    private fun sp(value: Float) = value * scaled

    private val background = Paint(Paint.ANTI_ALIAS_FLAG)
    private val glow = Paint(Paint.ANTI_ALIAS_FLAG)
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = dp(1f)
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        textAlign = Paint.Align.CENTER
    }
    private val heavyPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Typeface.create("sans-serif-black", Typeface.BOLD)
        textAlign = Paint.Align.CENTER
    }
    private val monoPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
        textAlign = Paint.Align.CENTER
    }
    private val creditCard = RectF()
    private val progressTrack = RectF()

    private val startedAt = SystemClock.uptimeMillis()
    private var progress = 0f
    private var status = "Menyiapkan aset, tekstur & shader…"
    private var failed = false
    private var exiting = false

    private val tick = object : Runnable {
        override fun run() {
            if (exiting) return
            val elapsed = (SystemClock.uptimeMillis() - startedAt) / 1000f
            // Creeps toward 92% while loading; the real trigger is the engine.
            progress = (elapsed / 2.4f).coerceIn(0f, 0.92f)
            invalidate()
            postDelayed(this, 33L)
        }
    }

    init {
        isClickable = true
        keepScreenOn = true
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        post(tick)
    }

    override fun onDetachedFromWindow() {
        removeCallbacks(tick)
        super.onDetachedFromWindow()
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        if (w <= 0 || h <= 0) return
        background.shader = LinearGradient(
            0f,
            0f,
            0f,
            h.toFloat(),
            intArrayOf(NIGHT_TOP, NIGHT_MID, NIGHT_BOTTOM),
            floatArrayOf(0f, 0.58f, 1f),
            Shader.TileMode.CLAMP,
        )
        glow.shader = RadialGradient(
            w * 0.84f,
            h * 0.10f,
            w * 0.95f,
            0x44FF8A3D,
            Color.TRANSPARENT,
            Shader.TileMode.CLAMP,
        )
        val margin = dp(26f)
        creditCard.set(
            margin,
            h * 0.435f,
            w - margin,
            h * 0.435f + dp(118f),
        )
        progressTrack.set(
            w * 0.5f - (w - margin * 2f) * 0.5f,
            h * 0.735f,
            w * 0.5f + (w - margin * 2f) * 0.5f,
            h * 0.735f + dp(4f),
        )
    }

    /** Fades the screen out; safe to call more than once. */
    fun dismiss() {
        if (exiting) return
        exiting = true
        removeCallbacks(tick)
        animate().alpha(0f).setDuration(340L).withEndAction {
            visibility = GONE
            alpha = 1f
        }
    }

    fun showError() {
        if (exiting || failed) return
        failed = true
        status = "Engine gagal start — cek logcat (tag StormPort)"
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 0f || h <= 0f) return

        canvas.drawRect(0f, 0f, w, h, background)
        canvas.drawCircle(w * 0.84f, h * 0.10f, w * 0.95f, glow)

        // Kicker + title.
        textPaint.textSize = sp(10f)
        textPaint.letterSpacing = 0.30f
        textPaint.color = ORANGE_SOFT
        canvas.drawText("NATIVE ANDROID PORT", w * 0.5f, h * 0.20f, textPaint)

        heavyPaint.textSize = sp(56f)
        heavyPaint.letterSpacing = 0.02f
        heavyPaint.color = TEXT_PRIMARY
        canvas.drawText("STORM", w * 0.5f, h * 0.278f, heavyPaint)

        textPaint.textSize = sp(15f)
        textPaint.letterSpacing = 0.42f
        textPaint.color = TEXT_SECONDARY
        canvas.drawText("REVOLUTION", w * 0.5f, h * 0.328f, textPaint)

        fill.color = ORANGE
        canvas.drawRoundRect(
            w * 0.5f - dp(28f),
            h * 0.352f,
            w * 0.5f + dp(28f),
            h * 0.352f + dp(2f),
            dp(1f),
            dp(1f),
            fill,
        )

        // Credit card: the porter, front and centre.
        fill.color = 0x1AFFFFFF
        canvas.drawRoundRect(creditCard, dp(18f), dp(18f), fill)
        stroke.color = 0x2EFFFFFF
        canvas.drawRoundRect(creditCard, dp(18f), dp(18f), stroke)

        val cardCenter = creditCard.centerX()
        val cardTop = creditCard.top

        textPaint.textSize = sp(9f)
        textPaint.letterSpacing = 0.34f
        textPaint.color = TEXT_MUTED
        canvas.drawText("PORTED BY", cardCenter, cardTop + dp(26f), textPaint)

        heavyPaint.textSize = sp(38f)
        heavyPaint.letterSpacing = 0.16f
        heavyPaint.color = ORANGE
        canvas.drawText("SKY", cardCenter, cardTop + dp(66f), heavyPaint)

        textPaint.textSize = sp(9f)
        textPaint.letterSpacing = 0.05f
        textPaint.color = TEXT_SECONDARY
        canvas.drawText("engine · renderer · build pipeline", cardCenter, cardTop + dp(90f), textPaint)
        textPaint.textSize = sp(8f)
        textPaint.color = TEXT_MUTED
        canvas.drawText("fan-made port, no retail assets", cardCenter, cardTop + dp(106f), textPaint)

        // Progress bar.
        fill.color = 0x33FFFFFF
        canvas.drawRoundRect(progressTrack, dp(2f), dp(2f), fill)
        val filled = progressTrack.width() * progress
        if (filled > dp(1f)) {
            fill.color = if (failed) CRIMSON else ORANGE
            canvas.drawRoundRect(
                progressTrack.left,
                progressTrack.top,
                progressTrack.left + filled,
                progressTrack.bottom,
                dp(2f),
                dp(2f),
                fill,
            )
        }

        monoPaint.textSize = sp(9f)
        monoPaint.color = if (failed) CRIMSON else TEXT_SECONDARY
        canvas.drawText(status, w * 0.5f, progressTrack.bottom + dp(20f), monoPaint)

        textPaint.textSize = sp(8f)
        textPaint.letterSpacing = 0.18f
        textPaint.color = TEXT_MUTED
        canvas.drawText("GLES 3 · 60 FPS TARGET · ADAPTIVE QUALITY", w * 0.5f, h - dp(26f), textPaint)
    }

    private companion object {
        fun hex(value: Long): Int = value.toInt()

        val ORANGE = hex(0xFFFF8A3D)
        val ORANGE_SOFT = hex(0xCCFF8A3D)
        val CRIMSON = hex(0xFFE0524A)
        val TEXT_PRIMARY = hex(0xFFF2F5FA)
        val TEXT_SECONDARY = hex(0xFF9AA6B8)
        val TEXT_MUTED = hex(0xFF6B7688)
        val NIGHT_TOP = hex(0xFF07090F)
        val NIGHT_MID = hex(0xFF111420)
        val NIGHT_BOTTOM = hex(0xFF1A131C)
    }
}
