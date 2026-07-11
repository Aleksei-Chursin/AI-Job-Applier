import gradio as gr

from src.webui.webui_manager import WebuiManager
from src.webui.components.job_applicator_tab import create_job_applicator_tab
from src.webui.components.setup_tab import create_setup_tab

_G  = "#EBC14E"
_GD = "#cda13d"
_BG = "#0F0F0F"
_S1 = "#141414"
_S2 = "#1c1c1c"
_BR = "#272727"
_TX = "#e2e2e2"
_TS = "#888888"

_GOLD_HUE = gr.themes.Color(
    c50="#fffbeb", c100="#fef3c7", c200="#fde68a", c300="#fcd34d",
    c400=_G,       c500=_GD,      c600="#b07d2a", c700="#8a6020",
    c800="#6b4a18", c900="#4f3610", c950="#342208",
)

theme_map = {
    "Legion": gr.themes.Soft(primary_hue=_GOLD_HUE).set(
        body_background_fill=_BG,           body_background_fill_dark=_BG,
        body_text_color=_TX,                body_text_color_dark=_TX,
        body_text_color_subdued=_TS,        body_text_color_subdued_dark=_TS,
        background_fill_primary=_S1,        background_fill_primary_dark=_S1,
        background_fill_secondary=_BG,      background_fill_secondary_dark=_BG,
        border_color_primary=_BR,           border_color_primary_dark=_BR,
        border_color_accent=_GD,            border_color_accent_dark=_GD,
        border_color_accent_subdued=_BR,    border_color_accent_subdued_dark=_BR,
        block_background_fill=_S1,          block_background_fill_dark=_S1,
        block_border_color=_BR,             block_border_color_dark=_BR,
        block_label_background_fill=_S1,    block_label_background_fill_dark=_S1,
        block_label_border_color=_BR,       block_label_border_color_dark=_BR,
        block_label_text_color=_GD,         block_label_text_color_dark=_GD,
        block_title_text_color=_TX,         block_title_text_color_dark=_TX,
        block_shadow="none",                block_shadow_dark="none",
        button_primary_background_fill=_G,  button_primary_background_fill_dark=_G,
        button_primary_background_fill_hover=_GD,
        button_primary_background_fill_hover_dark=_GD,
        button_primary_border_color=_G,     button_primary_border_color_dark=_G,
        button_primary_text_color=_BG,      button_primary_text_color_dark=_BG,
        button_primary_text_color_hover=_BG,button_primary_text_color_hover_dark=_BG,
        button_primary_shadow="none",       button_primary_shadow_dark="none",
        button_primary_shadow_hover=f"0 0 14px {_G}40",
        button_primary_shadow_hover_dark=f"0 0 14px {_G}40",
        button_secondary_background_fill="transparent",
        button_secondary_background_fill_dark="transparent",
        button_secondary_background_fill_hover=f"{_GD}18",
        button_secondary_background_fill_hover_dark=f"{_GD}18",
        button_secondary_border_color=_GD,  button_secondary_border_color_dark=_GD,
        button_secondary_border_color_hover=_G,
        button_secondary_border_color_hover_dark=_G,
        button_secondary_text_color=_G,     button_secondary_text_color_dark=_G,
        button_secondary_text_color_hover=_G,
        button_secondary_text_color_hover_dark=_G,
        button_secondary_shadow="none",     button_secondary_shadow_dark="none",
        button_cancel_background_fill="transparent",
        button_cancel_background_fill_dark="transparent",
        button_cancel_background_fill_hover="#dc262615",
        button_cancel_background_fill_hover_dark="#dc262615",
        button_cancel_border_color="#dc2626",
        button_cancel_border_color_dark="#dc2626",
        button_cancel_text_color="#dc2626",
        button_cancel_text_color_dark="#dc2626",
        input_background_fill=_S2,          input_background_fill_dark=_S2,
        input_background_fill_focus=_S2,    input_background_fill_focus_dark=_S2,
        input_border_color=_BR,             input_border_color_dark=_BR,
        input_border_color_focus=_G,        input_border_color_focus_dark=_G,
        input_border_color_hover=_GD,       input_border_color_hover_dark=_GD,
        input_placeholder_color="#444444",  input_placeholder_color_dark="#444444",
        input_shadow="none",                input_shadow_dark="none",
        input_shadow_focus=f"0 0 0 3px {_G}22",
        input_shadow_focus_dark=f"0 0 0 3px {_G}22",
        panel_background_fill=_S1,          panel_background_fill_dark=_S1,
        panel_border_color=_BR,             panel_border_color_dark=_BR,
        table_border_color=_BR,             table_border_color_dark=_BR,
        table_even_background_fill=_S1,     table_even_background_fill_dark=_S1,
        table_odd_background_fill=_S2,      table_odd_background_fill_dark=_S2,
        checkbox_background_color=_S2,      checkbox_background_color_dark=_S2,
        checkbox_border_color=_BR,          checkbox_border_color_dark=_BR,
        checkbox_border_color_focus=_G,     checkbox_border_color_focus_dark=_G,
        checkbox_label_background_fill=_S1, checkbox_label_background_fill_dark=_S1,
        slider_color=_G,                    slider_color_dark=_G,
        error_background_fill="#1a0808",    error_background_fill_dark="#1a0808",
        error_border_color="#dc2626",       error_border_color_dark="#dc2626",
        error_text_color="#ef4444",         error_text_color_dark="#ef4444",
    ),
    "Default":    gr.themes.Default(),
    "Soft":       gr.themes.Soft(),
    "Monochrome": gr.themes.Monochrome(),
    "Ocean":      gr.themes.Ocean(),
}

_CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@700&family=Montserrat:wght@400;600;700&display=swap');

.gradio-container {{
    max-width: 1100px !important;
    margin: 0 auto !important;
}}

/* ── Legion header ────────────────────────────────────────────────────────── */
.legion-header {{
    padding: 24px 0 18px;
    border-bottom: 1px solid {_BR};
    margin-bottom: 4px;
}}
.legion-header-inner {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 32px;
    max-width: 1100px;
    margin: 0 auto;
    padding: 0 24px;
}}
.legion-brand {{
    display: flex;
    align-items: baseline;
    gap: 20px;
}}
.legion-header h1 {{
    font-family: 'Cinzel', serif;
    font-size: 1.8rem;
    font-weight: 700;
    color: {_G};
    letter-spacing: 0.25em;
    margin: 0;
    text-shadow: 0 2px 20px {_G}33;
}}
.legion-header p {{
    font-family: 'Montserrat', sans-serif;
    font-size: 0.6rem;
    font-weight: 600;
    letter-spacing: 0.4em;
    color: {_GD};
    margin: 0;
    text-transform: uppercase;
    white-space: nowrap;
}}
.legion-join-btn {{
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.75rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.08em !important;
    color: {_BG} !important;
    background: linear-gradient(135deg, {_GD}, {_G}) !important;
    border: none !important;
    border-radius: 4px !important;
    padding: 9px 20px !important;
    text-decoration: none !important;
    white-space: nowrap !important;
    flex-shrink: 0 !important;
    margin-left: auto !important;
    transition: opacity 0.18s ease !important;
    cursor: pointer !important;
}}
.legion-join-btn:hover {{
    opacity: 0.85 !important;
    text-decoration: none !important;
    color: {_BG} !important;
}}

/* ── Primary buttons ──────────────────────────────────────────────────────── */
button.primary {{
    background: {_G} !important;
    border-color: {_G} !important;
    color: {_BG} !important;
}}
button.primary:hover {{
    background: {_GD} !important;
    box-shadow: 0 0 14px {_G}50 !important;
}}

/* ── Secondary buttons ────────────────────────────────────────────────────── */
button.secondary {{
    background: transparent !important;
    border-color: {_GD} !important;
    color: {_G} !important;
}}
button.secondary:hover {{
    background: {_GD}18 !important;
    border-color: {_G} !important;
}}

/* ── Stop / Cancel button ─────────────────────────────────────────────────── */
button.stop, button.cancel {{
    background: transparent !important;
    border-color: #dc2626 !important;
    color: #dc2626 !important;
}}
button.stop:hover, button.cancel:hover {{
    background: #dc262618 !important;
}}

/* ── CSS variable overrides for dark mode (Gradio reads these for tabs) ───── */
:root, .dark {{
    --color-accent: {_G};
    --color-accent-soft: {_G}22;
    --primary-500: {_GD};
    --primary-600: {_G};
}}

