// =====================================================================
// XI KE AGENT - LÕI (thuần Kotlin, không phụ thuộc giao diện)
// Dùng trong app "Nhật Ký XAUUSD".
//
// Luồng: Chỉ báo TradingView -> alert JSON -> ntfy.sh -> app
//        -> LUẬT CỨNG -> Gemini VETO -> thông báo + nhật ký
//
// Nguyên tắc cố định:
// 1. Tín hiệu do chỉ báo của bạn tạo ra. AI chỉ được CHO PHÉP hoặc CHẶN.
// 2. AI không bao giờ nhận hay trả lot, SL, TP; không đổi hướng lệnh.
// 3. Luật cứng chạy trước, không tốn lời gọi AI.
// 4. Mọi lỗi (mất mạng, timeout, JSON sai, thiếu số liệu) = CHẶN.
// Yêu cầu Android minSdk 26 (java.time, java.util.Base64).
// =====================================================================
package xike.agent

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.time.Instant
import java.time.ZoneId
import java.util.Base64

// ---------------- Cài đặt ----------------
data class AgentSettings(
    val geminiApiKey: String = "",
    val geminiModel: String = "gemini-3.8-flash",
    val geminiBaseUrl: String = "https://generativelanguage.googleapis.com",
    val ntfyServer: String = "https://ntfy.sh",
    val ntfyTopic: String = "",
    val secret: String = "",
    val rulesText: String = DEFAULT_RULES,
    val blockStartHour: Int = 18,
    val blockEndHour: Int = 22,
    val timeZone: String = "Asia/Ho_Chi_Minh",
    val maxSignalAgeSec: Long = 180,
    val maxManualAgeSec: Long = 900,
    val maxOneOpenTrade: Boolean = true,
    val minAllowConfidence: Int = 60,
    val httpTimeoutMs: Int = 30000,
    val maxSamples: Int = 4
)

// ---------------- Dữ liệu tín hiệu ----------------
data class Bar(val o: Double, val h: Double, val l: Double, val c: Double, val v: Double, val macd: Double)

data class Signal(
    val id: String,
    val secret: String,
    val symbol: String,
    val tf: String,
    val side: String,
    val barTimeMs: Long,
    val close: Double,
    val ema34: Double,
    val ema80: Double,
    val macd: Double,
    val macdSignal: Double,
    val volume: Double,
    val volumeMa: Double,
    val bars: List<Bar>,
    val note: String
) {
    // Dữ liệu gửi cho AI: KHÔNG có secret, lot, SL, TP.
    fun toAiJson(): JSONObject {
        val arr = JSONArray()
        bars.forEach { b ->
            arr.put(JSONObject().put("open", b.o).put("high", b.h).put("low", b.l)
                .put("close", b.c).put("volume", b.v).put("macd", b.macd))
        }
        return JSONObject()
            .put("symbol", symbol).put("timeframe", tf).put("side", side)
            .put("bar_close_time_utc", Instant.ofEpochMilli(barTimeMs).toString())
            .put("close", close).put("ema34", ema34).put("ema80", ema80)
            .put("macd", macd).put("macd_signal", macdSignal)
            .put("volume", volume).put("volume_ma20", volumeMa)
            .put("bars_oldest_to_newest", arr)
            .put("indicator_note", note)
    }

    companion object {
        fun parse(text: String): Signal? = try {
            val o = JSONObject(text.trim())
            val bars = mutableListOf<Bar>()
            val arr = o.optJSONArray("bars")
            if (arr != null) {
                for (i in 0 until arr.length()) {
                    val b = arr.optJSONArray(i) ?: continue
                    bars.add(Bar(b.optDouble(0), b.optDouble(1), b.optDouble(2), b.optDouble(3), b.optDouble(4), b.optDouble(5)))
                }
            }
            Signal(
                id = o.optString("id"),
                secret = o.optString("secret"),
                symbol = o.optString("symbol"),
                tf = o.optString("tf"),
                side = o.optString("side").trim().uppercase(),
                barTimeMs = o.optLong("bar_time", 0L),
                close = o.optDouble("close"),
                ema34 = o.optDouble("ema34"),
                ema80 = o.optDouble("ema80"),
                macd = o.optDouble("macd"),
                macdSignal = o.optDouble("macd_signal"),
                volume = o.optDouble("vol"),
                volumeMa = o.optDouble("vol_ma"),
                bars = bars,
                note = o.optString("note")
            )
        } catch (e: Exception) {
            null
        }
    }
}

