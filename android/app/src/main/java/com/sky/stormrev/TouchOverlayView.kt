package com.sky.stormrev

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.os.Handler
import android.os.Looper
import android.view.MotionEvent
import android.view.View
import org.json.JSONObject
import java.util.Locale
import kotlin.math.hypot

/**
 * On-screen HUD + touch controls drawn with Canvas over the GL surface.
 *
 * Top-left telemetry shows the live frame rate and chipset temperature (the
 * value that also drives the native performance governor), because that pair is
 * what actually explains a frame drop on a phone.
 */
class TouchOverlayView(context: Context, private val thermal: ThermalMonitor) : View(context) {

    private data class Control(
        val label: String,
        val bit: Int,
        val x: Float,
        val y: Float,
        val radius: Float,
        val color: Int,
    )

    private val density = resources.displayMetrics.density
    private fun dp(value: Float) = value * density

    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = dp(1.2f)
    }
    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        textAlign = Paint.Align.LEFT
    }
    private val monoPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
        textAlign = Paint.Align.LEFT
    }

    private val controls = ArrayList<Control>()
    private val pointerButtons = HashMap<Int, Int>()
    private var heldBits = 0

    private var stickPointer = -1
    private var stickActive = false
    private var stickBaseX = 0f
    private var stickBaseY = 0f
    private var stickBaseRadius = 0f
    private var stickX = 0f
    private var stickY = 0f

    private var stats = JSONObject()
    private var phase = 0
    private val rematch = RectF()

    private val handler = Handler(Looper.getMainLooper())
    private val poll = object : Runnable {
        override fun run() {
            stats = runCatching { JSONObject(NativeBridge.stats()) }.getOrDefault(JSONObject())
            phase = if (NativeBridge.ready) stats.optInt("phase", 0) else 0
            invalidate()
            handler.postDelayed(this, 100L)
        }
    }

    init {
        isClickable = true
        keepScreenOn = true
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        handler.post(poll)
    }

    override fun onDetachedFromWindow() {
        handler.removeCallbacks(poll)
        super.onDetachedFromWindow()
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        layoutControls()
    }

    private fun layoutControls() {
        val w = width.toFloat()
        val h = height.toFloat()
        controls.clear()
        controls += Control("ATK", NativeBridge.BUTTON_ATTACK, w - dp(104f), h - dp(104f), dp(60f), ORANGE)
        controls += Control("CHK", NativeBridge.BUTTON_CHAKRA, w - dp(214f), h - dp(142f), dp(46f), CHAKRA)
        controls += Control("GRD", NativeBridge.BUTTON_GUARD, w - dp(146f), h - dp(218f), dp(44f), GUARD)
        controls += Control("JMP", NativeBridge.BUTTON_JUMP, w - dp(60f), h - dp(232f), dp(42f), JUMP)
        controls += Control("DSH", NativeBridge.BUTTON_DASH, w - dp(282f), h - dp(74f), dp(36f), DASH)
        stickBaseX = dp(132f)
        stickBaseY = h - dp(140f)
        stickBaseRadius = dp(88f)
        rematch.set(
            w / 2f - dp(84f),
            h - dp(196f),
            w / 2f + dp(84f),
            h - dp(152f),
        )
    }

    // ---------------------------------------------------------------- input

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (!NativeBridge.ready) return true
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN -> {
                val index = event.actionIndex
                val id = event.getPointerId(index)
                val x = event.getX(index)
                val y = event.getY(index)

                if (phase != 0 && rematch.contains(x, y)) {
                    NativeBridge.resetMatch()
                    return true
                }

                val hit = controls.firstOrNull { hypot(x - it.x, y - it.y) <= it.radius * 1.18f }
                if (hit != null) {
                    pointerButtons[id] = hit.bit
                    heldBits = heldBits or hit.bit
                    pushInput()
                    invalidate()
                    return true
                }
                if (stickPointer < 0 && x < width * 0.5f) {
                    stickPointer = id
                    stickActive = true
                    stickBaseX = x
                    stickBaseY = y
                    stickX = 0f
                    stickY = 0f
                    pushInput()
                    invalidate()
                }
            }

            MotionEvent.ACTION_MOVE -> {
                if (stickPointer >= 0) {
                    val index = event.findPointerIndex(stickPointer)
                    if (index >= 0) {
                        updateStick(event.getX(index), event.getY(index))
                    }
                }
            }

            MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP -> {
                val id = event.getPointerId(event.actionIndex)
                releasePointer(id)
            }

            MotionEvent.ACTION_CANCEL -> {
                pointerButtons.clear()
                heldBits = 0
                stickPointer = -1
                stickActive = false
                stickX = 0f
                stickY = 0f
                pushInput()
                invalidate()
            }
        }
        return true
    }

    private fun releasePointer(id: Int) {
        val bit = pointerButtons.remove(id)
        if (bit != null) {
            heldBits = heldBits and bit.inv()
        }
        if (id == stickPointer) {
            stickPointer = -1
            stickActive = false
            stickX = 0f
            stickY = 0f
            stickBaseX = dp(132f)
            stickBaseY = height.toFloat() - dp(140f)
        }
        pushInput()
        invalidate()
    }

    private fun updateStick(x: Float, y: Float) {
        val dx = x - stickBaseX
        val dy = y - stickBaseY
        val distance = hypot(dx, dy)
        val limit = stickBaseRadius
        val clamped = if (distance > limit && distance > 0.001f) limit / distance else 1f
        val knobX = dx * clamped
        val knobY = dy * clamped
        val deadZone = dp(8f)
        stickX = if (kotlin.math.abs(knobX) < deadZone) 0f else (knobX / limit).coerceIn(-1f, 1f)
        // Screen up is toward the opponent, so invert the screen delta.
        stickY = if (kotlin.math.abs(knobY) < deadZone) 0f else (-knobY / limit).coerceIn(-1f, 1f)
        pushInput()
        invalidate()
    }

    private fun pushInput() {
        NativeBridge.setInput(stickX, stickY, heldBits)
    }

    // ---------------------------------------------------------------- render

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        drawTelemetry(canvas)
        drawHealthHud(canvas)
        drawStick(canvas)
        drawControls(canvas)
        drawMatchState(canvas)
        if (!NativeBridge.ready) {
            labelPaint.textAlign = Paint.Align.CENTER
            labelPaint.textSize = dp(13f)
            labelPaint.color = TEXT_SECONDARY
            canvas.drawText(
                "Menyiapkan engine… (log: StormPort)",
                width / 2f,
                height / 2f,
                labelPaint,
            )
        }
    }

    private fun drawTelemetry(canvas: Canvas) {
        val left = dp(12f)
        val top = dp(12f)
        val right = left + dp(212f)
        val bottom = top + dp(92f)

        fill.color = 0xD90B0E16.toInt()
        canvas.drawRoundRect(left, top, right, bottom, dp(14f), dp(14f), fill)
        stroke.color = 0x33FFFFFF
        canvas.drawRoundRect(left, top, right, bottom, dp(14f), dp(14f), stroke)

        fill.color = ORANGE
        canvas.drawRoundRect(left + dp(10f), top + dp(12f), left + dp(13f), top + dp(34f), dp(2f), dp(2f), fill)

        val fps = if (stats.has("fps")) stats.optDouble("fps", 0.0) else Double.NaN
        val fpsText = if (fps.isNaN()) "--" else String.format(Locale.US, "%.0f", fps)

        monoPaint.textSize = dp(27f)
        monoPaint.color = TEXT_PRIMARY
        canvas.drawText(fpsText, left + dp(21f), top + dp(42f), monoPaint)
        val fpsWidth = monoPaint.measureText(fpsText)

        labelPaint.textSize = dp(9f)
        labelPaint.color = TEXT_SECONDARY
        labelPaint.textAlign = Paint.Align.LEFT
        canvas.drawText("FPS", left + dp(23f) + fpsWidth, top + dp(40f), labelPaint)

        // Chipset temperature, colour-coded: cool -> hot.
        val celsius = thermal.celsius
        val tempColor = when {
            celsius.isNaN() -> TEXT_MUTED
            celsius < 52f -> COOL
            celsius < 64f -> WARM
            else -> HOT
        }
        val tempText = if (celsius.isNaN()) "--" else String.format(Locale.US, "%.1f", celsius)
        monoPaint.textSize = dp(21f)
        monoPaint.color = tempColor
        canvas.drawText(tempText, left + dp(112f), top + dp(42f), monoPaint)
        val tempWidth = monoPaint.measureText(tempText)

        labelPaint.textSize = dp(9f)
        labelPaint.color = tempColor
        canvas.drawText("°C", left + dp(114f) + tempWidth, top + dp(40f), labelPaint)

        labelPaint.color = TEXT_MUTED
        labelPaint.textSize = dp(8f)
        canvas.drawText(
            "${thermal.sourceLabel} · ${thermal.statusLabel}",
            left + dp(112f),
            top + dp(55f),
            labelPaint,
        )

        val scale = stats.optDouble("scale", 1.0)
        val tier = stats.optInt("tier", 3)
        val draws = stats.optInt("draws", 0)
        val rw = stats.optInt("rw", 0)
        val rh = stats.optInt("rh", 0)
        labelPaint.color = TEXT_SECONDARY
        labelPaint.textSize = dp(8f)
        val detail = if (rw > 0) {
            String.format(Locale.US, "%.2fx · T%d · %d draw · %dx%d", scale, tier, draws, rw, rh)
        } else {
            String.format(Locale.US, "%.2fx · T%d", scale, tier)
        }
        canvas.drawText(detail, left + dp(21f), top + dp(78f), labelPaint)
    }

    private fun drawHealthHud(canvas: Canvas) {
        val margin = dp(12f)
        val top = dp(114f)
        val height = dp(16f)
        val gap = dp(14f)
        val timerWidth = dp(66f)
        val sideWidth = (width - margin * 2 - timerWidth - gap * 2) / 2f
        if (sideWidth <= dp(40f)) return

        val hp0 = stats.optDouble("hp0", 1.0).toFloat()
        val hp1 = stats.optDouble("hp1", 1.0).toFloat()
        val ck0 = stats.optDouble("ck0", 1.0).toFloat()
        val ck1 = stats.optDouble("ck1", 1.0).toFloat()

        drawHealthBar(canvas, margin, top, sideWidth, height, hp0, ck0, ORANGE, false)
        drawHealthBar(
            canvas,
            width - margin - sideWidth,
            top,
            sideWidth,
            height,
            hp1,
            ck1,
            CRIMSON,
            true,
        )

        val seconds = stats.optDouble("time", 99.0)
        val timer = if (seconds.isNaN()) "--" else String.format(Locale.US, "%02d", seconds.toInt())
        monoPaint.textAlign = Paint.Align.CENTER
        monoPaint.textSize = dp(25f)
        monoPaint.color = TEXT_PRIMARY
        canvas.drawText(timer, width / 2f, top + dp(17f), monoPaint)
        monoPaint.textAlign = Paint.Align.LEFT

        labelPaint.textSize = dp(9f)
        labelPaint.color = TEXT_SECONDARY
        labelPaint.textAlign = Paint.Align.LEFT
        canvas.drawText("ROOKIE", margin + dp(2f), top - dp(6f), labelPaint)
        labelPaint.textAlign = Paint.Align.RIGHT
        canvas.drawText("RIVAL", width - margin - dp(2f), top - dp(6f), labelPaint)
        labelPaint.textAlign = Paint.Align.LEFT
    }

    private fun drawHealthBar(
        canvas: Canvas,
        x: Float,
        y: Float,
        w: Float,
        h: Float,
        hp: Float,
        chakra: Float,
        color: Int,
        mirrored: Boolean,
    ) {
        fill.color = 0xB30B0E16.toInt()
        canvas.drawRoundRect(x, y, x + w, y + h, dp(5f), dp(5f), fill)

        val inset = dp(2f)
        val fillWidth = (w - inset * 2f) * hp.coerceIn(0f, 1f)
        if (fillWidth > 0.5f) {
            val left = if (mirrored) x + w - inset - fillWidth else x + inset
            fill.color = color
            canvas.drawRoundRect(left, y + inset, left + fillWidth, y + h - inset, dp(4f), dp(4f), fill)
        }

        // Chakra gauge under the health bar.
        val chakraTop = y + h + dp(3f)
        fill.color = 0x800B0E16.toInt()
        canvas.drawRoundRect(x, chakraTop, x + w, chakraTop + dp(4f), dp(2f), dp(2f), fill)
        val chakraWidth = w * chakra.coerceIn(0f, 1f)
        if (chakraWidth > 0.5f) {
            val left = if (mirrored) x + w - chakraWidth else x
            fill.color = CHAKRA
            canvas.drawRoundRect(left, chakraTop, left + chakraWidth, chakraTop + dp(4f), dp(2f), dp(2f), fill)
        }
    }

    private fun drawStick(canvas: Canvas) {
        val baseAlpha = if (stickActive) 130 else 60
        fill.color = Color.argb(baseAlpha, 245, 247, 250)
        canvas.drawCircle(stickBaseX, stickBaseY, stickBaseRadius, fill)

        stroke.color = Color.argb(if (stickActive) 220 else 110, 255, 138, 61)
        stroke.strokeWidth = dp(2f)
        canvas.drawCircle(stickBaseX, stickBaseY, stickBaseRadius, stroke)

        val knobX = stickBaseX + stickX * stickBaseRadius * 0.62f
        val knobY = stickBaseY - stickY * stickBaseRadius * 0.62f
        fill.color = Color.argb(if (stickActive) 235 else 150, 255, 138, 61)
        canvas.drawCircle(knobX, knobY, dp(30f), fill)
    }

    private fun drawControls(canvas: Canvas) {
        for (control in controls) {
            val pressed = (heldBits and control.bit) != 0
            fill.color = if (pressed) control.color else 0x66101420
            canvas.drawCircle(control.x, control.y, control.radius, fill)

            stroke.color = control.color
            stroke.strokeWidth = dp(2f)
            canvas.drawCircle(control.x, control.y, control.radius, stroke)

            labelPaint.textAlign = Paint.Align.CENTER
            labelPaint.textSize = dp(12f)
            labelPaint.color = TEXT_PRIMARY
            canvas.drawText(control.label, control.x, control.y + dp(4f), labelPaint)
            labelPaint.textAlign = Paint.Align.LEFT
        }
    }

    private fun drawMatchState(canvas: Canvas) {
        if (phase == 0) return
        val message = when (phase) {
            1 -> "K.O. — KAMU MENANG"
            2 -> "K.O. — KAMU KALAH"
            else -> "WAKTU HABIS — SERI"
        }
        labelPaint.textAlign = Paint.Align.CENTER
        labelPaint.textSize = dp(26f)
        labelPaint.color = ORANGE
        canvas.drawText(message, width / 2f, height * 0.42f, labelPaint)

        fill.color = 0xCC101420.toInt()
        canvas.drawRoundRect(rematch, dp(22f), dp(22f), fill)
        stroke.color = ORANGE
        stroke.strokeWidth = dp(1.6f)
        canvas.drawRoundRect(rematch, dp(22f), dp(22f), stroke)
        labelPaint.textSize = dp(13f)
        labelPaint.color = TEXT_PRIMARY
        canvas.drawText(
            "REMATCH",
            rematch.centerX(),
            rematch.centerY() + dp(5f),
            labelPaint,
        )
        labelPaint.textAlign = Paint.Align.LEFT
    }

    private companion object {
        // Not `const`: hex literals above Int.MAX_VALUE are Long, so the
        // `.toInt()` call is not a compile-time constant.
        val ORANGE = 0xFFFF8A3D.toInt()
        val CRIMSON = 0xFFE0524A.toInt()
        val CHAKRA = 0xFF4EA3FF.toInt()
        val GUARD = 0xFF9AA4B2.toInt()
        val JUMP = 0xFFB98CFF.toInt()
        val DASH = 0xFF5AD1A8.toInt()
        val COOL = 0xFF7DE38B.toInt()
        val WARM = 0xFFFFC857.toInt()
        val HOT = 0xFFFF6B6B.toInt()
        val TEXT_PRIMARY = 0xFFF2F5FA.toInt()
        val TEXT_SECONDARY = 0xFF9AA6B8.toInt()
        val TEXT_MUTED = 0xFF6B7688.toInt()
    }
}
