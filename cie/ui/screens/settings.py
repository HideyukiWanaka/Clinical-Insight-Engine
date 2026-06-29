"""CIE Platform — Settings Screen.

Renders the API key configuration UI. This module is presentation-only:
it reads state from its arguments, renders Streamlit widgets, and returns
an event dict describing the user's action. All state mutations occur in
``app.py``'s ``_handle_settings()`` handler.

Security invariants enforced here:
- API key values are NEVER written to ``st.session_state``.
- The key value appears only in the returned event dict and is consumed
  immediately by the caller.
- Only a boolean key-presence flag is displayed (never the key itself).
"""

from __future__ import annotations

import streamlit as st

_PROVIDERS: dict[str, str] = {
    "anthropic":     "Anthropic (Claude)",
    "openai":        "OpenAI (GPT)",
    "google_gemini": "Google Gemini",
}

_PROVIDER_KEYS = list(_PROVIDERS.keys())
_PROVIDER_LABELS = list(_PROVIDERS.values())


def render_settings(
    current_provider: str,
    provider_key_status: dict[str, bool],
) -> dict | None:
    """Render the Settings screen and return a single action event or None.

    Args:
        current_provider: The currently active LLM provider identifier
            (``"anthropic"``, ``"openai"``, or ``"google_gemini"``).
        provider_key_status: Mapping of provider → ``has_key`` boolean.
            Only presence information, never key values.

    Returns:
        One of the following dicts, or ``None`` if no action was taken:

        - ``{"action": "save_key",       "provider": str, "api_key": str}``
        - ``{"action": "clear_key",      "provider": str}``
        - ``{"action": "change_provider","provider": str}``
    """
    st.title("設定")
    st.caption("AIプロバイダーとAPIキーを管理します。")

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------
    st.subheader("AIプロバイダー")

    current_index = _PROVIDER_KEYS.index(current_provider) if current_provider in _PROVIDER_KEYS else 0
    selected_label = st.radio(
        "使用するプロバイダー",
        options=_PROVIDER_LABELS,
        index=current_index,
        key="settings_provider_radio",
        horizontal=True,
    )
    selected_provider = _PROVIDER_KEYS[_PROVIDER_LABELS.index(selected_label)]

    if selected_provider != current_provider:
        return {"action": "change_provider", "provider": selected_provider}

    st.divider()

    # ------------------------------------------------------------------
    # API key management
    # ------------------------------------------------------------------
    st.subheader("APIキー設定")

    provider_label = _PROVIDERS.get(current_provider, current_provider)
    st.markdown(f"**{provider_label}** のAPIキー")

    has_key = provider_key_status.get(current_provider, False)
    if has_key:
        st.success("✓ 設定済み")
    else:
        st.warning("未設定 — このプロバイダーを使用するにはAPIキーを入力してください。")

    key_input = st.text_input(
        "APIキーを入力",
        type="password",
        placeholder="APIキーをここに貼り付けてください...",
        key="settings_api_key_input",
        help="入力した値は即座にOSキーチェーンに保存され、画面上には表示されません。",
    )

    col_save, col_clear, _ = st.columns([1, 1, 3])

    with col_save:
        save_clicked = st.button(
            "保存",
            disabled=not bool(key_input),
            use_container_width=True,
            key="settings_save_btn",
        )

    with col_clear:
        if has_key:
            clear_clicked = st.button(
                "削除",
                use_container_width=True,
                key="settings_clear_btn",
                type="secondary",
            )
        else:
            clear_clicked = False

    if save_clicked and key_input:
        return {"action": "save_key", "provider": current_provider, "api_key": key_input}

    if clear_clicked:
        return {"action": "clear_key", "provider": current_provider}

    return None
