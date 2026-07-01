import streamlit as st
import logging

logger = logging.getLogger(__name__)


# ==========================================
# 🎯 СИГНАЛЫ С УРОВНЯМИ
# ==========================================
def render_signals_tab(signals):
    """
    Отображает список последних торговых сигналов с подробной информацией.
    Каждый сигнал можно раскрыть, чтобы увидеть уровни входа и тейк-профитов.
    """
    st.subheader("🎯 Сигналы с уровнями")
    
    if not signals:
        st.info("Ожидание появления новых сигналов от радара...")
        return
    
    st.caption("Показаны последние 15 сигналов. Нажмите на заголовок, чтобы раскрыть детали.")
    
    for sig in signals[:15]:
        direction = sig.get('trade_direction', 'neutral')
        
        # Выбираем иконку в зависимости от направления
        if direction == 'long':
            de = "📈"
        elif direction == 'short':
            de = "📉"
        else:
            de = "⚖️"
            
        change = sig.get('change_pct', 0) or 0
        forecast = sig.get('forecast_score', 0) or 0
        
        # Используем expander для компактности списка
        with st.expander(f"{de} {sig.get('name', '')} | {change:+.2f}% | Прогноз: {forecast:.0f}%", expanded=False):
            
            # Метрики
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1: st.metric("Цена", f"{sig.get('price', 0):.2f}")
            with c2: st.metric("RSI", f"{sig.get('rsi', 0):.1f}")
            with c3: st.metric("ATR", f"{sig.get('atr', 0):.2f}")
            with c4: st.metric("Направление", direction.upper())
            with c5: st.metric("R:R", f"1:{sig.get('risk_reward', 0):.1f}")
            
            st.markdown("---")
            
            # Уровни торговли
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**🟦 Вход:** `{sig.get('entry_price', 0):.2f}`")
                st.markdown(f"**🟥 Стоп:** <span style='color:#ff4444;'>`{sig.get('stop_loss', 0):.2f}`</span>", unsafe_allow_html=True)
            with c2:
                st.markdown(f"**🟨 Цель 1:** `{sig.get('take_profit_1', 0):.2f}`")
                st.markdown(f"**🟩 Цель 2:** `{sig.get('take_profit_2', 0):.2f}`")
            
            st.markdown("---")
            st.caption(f"Сила сигнала: **{sig.get('signal_strength', 'medium')}** | Сектор: **{sig.get('sector', 'unknown')}** | Сентимент новостей: **{sig.get('news_sentiment', 0):.2f}**")
