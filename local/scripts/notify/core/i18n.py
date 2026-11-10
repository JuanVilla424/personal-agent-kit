_STRINGS: dict[str, dict[str, str]] = {
    "processing": {"es": "⏳ Procesando tu consulta…", "en": "⏳ Processing your query…"},
    "queue_position": {
        "es": "📋 Posición **#{pos}** en cola — aprox. **{eta} min** de espera.",
        "en": "📋 Position **#{pos}** in queue — approx. **{eta} min** wait.",
    },
    "timeout": {
        "es": "❌ **Timeout** — la consulta tardó más de {secs}s.\nIntenta una pregunta más específica o nombra un agente concreto.",
        "en": "❌ **Timeout** — query took more than {secs}s.\nTry a more specific question or name a concrete agent.",
    },
    "no_output": {"es": "❌ Sin respuesta del agente.", "en": "❌ No response from agent."},
    "error_internal": {"es": "❌ Error interno del bot.", "en": "❌ Internal bot error."},
    "cancelled": {"es": "❌ Consulta cancelada.", "en": "❌ Query cancelled."},
    "rate_limited": {
        "es": "⏱️ Límite de mensajes alcanzado. Inténtalo en un momento.",
        "en": "⏱️ Rate limit reached. Try again shortly.",
    },
    "quiet_hours": {
        "es": "🌙 Fuera de horario ({start}-{end}). Reintenta después.",
        "en": "🌙 Outside operating hours ({start}-{end}). Try again later.",
    },
    "permission_denied": {
        "es": "🚫 Sin permiso para esta acción.",
        "en": "🚫 No permission for this action.",
    },
    "content_blocked": {
        "es": "🚫 Mensaje bloqueado por filtro de contenido (regla: {rule}).",
        "en": "🚫 Message blocked by content filter (rule: {rule}).",
    },
    "queue_expired": {
        "es": "⏱️ Tu mensaje expiró en cola ({secs}s). Reenvíalo.",
        "en": "⏱️ Your message expired in queue ({secs}s). Resend it.",
    },
    "progress_thinking": {"es": "🤔 pensando", "en": "🤔 thinking"},
    "progress_tool": {"es": "🔧 `{tool}`", "en": "🔧 `{tool}`"},
    "cache_hit": {"es": "⚡ Respuesta desde caché.", "en": "⚡ Response from cache."},
    "session_reset": {"es": "🔄 Sesión del thread reseteada.", "en": "🔄 Thread session reset."},
    "cost_report": {
        "es": "💰 Tu costo este mes: **${cost:.4f} USD** ({queries} queries)",
        "en": "💰 Your cost this month: **${cost:.4f} USD** ({queries} queries)",
    },
    "status_report": {
        "es": "📊 **Estado del bot**\n• Pool: {pool_free}/{pool_size} libres\n• Threads activos: {threads}\n• Cola global: {queue}\n• Uptime: {uptime}",
        "en": "📊 **Bot status**\n• Pool: {pool_free}/{pool_size} free\n• Active threads: {threads}\n• Global queue: {queue}\n• Uptime: {uptime}",
    },
    "totp_prompt": {
        "es": "🔐 Esta acción requiere 2FA. Ingresa tu código TOTP:",
        "en": "🔐 This action requires 2FA. Enter your TOTP code:",
    },
    "totp_invalid": {"es": "❌ Código TOTP inválido.", "en": "❌ Invalid TOTP code."},
    "totp_ok": {
        "es": "✅ Código verificado. Continuando con permisos elevados.",
        "en": "✅ Code verified. Continuing with elevated permissions.",
    },
    "attachment_processing": {
        "es": "📎 Procesando adjunto: {name}…",
        "en": "📎 Processing attachment: {name}…",
    },
    "voice_joined": {
        "es": "🔊 Reproduciré la respuesta en voz.",
        "en": "🔊 I will play the response as voice.",
    },
    "no_session_flag": {"es": "(sin sesión — stateless)", "en": "(no session — stateless)"},
    "no_output_with_error": {
        "es": "❌ Sin respuesta.\n```\n{err}\n```",
        "en": "❌ No response.\n```\n{err}\n```",
    },
    "budget_exceeded": {
        "es": "⛔ Presupuesto mensual alcanzado (${spent:.2f} / ${cap:.2f}). Esperá al próximo mes o pedí una ampliación.",
        "en": "⛔ Monthly budget reached (${spent:.2f} / ${cap:.2f}). Wait until next month or request an increase.",
    },
}


def t(key: str, locale: str = "en", **kwargs: object) -> str:
    entry = _STRINGS.get(key, {})
    text = entry.get(locale, entry.get("en", key))
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text


def detect_locale(locale_hint: str | None = None) -> str:
    """Detect locale from an optional hint string. Defaults to English."""
    if locale_hint and locale_hint.startswith("es"):
        return "es"
    return "en"