data class ImageData(val mime: String, val bytes: ByteArray)

// Ảnh mẫu để "dạy" AI: nhãn VÀO ĐÚNG / KHÔNG NÊN VÀO + ghi chú của bạn.
data class Sample(val image: ImageData, val label: String, val note: String)

enum class Source { HARD_RULE, AI, ERROR }

data class Decision(
    val allow: Boolean,
    val source: Source,
    val confidence: Int,
    val reasons: List<String>,
    val violated: List<String>,
    val summary: String
) {
    fun shortText(): String {
        val head = if (allow) "CHO PHÉP" else "CHẶN"
        val by = if (source == Source.AI) "AI" else if (source == Source.HARD_RULE) "Luật cứng" else "Lỗi hệ thống"
        val lines = (violated + reasons).distinct().take(4).joinToString("\n") { "- $it" }
        return "$head ($by, tin cậy $confidence%)\n$summary\n$lines".trim()
    }

    companion object {
        fun veto(source: Source, reason: String): Decision =
            Decision(false, source, 100, listOf(reason), emptyList(), reason)
    }
}

data class AgentResult(val signal: Signal?, val decision: Decision, val duplicate: Boolean)

// ---------------- HTTP ----------------
fun interface HttpClient {
    fun request(method: String, url: String, headers: Map<String, String>, body: String?, timeoutMs: Int): Pair<Int, String>
}

object UrlHttp : HttpClient {
    override fun request(method: String, url: String, headers: Map<String, String>, body: String?, timeoutMs: Int): Pair<Int, String> {
        val c = URL(url).openConnection() as HttpURLConnection
        try {
            c.requestMethod = method
            c.connectTimeout = timeoutMs
            c.readTimeout = timeoutMs
            headers.forEach { (k, v) -> c.setRequestProperty(k, v) }
            if (body != null) {
                c.doOutput = true
                c.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val code = c.responseCode
            val stream = if (code in 200..299) c.inputStream else c.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            return code to text
        } finally {
            c.disconnect()
        }
    }
}

// ---------------- Luật cứng (không dùng AI) ----------------
object HardRules {
    fun check(s: Signal, st: AgentSettings, nowMs: Long, hasOpenTrade: Boolean, maxAgeSec: Long): List<String> {
        val v = mutableListOf<String>()
        if (st.secret.isBlank()) v.add("Chưa đặt secret trong app")
        if (st.secret.isNotBlank() && s.secret != st.secret) v.add("Sai secret: tín hiệu không đến từ chỉ báo của bạn")
        if (s.id.isBlank()) v.add("Tín hiệu thiếu id")
        if (s.side != "BUY" && s.side != "SELL") v.add("Hướng lệnh không hợp lệ: '${s.side}'")
        val nums = listOf("close" to s.close, "ema34" to s.ema34, "ema80" to s.ema80, "macd" to s.macd, "volume" to s.volume)
        nums.filter { !it.second.isFinite() }.forEach { v.add("Thiếu số liệu ${it.first}") }
        if (s.bars.any { b -> listOf(b.o, b.h, b.l, b.c).any { !it.isFinite() } }) v.add("Dữ liệu nến bị thiếu")
        val ageSec = (nowMs - s.barTimeMs) / 1000
        if (s.barTimeMs <= 0L) v.add("Thiếu thời gian nến")
        if (s.barTimeMs > 0L && ageSec > maxAgeSec) v.add("Tín hiệu cũ ${ageSec}s (tối đa ${maxAgeSec}s)")
        if (s.barTimeMs > 0L && ageSec < -120) v.add("Thời gian nến ở tương lai, kiểm tra đồng hồ điện thoại")
        if (inBlockedHours(nowMs, st)) v.add("Giờ cấm vào lệnh ${st.blockStartHour}:00-${st.blockEndHour}:00")
        if (st.maxOneOpenTrade && hasOpenTrade) v.add("Đang có lệnh mở, tối đa 1 lệnh")
        return v
    }

