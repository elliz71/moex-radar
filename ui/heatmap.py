import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import logging

logger = logging.getLogger(__name__)


# ==========================================
# 🔥 ТЕПЛОВАЯ КАРТА КОРРЕЛЯЦИЙ
# ==========================================
def render_heatmap_correlation():
    """
    Отображает тепловую карту корреляции доходностей активов
    Показывает, какие активы движутся вместе, а какие - противоположно
    """
    from moex_api import fetch_moex_data_raw
    from config import CONFIG
    
    st.subheader("🔥 Корреляция доходностей активов")
    st.caption("Как активы движутся относительно друг друга (акции + сырьё + валюта)")
    
    with st.spinner("Загрузка данных..."):
        prices_data = {}
        assets_for_corr = {}
        assets_for_corr.update(CONFIG['CORE_ASSETS'])
        assets_for_corr.update(CONFIG['FUTURES'])
        dynamic_items = list(CONFIG.get('DYNAMIC_STOCKS', {}).items())[:10]
        for ticker, info in dynamic_items:
            assets_for_corr[ticker] = info
        
        for ticker, info in assets_for_corr.items():
            df = fetch_moex_data_raw(ticker, info['type'])
            if df is not None and len(df) > 20:
                try:
                    returns = df['close'].pct_change().dropna()
                    if len(returns) > 10:
                        prices_data[ticker] = returns
                except Exception:
                    continue
        
        if len(prices_data) < 3:
            st.warning("⚠️ Недостаточно данных для построения корреляции")
            return
        
        returns_df = pd.DataFrame(prices_data)
        corr_matrix = returns_df.corr()
    
    # Рисуем тепловую карту
    with plt.style.context('dark_background'):
        fig, ax = plt.subplots(figsize=(12, 10))
        fig.patch.set_facecolor('#0e1117')
        ax.set_facecolor('#0e1117')
        
        im = ax.imshow(corr_matrix.values, cmap='RdYlGn', aspect='auto', vmin=-1, vmax=1)
        
        ax.set_xticks(range(len(corr_matrix.columns)))
        ax.set_yticks(range(len(corr_matrix.columns)))
        ax.set_xticklabels(corr_matrix.columns, rotation=45, ha='right', color='white', fontsize=9)
        ax.set_yticklabels(corr_matrix.columns, color='white', fontsize=9)
        
        # Добавляем числа в ячейки
        for i in range(len(corr_matrix)):
            for j in range(len(corr_matrix)):
                val = corr_matrix.values[i, j]
                color = 'white' if abs(val) < 0.5 else 'black'
                ax.text(j, i, f'{val:.2f}', ha="center", va="center",
                       color=color, fontsize=8, fontweight='bold')
        
        plt.colorbar(im, label='Корреляция', ax=ax)
        ax.set_title('Корреляция доходностей', color='white', fontsize=14, pad=20)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    
    # Легенда
    st.markdown("### 📖 Как читать")
    c1, c2, c3 = st.columns(3)
    with c1: st.success("🟢 **Зелёный (>0.5)**\nДвижутся вместе")
    with c2: st.error("🔴 **Красный (<-0.3)**\nПротивоположно")
    with c3: st.info("⚪ **Белый (~0)**\nНет связи")
    
    # Находим самые сильные связи
    pairs = []
    for i in range(len(corr_matrix)):
        for j in range(i+1, len(corr_matrix)):
            pairs.append({
                'pair': f"{corr_matrix.columns[i]} ↔ {corr_matrix.columns[j]}",
                'correlation': corr_matrix.values[i, j]
            })
    pairs.sort(key=lambda x: abs(x['correlation']), reverse=True)
    
    st.markdown("### 🔗 Топ связей")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🟢 Сильнейшая положительная:**")
        for p in pairs[:5]:
            if p['correlation'] > 0:
                st.markdown(f"- `{p['pair']}`: **{p['correlation']:+.2f}**")
    with c2:
        st.markdown("**🔴 Сильнейшая отрицательная:**")
        for p in reversed(pairs[-5:]):
            if p['correlation'] < 0:
                st.markdown(f"- `{p['pair']}`: **{p['correlation']:+.2f}**")
    
    st.info("💡 **Совет:** Для диверсификации выбирайте активы с корреляцией < 0.3")
