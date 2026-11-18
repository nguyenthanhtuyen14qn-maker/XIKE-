// =====================================================================
// XI KE AGENT - PHẦN ANDROID cho app "Nhật Ký XAUUSD"
// Gồm: lưu cài đặt, ảnh mẫu, thông báo, màn hình AgentActivity.
// Màn hình tự dựng bằng code (không cần file XML).
// Cần file XiKeAgentCore.kt nằm cùng thư mục.
// =====================================================================
package xike.agent

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.Executors

// ---------------- Lưu cài đặt + ảnh mẫu ----------------
class AgentStore(ctx: Context) {
    private val p = ctx.getSharedPreferences("xike_agent", Context.MODE_PRIVATE)
    private val samplesDir = File(ctx.filesDir, "xike_agent_samples")
    val log = DecisionLog(File(ctx.filesDir, "xike_agent_log.jsonl"))

    fun load(): AgentSettings {
        val d = AgentSettings()
        return d.copy(
            geminiApiKey = p.getString("key", "") ?: "",
            geminiModel = p.getString("model", d.geminiModel) ?: d.geminiModel,
            ntfyServer = p.getString("ntfy_server", d.ntfyServer) ?: d.ntfyServer,
            ntfyTopic = p.getString("topic", "") ?: "",
            secret = p.getString("secret", "") ?: "",
            rulesText = p.getString("rules", d.rulesText) ?: d.rulesText,
            blockStartHour = p.getInt("block_start", d.blockStartHour),
            blockEndHour = p.getInt("block_end", d.blockEndHour),
            minAllowConfidence = p.getInt("min_conf", d.minAllowConfidence)
        )
    }

    fun save(s: AgentSettings) {
        p.edit()
            .putString("key", s.geminiApiKey.trim())
            .putString("model", s.geminiModel.trim())
            .putString("ntfy_server", s.ntfyServer.trim())
            .putString("topic", s.ntfyTopic.trim())
            .putString("secret", s.secret.trim())
            .putString("rules", s.rulesText)
            .putInt("block_start", s.blockStartHour)
            .putInt("block_end", s.blockEndHour)
            .putInt("min_conf", s.minAllowConfidence)
            .apply()
    }

    var lastId: String?
        get() = p.getString("last_id", null)
        set(v) { p.edit().putString("last_id", v).apply() }

    var lastSignal: String
        get() = p.getString("last_signal", "") ?: ""
        set(v) { p.edit().putString("last_signal", v).apply() }

    var hasOpenTrade: Boolean
        get() = p.getBoolean("open_trade", false)
        set(v) { p.edit().putBoolean("open_trade", v).apply() }

    fun addSample(jpeg: ByteArray, label: String, note: String) {
        samplesDir.mkdirs()
        val f = File(samplesDir, "s_" + System.currentTimeMillis() + ".jpg")
        f.writeBytes(jpeg)
        File(f.path + ".txt").writeText(label + "\n" + note)
    }

    // Mới nhất trước; agent chỉ gửi tối đa maxSamples ảnh.
    fun samples(): List<Sample> {
        val files = samplesDir.listFiles()?.filter { it.name.endsWith(".jpg") }?.sortedByDescending { it.name } ?: emptyList()
        return files.map { f ->
            val meta = File(f.path + ".txt")
            val lines = if (meta.exists()) meta.readLines() else emptyList()
            Sample(ImageData("image/jpeg", f.readBytes()), lines.getOrElse(0) { "?" }, lines.drop(1).joinToString(" "))
        }
    }

    fun sampleCount(): Int = samplesDir.listFiles()?.count { it.name.endsWith(".jpg") } ?: 0

    fun clearSamples() {
        samplesDir.listFiles()?.forEach { it.delete() }
    }
}

// ---------------- Ảnh: thu nhỏ + nén JPEG cho nhẹ ----------------
object ImageUtil {
    fun loadJpeg(ctx: Context, uri: Uri, maxSide: Int = 1600): ByteArray? {
        val src = ctx.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it) } ?: return null
        val scale = maxSide.toFloat() / maxOf(src.width, src.height)
        val bmp = if (scale < 1f) Bitmap.createScaledBitmap(src, (src.width * scale).toInt(), (src.height * scale).toInt(), true) else src
        val out = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, 85, out)
        return out.toByteArray()
    }
}

// ---------------- Thông báo ----------------
object AgentNotify {
    private const val CH = "xike_agent"