    fun inBlockedHours(ms: Long, st: AgentSettings): Boolean {
        if (st.blockStartHour == st.blockEndHour) return false
        val h = Instant.ofEpochMilli(ms).atZone(ZoneId.of(st.timeZone)).hour
        return if (st.blockStartHour < st.blockEndHour) h >= st.blockStartHour && h < st.blockEndHour
        else h >= st.blockStartHour || h < st.blockEndHour
    }
}

// ---------------- Gemini VETO ----------------
class GeminiVeto(private val st: AgentSettings, private val http: HttpClient = UrlHttp) {

    fun buildRequest(s: Signal, chart: ImageData?, samples: List<Sample>): JSONObject {
        val parts = JSONArray()
        parts.put(text("QUY TẮC CỦA TÔI:\n" + st.rulesText))
        if (samples.isNotEmpty()) {
            parts.put(text("ẢNH MẪU ĐỂ HỌC (không phải biểu đồ hiện tại):"))
            samples.forEachIndexed { i, sm ->
                parts.put(text("Mẫu ${i + 1} - nhãn: ${sm.label}. Ghi chú: ${sm.note}"))
                parts.put(image(sm.image))
            }
        }
        parts.put(text("TÍN HIỆU CẦN KIỂM DUYỆT (số liệu chỉ báo TradingView, nến cuối là nến vừa đóng):\n" + s.toAiJson().toString()))
        if (chart != null) {
            parts.put(text("ẢNH BIỂU ĐỒ HIỆN TẠI:"))
            parts.put(image(chart))
        }
        parts.put(text("Chỉ trả về đúng một object JSON theo mẫu, không viết gì thêm."))
        return JSONObject()
            .put("systemInstruction", JSONObject().put("parts", JSONArray().put(text(SYSTEM_PROMPT))))
            .put("contents", JSONArray().put(JSONObject().put("role", "user").put("parts", parts)))
    }

    fun decide(s: Signal, chart: ImageData?, samples: List<Sample>): Decision {
        if (st.geminiApiKey.isBlank()) return Decision.veto(Source.ERROR, "Chưa nhập Gemini API key")
        return try {
            val url = st.geminiBaseUrl.trimEnd('/') + "/v1beta/models/" + st.geminiModel.trim() + ":generateContent"
            val headers = mapOf("Content-Type" to "application/json", "x-goog-api-key" to st.geminiApiKey.trim())
            val (code, body) = http.request("POST", url, headers, buildRequest(s, chart, samples).toString(), st.httpTimeoutMs)
            if (code !in 200..299) Decision.veto(Source.ERROR, "Gemini lỗi HTTP $code: " + body.take(160))
            else parseResponse(body, st.minAllowConfidence)
        } catch (e: Exception) {
            Decision.veto(Source.ERROR, "Không gọi được Gemini: " + (e.message ?: e.javaClass.simpleName))
        }
    }

    private fun text(t: String) = JSONObject().put("text", t)

    private fun image(img: ImageData) = JSONObject().put("inlineData",
        JSONObject().put("mimeType", img.mime).put("data", Base64.getEncoder().encodeToString(img.bytes)))

