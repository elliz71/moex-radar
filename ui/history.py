import streamlit as st
import logging

logger = logging.getLogger(__name__)


# ==========================================
# 📜 ИСТОРИЯ СИГНАЛОВ
# ==========================================
def render_history_tab(signals):
    """
    Отображает полную историю всех торговых сигналов с фильтрацией.
    Позволяет отфильтровать по исходу (win/loss/neutral), тикеру и направлению.
    """
    st.subheader("📜 История")
    
    if not signals:
        st.info("История пуста. Радар ещё не нашёл ни одного сигнала.")
        return
    
    # Фильтры
    c1, c2, c3 = st.columns(3)
    
    with c1:
        # Фильтр по исходу
        fo = st.selectbox(
            "Исход", 
            ["Все", "win", "loss", "neutral", "pending", "partial_win", "partial_loss"], 
            key="h_out"
        )
    
    with c2:
        # Фильтр по тикеру
        tickers_list = list(set(s.get('ticker', '') for s in signals))
        ft = st.selectbox("Тикер", ["Все"] + tickers_list, key="h_tick")
    
    with c3:
        # Фильтр по направлению
        fd = st.selectbox(
            "Направление", 
            ["Все", "long", "short", "neutral"], 
            key="h_dir"
        )
    
    # Применяем фильтры
    filtered = signals
    
    if fo != "Все":
        filtered = [s for s in filtered if s.get('outcome') == fo]
    
    if ft != "Все":
        filtered = [s for s in filtered if s.get('ticker') == ft]
    
    if fd != "Все":
        filtered = [s for s in filtered if s.get('trade_direction') == fd]
    
    st.markdown(f"**Найдено:** {len(filtered)} сигналов")
    st.markdown("---")
    
    # Отображаем отфильтрованные сигналы
    for sig in filtered[:30]:  # Показываем максимум 30 последних
        outcome = sig.get('outcome', 'pending')
        
        # Выбираем эмодзи в зависимости от исхода
        if outcome == 'win':
            em = "✅"
        elif outcome == 'loss':
            em = "❌"
        elif outcome == 'partial_win':
            em = "🟡"
        elif outcome == 'partial_loss':
            em = "🟠"
        else:
            em = "⏳"
        
        # CSS класс для цветной подсветки
        cls = f"outcome-{outcome}" if outcome in ['win', 'loss'] else ""
        
        st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
        
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        
        with c1:
            st.markdown(f"**{em} {sig.get('name', '')}** ({sig.get('ticker', '')})")
            st.caption(f"{sig.get('trade_direction', 'neutral').upper()} | {sig.get('timestamp', '')[:16]}")
        
        with c2:
            st.metric("Вход", f"{sig.get('entry_price', 0):.2f}")
        
        with c3:
            if sig.get('checked'):
                pnl = sig.get('pnl_pct', 0) or 0
                c = "green" if pnl >= 0 else "red"
                st.markdown(f"<span style='color:{c}; font-size:18px; font-weight:bold;'>{pnl:+.2f}%</span>", unsafe_allow_html=True)
            else:
                st.markdown("⏳")
        
        with c4:
            st.markdown(f"**{outcome}**")
            if sig.get('exit_reason'):
                st.caption(f"({sig.get('exit_reason')})")
        
        st.markdown('</div>', unsafe_allow_html=True)
        st.divider()
