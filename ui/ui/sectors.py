import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import logging

logger = logging.getLogger(__name__)


# ==========================================
# 📊 СРАВНЕНИЕ СЕКТОРОВ
# ==========================================
def render_sector_comparison():
    """
    Отображает сравнение секторов рынка по доходности
    Показывает, какие сектора сейчас сильны, а какие слабы
    """
    from moex_api import fetch_moex_data_raw
    from config import CONFIG, get_all_assets
    
    st.subheader("📊 Сравнение секторов рынка")
    st.caption("Относительная сила секторов за последние 100 минут")
    
    with st.spinner("Загрузка..."):
        sectors = {}
        for ticker, info in get_all_assets().items():
            if info['type'] != 'stock':
                continue
            sector = info.get('sector', 'other')
            if sector not in sectors:
                sectors[sector] = []
            sectors[sector].append(ticker)
        
        sector_performance = {}
        for sector, tickers in sectors.items():
            performances = []
            for ticker in tickers[:5]:  # Берём первые 5 акций из сектора
                df = fetch_moex_data_raw(ticker, 'stock')
                if df is not None and len(df) > 10:
                    try:
                        prev_price = df['close'].iloc[-10]
                        curr_price = df['close'].iloc[-1]
                        if prev_price > 0:
                            price_change = (curr_price - prev_price) / prev_price * 100
                            performances.append(price_change)
                    except Exception:
                        continue
            if performances:
                sector_performance[sector] = sum(performances) / len(performances)
    
    if not sector_performance:
        st.warning("⚠️ Недостаточно данных для анализа секторов")
        return
    
    # Рисуем горизонтальный бар-чарт
    with plt.style.context('dark_background'):
        fig, ax = plt.subplots(figsize=(10, 6))
        fig.patch.set_facecolor('#0e1117')
        ax.set_facecolor('#0e1117')
        
        sectors_list = list(sector_performance.keys())
        performance_list = list(sector_performance.values())
        colors = ['#26a69a' if p >= 0 else '#ef5350' for p in performance_list]
        
        bars = ax.barh(sectors_list, performance_list, color=colors, alpha=0.8)
        
        # Добавляем подписи к барам
        max_abs = max(abs(p) for p in performance_list) if performance_list else 1
        max_abs = max(max_abs, 0.1)
        text_offset = max_abs * 0.15
        ax.set_xlim(-max_abs - text_offset * 2, max_abs + text_offset * 2)
        
        for bar, perf in zip(bars, performance_list):
            width = bar.get_width()
            x_pos = width + text_offset if width >= 0 else width - text_offset
            ax.text(x_pos, bar.get_y() + bar.get_height()/2,
                   f'{perf:+.2f}%',
                   ha='left' if width >= 0 else 'right',
                   va='center', color='white', fontweight='bold')
        
        ax.axvline(x=0, color='white', linestyle='-', linewidth=1, alpha=0.5)
        ax.set_xlabel('Доходность (%)', color='white')
        ax.set_title('Сила секторов', color='white', fontsize=14, pad=20)
        ax.tick_params(colors='white')
        for spine in ['top', 'right']:
            ax.spines[spine].set_visible(False)
        ax.grid(True, axis='x', alpha=0.2, color='white')
        
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    
    # Анализ результатов
    best_sector = max(sector_performance.items(), key=lambda x: x[1])
    worst_sector = min(sector_performance.items(), key=lambda x: x[1])
    
    st.markdown("### 💡 Анализ")
    c1, c2 = st.columns(2)
    with c1:
        st.success(f"🏆 **Сильнейший:** {best_sector[0]}\n\n{best_sector[1]:+.2f}%")
    with c2:
        st.error(f"📉 **Слабейший:** {worst_sector[0]}\n\n{worst_sector[1]:+.2f}%")