    companion object {
        val SYSTEM_PROMPT = """
Bạn là lớp KIỂM DUYỆT (veto) cho tín hiệu vàng XAUUSD do chỉ báo của trader tạo ra.
Quyền của bạn chỉ có: ALLOW (cho phép) hoặc VETO (chặn).
Bạn KHÔNG tạo lệnh mới, KHÔNG đổi hướng lệnh, KHÔNG đề xuất hay sửa lot, SL, TP.
Chỉ đánh giá theo QUY TẮC CỦA TÔI, số liệu tín hiệu và ảnh (nếu có).
Ảnh mẫu chỉ để học cách trader nhìn biểu đồ, không phải dữ liệu hiện tại.
VETO khi tín hiệu vi phạm quy tắc, khi ảnh/số liệu mâu thuẫn với quy tắc, hoặc khi thiếu dữ liệu để kết luận.
Không bịa số liệu không có trong dữ liệu.
Trả về đúng một object JSON:
{"decision":"ALLOW hoặc VETO","confidence":0-100,"violated_rules":["quy tắc bị vi phạm"],"reasons":["lý do ngắn"],"summary_vi":"một câu tóm tắt tiếng Việt"}
""".trim()

        // Mọi câu trả lời không hợp lệ đều thành CHẶN.
        fun parseResponse(body: String, minConfidence: Int): Decision {
            val root = try { JSONObject(body) } catch (e: Exception) { return Decision.veto(Source.ERROR, "Phản hồi Gemini không phải JSON") }
            val cands = root.optJSONArray("candidates")
            if (cands == null || cands.length() == 0) {
                val block = root.optJSONObject("promptFeedback")?.optString("blockReason") ?: ""
                return Decision.veto(Source.ERROR, "Gemini không trả kết quả " + block)
            }
            val parts = cands.optJSONObject(0)?.optJSONObject("content")?.optJSONArray("parts")
            val sb = StringBuilder()
            if (parts != null) {
                for (i in 0 until parts.length()) {
                    val p = parts.optJSONObject(i) ?: continue
                    if (!p.optBoolean("thought")) sb.append(p.optString("text"))
                }
            }
            val answer = extractJsonObject(sb.toString()) ?: return Decision.veto(Source.ERROR, "AI trả lời sai định dạng")
            val decision = answer.optString("decision").trim().uppercase()
            if (decision != "ALLOW" && decision != "VETO") return Decision.veto(Source.ERROR, "AI trả quyết định lạ: '$decision'")
            val conf = answer.optInt("confidence", 0).coerceIn(0, 100)
            val reasons = strings(answer.optJSONArray("reasons")).toMutableList()
            val violated = strings(answer.optJSONArray("violated_rules"))
            val summary = answer.optString("summary_vi").take(300)
            var allow = decision == "ALLOW"
            if (allow && conf < minConfidence) {
                allow = false
                reasons.add("AI cho phép nhưng độ tin cậy $conf% < $minConfidence% nên chặn")
            }
            return Decision(allow, Source.AI, conf, reasons, violated, summary)
        }

        fun extractJsonObject(t: String): JSONObject? {
            val a = t.indexOf('{')
            val b = t.lastIndexOf('}')
            if (a < 0 || b <= a) return null
            return try { JSONObject(t.substring(a, b + 1)) } catch (e: Exception) { null }
        }

        private fun strings(a: JSONArray?): List<String> {
            if (a == null) return emptyList()
            val out = mutableListOf<String>()
            for (i in 0 until a.length()) {
                val s = a.optString(i).trim()
                if (s.isNotEmpty()) out.add(s.take(200))
            }
            return out.take(6)
        }
    }
}

// ---------------- Nhận tín hiệu từ ntfy.sh ----------------
data class FeedMessage(val id: String, val time: Long, val text: String)

class NtfyFeed(private val server: String, private val topic: String, private val http: HttpClient = UrlHttp) {
    fun poll(sinceId: String?): List<FeedMessage> {
        val since = if (sinceId.isNullOrBlank()) "5m" else sinceId
        val url = server.trimEnd('/') + "/" + URLEncoder.encode(topic.trim(), "UTF-8") +
            "/json?poll=1&since=" + URLEncoder.encode(since, "UTF-8")
        val (code, body) = http.request("GET", url, emptyMap(), null, 15000)
        if (code !in 200..299) throw IOException("ntfy HTTP $code")
        return body.lineSequence().map { it.trim() }.filter { it.startsWith("{") }.mapNotNull { line ->
            try {
                val o = JSONObject(line)
                if (o.optString("event") == "message") FeedMessage(o.optString("id"), o.optLong("time"), o.optString("message")) else null
            } catch (e: Exception) {
                null
            }
        }.toList()
    }
}

// ---------------- Nhật ký quyết định (để đo AI có giúp không) ----------------
class DecisionLog(private val file: File) {
    @Synchronized
    fun append(s: Signal?, raw: String, d: Decision, nowMs: Long, manual: Boolean) {
        val o = JSONObject()
            .put("ts", nowMs)
            .put("id", s?.id ?: "")
            .put("side", s?.side ?: "")
            .put("close", if (s != null && s.close.isFinite()) s.close else 0.0)
            .put("allow", d.allow)
            .put("source", d.source.name)
            .put("confidence", d.confidence)
            .put("manual", manual)
            .put("summary", d.summary)
            .put("reasons", JSONArray(d.reasons))
            .put("violated", JSONArray(d.violated))
        if (s == null) o.put("raw", raw.take(500))
        file.parentFile?.mkdirs()
        file.appendText(o.toString() + "\n")
    }

