import streamlit as st
import pandas as pd
import logging

logger = logging.getLogger(__name__)


# ==========================================
# 📊 ЭФФЕКТИВНОСТЬ ТОРГОВЛИ
# ==========================================
def render_performance_tab(checked, wins, losses):
    """
    Отображает статистику эффективности торговых сигналов.
    Считает Win Rate, средний выигрыш/проигрыш и Profit Factor.
    """
    st.subheader("📊 Эффективность")
    
    # Нужно минимум 5 проверенных сигналов для статистики
    if len(checked) < 5:
        st.info(f"Мало данных: {len(checked)}. Нужно минимум 5 проверенных сигналов для отображения статистики.")
        return
    
    # Основные метрики
    wr = len(wins) / max(len(checked), 1) * 100  # Win Rate
    
    c1, c2, c3, c4 = st.columns(4)
    
    with c1: 
        # Win Rate - процент успешных сделок
        color = "green" if wr >= 50 else "red"
        st.markdown(f"**Win Rate**")
        st.markdown(f"<span style='color:{color}; font-size:30px;'>{wr:.1f}%</span>", unsafe_allow_html=True)
    
    with c2:
        # Средняя прибыль по выигрышным сделкам
        avg_win = sum(s.get('pnl_pct', 0) or 0 for s in wins) / max(len(wins), 1)
        st.metric("Ср. прибыль", f"{avg_win:+.2f}%")
    
    with c3:
        # Средний убыток по проигрышным сделкам
        avg_loss = sum(s.get('pnl_pct', 0) or 0 for s in losses) / max(len(losses), 1)
        st.metric("Ср. убыток", f"{avg_loss:+.2f}%")
    
    with c4:
        # Profit Factor - отношение всей прибыли ко всем убыткам
        tw = sum(s.get('pnl_pct', 0) or 0 for s in wins)  # Total Win
        tl = sum(s.get('pnl_pct', 0) or 0 for s in losses)  # Total Loss
        
        if abs(tl) < 0.01:
            # Если убытков почти нет
            pf = float('inf') if tw > 0 else 0
            st.metric("Profit Factor", "∞" if pf == float('inf') else f"{pf:.2f}")
        else:
            st.metric("Profit Factor", f"{abs(tw / tl):.2f}")
    
    st.markdown("---")
    
    # Графики
    df_checked = pd.DataFrame(checked)
    c1, c2 = st.columns(2)
    
    with c1:
        st.markdown("#### 📊 Распределение исходов")
        st.caption("Сколько сигналов закончились в плюс/минус/нейтрально")
        # Bar chart по количеству исходов
        outcome_counts = df_checked['outcome'].value_counts()
        st.bar_chart(outcome_counts)
    
    with c2:
        st.markdown("#### 💰 Распределение P&L")
        st.caption("Процент прибыли/убытка по каждой проверенной сделке")
        # Bar chart по P&L каждой сделки
        st.bar_chart(df_checked['pnl_pct'])
    
    st.markdown("---")
    
    # Пояснение метрик
    with st.expander("📖 Как читать эти метрики"):
        st.markdown("""
        **🏆 Win Rate (Процент побед)**
        - Показывает, сколько процентов сделок закончились в плюс
        - Хороший показатель: > 50%
        
        **💰 Средняя прибыль / убыток**
        - Показывает, сколько в среднем ты зарабатываешь на выигрышной сделке
        - И сколько теряешь на проигрышной
        
        **⚖️ Profit Factor (Коэффициент прибыли)**
        - Отношение всей заработанной прибыли ко всем понесённым убыткам
        - `PF = Сумма прибылей / Сумма убытков`
        - Хороший показатель: > 1.5
        - Отличный показатель: > 2.0
        
        **💡 Вывод:**
        Идеальная система имеет Win Rate ~40-60%, но при этом Profit Factor > 2.0.
        Это значит, что когда ты выигрываешь - ты выигрываешь МНОГО, а когда проигрываешь - ты проигрываешь МАЛО.
        """)