/* ── Tab bar ──────────────────────────────────────────────────────────────── */
.tab-nav button,
.tabs > .tab-nav > button {{
    color: {_TS} !important;
    border-bottom: 2px solid transparent !important;
    border-top: none !important;
    border-left: none !important;
    border-right: none !important;
    border-radius: 0 !important;
    background: transparent !important;
}}
.tab-nav button:hover {{
    color: {_GD} !important;
    background: transparent !important;
}}
.tab-nav button.selected,
.tab-nav button[aria-selected="true"] {{
    color: {_G} !important;
    border-bottom: 2px solid {_G} !important;
    background: transparent !important;
}}

/* ── Links ────────────────────────────────────────────────────────────────── */
a, a:visited {{
    color: {_G} !important;
    text-decoration: none !important;
}}
a:hover {{
    color: {_GD} !important;
    text-decoration: underline !important;
}}

/* ── Labels — strip blue badge, force gold text ───────────────────────────── */
.label-wrap,
.label-wrap > label,
.block > .label-wrap {{
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    box-shadow: none !important;
}}
.label-wrap > span,
.label-wrap label > span,
.label-wrap > label > span,
label > span,
.block label span,
.block > label > span {{
    color: {_GD} !important;
    background: transparent !important;
    font-weight: 600 !important;
}}

/* ── Accordion headers ────────────────────────────────────────────────────── */
.accordion .label-wrap span,
details > summary span,
details summary span {{
    color: {_G} !important;
    background: transparent !important;
}}

/* ── Input focus ──────────────────────────────────────────────────────────── */
input:focus, textarea:focus {{
    border-color: {_G} !important;
    box-shadow: 0 0 0 3px {_G}22 !important;
}}

/* ── Scrollbars ───────────────────────────────────────────────────────────── */
::-webkit-scrollbar {{ width: 5px; height: 5px; }}
::-webkit-scrollbar-track {{ background: {_BG}; }}
::-webkit-scrollbar-thumb {{ background: {_GD}55; border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: {_G}; }}
"""

_JS = """
function refresh() {
    // Force dark mode
    const url = new URL(window.location);
    if (url.searchParams.get('__theme') !== 'dark') {
        url.searchParams.set('__theme', 'dark');
        window.location.href = url.href;
        return;
    }

    // Override tab colors after Gradio renders
    function fixTabs() {
        document.querySelectorAll('.tab-nav button, .tabs .tab-nav button').forEach(btn => {
            const selected = btn.classList.contains('selected') ||
                             btn.getAttribute('aria-selected') === 'true';
            btn.style.setProperty('color', selected ? '#EBC14E' : '#888888', 'important');
            btn.style.setProperty('border-bottom',
                selected ? '2px solid #EBC14E' : '2px solid transparent', 'important');
            btn.style.setProperty('background', 'transparent', 'important');
        });
    }

    // Run now and observe for future tab changes
    setTimeout(fixTabs, 300);
    const observer = new MutationObserver(fixTabs);
    setTimeout(() => {
        const nav = document.querySelector('.tab-nav');
        if (nav) observer.observe(nav, { attributes: true, subtree: true, attributeFilter: ['class', 'aria-selected'] });
    }, 500);
}
"""


def create_ui(theme_name: str = "Legion", ui_manager: WebuiManager = None) -> tuple:
    if ui_manager is None:
        ui_manager = WebuiManager()

    with gr.Blocks(
        title="The Legion — AI Job Applier",
        theme=theme_map.get(theme_name, theme_map["Legion"]),
        css=_CSS,
        js=_JS,
    ) as demo:

        gr.HTML("""
        <div class="legion-header">
            <div class="legion-header-inner">
                <div class="legion-brand">
                    <h1>THE LEGION</h1>
                    <p>Maximum Yield &nbsp;·&nbsp; Minimum Friction</p>
                </div>
                <a href="https://legionaries.circle.so/feed"
                   target="_blank"
                   class="legion-join-btn">
                    Join The Legion &rarr;
                </a>
            </div>
        </div>
        """)

        with gr.Tabs():
            with gr.TabItem("Setup"):
                create_setup_tab()

            with gr.TabItem("Job Applicator"):
                create_job_applicator_tab(ui_manager)

    return demo, ui_manager