    fun show(ctx: Context, title: String, text: String) {
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(CH, "XI KE Agent", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(ctx, 0, Intent(ctx, AgentActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        @Suppress("DEPRECATION")
        val b = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(ctx, CH) else Notification.Builder(ctx)
        b.setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
        nm.notify((System.currentTimeMillis() % 100000).toInt(), b.build())
    }
}

// ---------------- Màn hình Agent ----------------
class AgentActivity : Activity() {
    private lateinit var store: AgentStore
    private val io = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private var watching = false
    private var pendingLabel = ""

    private lateinit var etKey: EditText
    private lateinit var etModel: EditText
    private lateinit var etTopic: EditText
    private lateinit var etSecret: EditText
    private lateinit var etBlock: EditText
    private lateinit var etConf: EditText
    private lateinit var etRules: EditText
    private lateinit var etNote: EditText
    private lateinit var tvOut: TextView

    private val tick = object : Runnable {
        override fun run() {
            if (!watching) return
            pollOnce()
            main.postDelayed(this, 20000L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = AgentStore(this)
        val s = store.load()
        val col = LinearLayout(this)
        col.orientation = LinearLayout.VERTICAL
        col.setPadding(32, 32, 32, 32)

        fun label(t: String) {
            val tv = TextView(this)
            tv.text = t
            col.addView(tv)
        }
        fun field(t: String, value: String, type: Int): EditText {
            label(t)
            val e = EditText(this)
            e.setText(value)
            e.inputType = type
            col.addView(e)
            return e
        }
        fun button(t: String, action: () -> Unit) {
            val b = Button(this)
            b.text = t
            b.setOnClickListener { action() }
            col.addView(b)
        }

        val text = InputType.TYPE_CLASS_TEXT
        label("XI KE AGENT: AI chỉ CHO PHÉP hoặc CHẶN tín hiệu từ chỉ báo của bạn. AI không tạo lệnh, không đổi lot/SL/TP.")
        etKey = field("Gemini API key", s.geminiApiKey, text or InputType.TYPE_TEXT_VARIATION_PASSWORD)
        etModel = field("Model Gemini", s.geminiModel, text)
        etTopic = field("Topic ntfy (chuỗi dài, khó đoán)", s.ntfyTopic, text)
        etSecret = field("Secret (giống trong Pine)", s.secret, text)
        etBlock = field("Giờ cấm (VD 18-22, 0-0 = tắt)", "" + s.blockStartHour + "-" + s.blockEndHour, text)
        etConf = field("Độ tin cậy tối thiểu để cho phép (%)", "" + s.minAllowConfidence, InputType.TYPE_CLASS_NUMBER)
        etRules = field("Quy tắc của bạn (AI đọc mỗi lần kiểm duyệt)", s.rulesText, text or InputType.TYPE_TEXT_FLAG_MULTI_LINE)
        etRules.minLines = 6

        val cb = CheckBox(this)
        cb.text = "Tôi đang có lệnh mở (chặn lệnh mới)"
        cb.isChecked = store.hasOpenTrade
        cb.setOnCheckedChangeListener { _, checked -> store.hasOpenTrade = checked }
        col.addView(cb)

        button("Lưu cài đặt") { saveSettings(); say("Đã lưu cài đặt") }
        button("Gửi tín hiệu thử (kiểm tra key Gemini)") { runTest() }
        button("Bắt đầu / Dừng theo dõi tín hiệu") { toggleWatch() }
        button("Kiểm tra tín hiệu ngay") { pollOnce() }
        button("Phân tích lại tín hiệu gần nhất + ảnh chart") { pickImage(REQ_CHART, "") }
        etNote = field("Ghi chú cho ảnh mẫu (VD: nến 3 chạm EMA34, MACD > 0.5)", "", text)
        button("Thêm ảnh mẫu: VÀO ĐÚNG") { pickImage(REQ_SAMPLE, "VÀO ĐÚNG") }
        button("Thêm ảnh mẫu: KHÔNG NÊN VÀO") { pickImage(REQ_SAMPLE, "KHÔNG NÊN VÀO") }
        button("Xoá tất cả ảnh mẫu") { io.execute { store.clearSamples(); say("Đã xoá ảnh mẫu") } }
        button("Xem nhật ký quyết định") { showLog() }

        tvOut = TextView(this)
        tvOut.setTextIsSelectable(true)
        col.addView(tvOut)

        val scroll = ScrollView(this)
        scroll.addView(col)
        setContentView(scroll)
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 7)
        say("Ảnh mẫu đã lưu: " + store.sampleCount())
    }

    override fun onDestroy() {
        watching = false
        main.removeCallbacks(tick)
        super.onDestroy()
    }

    private fun saveSettings() {
        val old = store.load()
        val hours = etBlock.text.toString().split("-").map { it.trim().toIntOrNull() }
        val start = hours.getOrNull(0) ?: old.blockStartHour
        val end = hours.getOrNull(1) ?: old.blockEndHour
        store.save(old.copy(
            geminiApiKey = etKey.text.toString(),
            geminiModel = etModel.text.toString().ifBlank { AgentSettings().geminiModel },
            ntfyTopic = etTopic.text.toString(),
            secret = etSecret.text.toString(),
            rulesText = etRules.text.toString(),
            blockStartHour = start.coerceIn(0, 23),
            blockEndHour = end.coerceIn(0, 23),
            minAllowConfidence = (etConf.text.toString().toIntOrNull() ?: old.minAllowConfidence).coerceIn(0, 100)
        ))
    }

    private fun toggleWatch() {
        saveSettings()
        watching = !watching
        main.removeCallbacks(tick)
        if (watching) main.post(tick)
        say(if (watching) "Đang theo dõi mỗi 20 giây (chỉ khi app đang mở)" else "Đã dừng theo dõi")
    }

    private fun pollOnce() {
        val st = store.load()
        if (st.ntfyTopic.isBlank()) { say("Chưa nhập topic ntfy"); return }
        io.execute {
            try {
                val msgs = NtfyFeed(st.ntfyServer, st.ntfyTopic).poll(store.lastId)
                val samples = if (msgs.isEmpty()) emptyList() else store.samples()
                for (m in msgs) {
                    store.lastId = m.id
                    val r = VetoAgent(st, store.log).handle(m.text, store.hasOpenTrade, null, samples)
                    if (r.duplicate) continue
                    if (r.signal != null) store.lastSignal = m.text
                    report(r, true)
                }
            } catch (e: Exception) {
                say("Lỗi lấy tín hiệu: " + (e.message ?: e.javaClass.simpleName))
            }
        }
    }

    private fun runTest() {
        saveSettings()
        val st = store.load()
        val now = System.currentTimeMillis()
        val raw = "{\"secret\":\"" + st.secret + "\",\"id\":\"TEST-" + now + "\",\"symbol\":\"XAUUSD\",\"tf\":\"30\",\"side\":\"BUY\",\"bar_time\":" + now +
            ",\"close\":2650.5,\"ema34\":2648.1,\"ema80\":2640.2,\"macd\":1.2,\"macd_signal\":0.8,\"vol\":1500,\"vol_ma\":1200," +
            "\"bars\":[[2645,2652,2644,2650,1300,0.9],[2650,2653,2647,2648,1250,1.0],[2648,2651,2646,2650.5,1500,1.2]],\"note\":\"TIN HIEU THU\"}"
        say("Đang gửi tín hiệu thử...")
        io.execute {
            val r = VetoAgent(st, store.log).handle(raw, store.hasOpenTrade, null, store.samples(), manual = true)
            report(r, false)
        }
    }

    private fun analyseWithChart(jpeg: ByteArray) {
        val raw = store.lastSignal
        if (raw.isBlank()) { say("Chưa có tín hiệu nào để phân tích lại"); return }
        val st = store.load()
        say("Đang phân tích tín hiệu gần nhất cùng ảnh chart...")
        val r = VetoAgent(st, store.log).handle(raw, store.hasOpenTrade, ImageData("image/jpeg", jpeg), store.samples(), manual = true)
        report(r, true)
    }

    private fun report(r: AgentResult, notify: Boolean) {
        val title = (if (r.decision.allow) "✅ CHO PHÉP " else "⛔ CHẶN ") + (r.signal?.side ?: "") + " " + (r.signal?.symbol ?: "")
        val body = r.decision.shortText() + "\nLot/SL/TP: theo quy tắc của bạn, AI không đổi."
        if (notify) AgentNotify.show(this, title, body)
        say(title + "\n" + body)
    }

    private fun showLog() {
        io.execute {
            val lines = store.log.recent(20).reversed().map { o ->
                val t = java.time.Instant.ofEpochMilli(o.optLong("ts")).atZone(java.time.ZoneId.of("Asia/Ho_Chi_Minh"))
                val hm = String.format("%02d/%02d %02d:%02d", t.dayOfMonth, t.monthValue, t.hour, t.minute)
                hm + " " + o.optString("side") + " " + (if (o.optBoolean("allow")) "CHO PHÉP" else "CHẶN") + " [" + o.optString("source") + "] " + o.optString("summary")
            }
            say("NHẬT KÝ 20 QUYẾT ĐỊNH GẦN NHẤT\n" + lines.joinToString("\n"))
        }
    }

    private fun pickImage(req: Int, labelText: String) {
        pendingLabel = labelText
        val i = Intent(Intent.ACTION_GET_CONTENT)
        i.type = "image/*"
        @Suppress("DEPRECATION")
        startActivityForResult(i, req)
    }

    @Deprecated("Activity API")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null) return
        val labelText = pendingLabel
        val note = etNote.text.toString()
        io.execute {
            val jpeg = try { ImageUtil.loadJpeg(this, uri) } catch (e: Exception) { null }
            if (jpeg == null) { say("Không đọc được ảnh"); return@execute }
            if (requestCode == REQ_SAMPLE) {
                store.addSample(jpeg, labelText, note)
                say("Đã thêm ảnh mẫu '" + labelText + "'. Tổng: " + store.sampleCount())
            }
            if (requestCode == REQ_CHART) analyseWithChart(jpeg)
        }
    }

    private fun say(msg: String) {
        main.post { tvOut.text = msg + "\n\n" + tvOut.text.toString().take(6000) }
    }

    companion object {
        const val REQ_CHART = 41
        const val REQ_SAMPLE = 42
    }
}