    @Synchronized
    fun recent(n: Int): List<JSONObject> {
        if (!file.exists()) return emptyList()
        return file.readLines().takeLast(n).mapNotNull { try { JSONObject(it) } catch (e: Exception) { null } }
    }

    fun seen(id: String): Boolean = id.isNotBlank() && recent(300).any { it.optString("id") == id && !it.optBoolean("manual") }
}

// ---------------- Agent điều phối ----------------
class VetoAgent(
    private val st: AgentSettings,
    private val log: DecisionLog,
    private val http: HttpClient = UrlHttp,
    private val clock: () -> Long = { System.currentTimeMillis() }
) {
    // manual = true: bạn bấm "Phân tích lại + ảnh chart" (cho phép tín hiệu cũ hơn, không chống trùng).
    fun handle(raw: String, hasOpenTrade: Boolean, chart: ImageData?, samples: List<Sample>, manual: Boolean = false): AgentResult {
        val now = clock()
        val s = Signal.parse(raw)
        if (s == null) {
            val d = Decision.veto(Source.ERROR, "Không đọc được tín hiệu (không phải JSON hợp lệ)")
            log.append(null, raw, d, now, manual)
            return AgentResult(null, d, false)
        }
        if (!manual && log.seen(s.id)) return AgentResult(s, Decision.veto(Source.HARD_RULE, "Tín hiệu trùng, đã xử lý"), true)
        val maxAge = if (manual) st.maxManualAgeSec else st.maxSignalAgeSec
        val hard = HardRules.check(s, st, now, hasOpenTrade, maxAge)
        val d = if (hard.isNotEmpty()) Decision(false, Source.HARD_RULE, 100, emptyList(), hard, "Chặn bởi luật cứng")
        else GeminiVeto(st, http).decide(s, chart, samples.take(st.maxSamples))
        log.append(s, raw, d, now, manual)
        return AgentResult(s, d, false)
    }
}

// Mẫu quy tắc mặc định - SỬA trong app cho đúng chỉ báo của bạn.
val DEFAULT_RULES = """
(VÍ DỤ - xoá và dán quy tắc chỉ báo thật trong app Nhật Ký XAUUSD vào đây. Mỗi quy tắc một dòng, rõ ràng, có số cụ thể.)
1. Chỉ kiểm duyệt XAUUSD.
2. Không vào lệnh 18:00-22:00 giờ Việt Nam (app đã chặn cứng).
3. BUY chỉ hợp lệ khi EMA34 nằm trên EMA80; SELL khi EMA34 nằm dưới EMA80.
4. Chặn khi nến vừa đóng là nến đảo chiều mạnh ngược hướng lệnh.
5. Chặn khi volume không ủng hộ hướng lệnh so với các nến gần nhất.
""".trim()
