import streamlit as st
import logging
from config import CONFIG, get_all_assets
from database import execute_db_query
from moex_api import get_moex_data
from technical_analysis import calculate_rsi

logger = logging.getLogger(__name__)


# ==========================================
# ⭐ ДАШБОРД ЛУЧШИХ ИДЕЙ
# ==========================================
def render_best_ideas_dashboard():
    """Отображает топ торговых идей по прогнозу и Risk/Reward"""
    st.subheader("⭐ Лучшие торговые идеи")
    st.caption("Автоматический отбор топ-сигналов")
    
    signals_rows = execute_db_query(
        'SELECT * FROM signals WHERE trade_direction != "neutral" ORDER BY timestamp DESC LIMIT 50',
        fetch=True) or []
    
    if not signals_rows:
        st.info("🔍 Пока нет торговых идей. Радар продолжает мониторинг...")
        return
    
    sig_cols = ['id', 'timestamp', 'ticker', 'name', 'type', 'sector', 'price', 'change_pct',
              'volume', 'avg_volume', 'rsi', 'atr', 'strength', 'news_sentiment', 'forecast_score',
              'entry_price', 'stop_loss', 'take_profit_1', 'take_profit_2', 'take_profit_3',
              'risk_reward', 'position_size', 'trade_direction', 'support_level', 'resistance_level',
              'outcome', 'pnl_pct', 'max_price', 'min_price', 'hours_elapsed', 'checked', 'exit_reason']
    
    signals = []
    for r in signals_rows:
        if len(r) >= len(sig_cols):
            signals.append(dict(zip(sig_cols, r)))
    
    if not signals:
        st.info("🔍 Нет данных")
        return
    
    # Топ-3 по прогнозу
    st.markdown("### 🎯 Топ-3 по вероятности успеха")
    top_forecast = sorted(signals, key=lambda x: x.get('forecast_score', 0) or 0, reverse=True)[:3]
    cols = st.columns(3)
    for i, sig in enumerate(top_forecast):
        with cols[i]:
            emoji = "📈" if sig.get('trade_direction') == 'long' else "📉"
            css = "trade-long" if sig.get('trade_direction') == 'long' else "trade-short"
            with st.container():
                st.markdown(f'<div class="{css}">', unsafe_allow_html=True)
                st.markdown(f"#### {emoji} {sig.get('name', '')}")
                forecast = sig.get('forecast_score', 0) or 0
                st.metric("🎯 Прогноз", f"{forecast:.0f}%")
                rr = sig.get('risk_reward', 0) or 0
                st.metric("R:R", f"1:{rr:.1f}" if rr > 0 else "N/A")
                rsi = sig.get('rsi', 50) or 50
                st.metric("RSI", f"{rsi:.1f}")
                change = sig.get('change_pct', 0) or 0
                st.caption(f"{change:+.2f}% | **{sig.get('trade_direction', '').upper()}** | {sig.get('sector', '')}")
                st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Топ-3 по Risk/Reward
    st.markdown("### 💰 Топ-3 по Risk/Reward")
    valid_rr = [s for s in signals if (s.get('risk_reward', 0) or 0) > 0]
    top_rr = sorted(valid_rr, key=lambda x: x.get('risk_reward', 0), reverse=True)[:3]
    
    if top_rr:
        cols = st.columns(3)
        for i, sig in enumerate(top_rr):
            with cols[i]:
                emoji = "📈" if sig.get('trade_direction') == 'long' else "📉"
                st.markdown(f"#### {emoji} {sig.get('name', '')}")
                rr = sig.get('risk_reward', 0) or 0
                st.metric("💎 R:R", f"1:{rr:.1f}")
                c1, c2 = st.columns(2)
                entry = sig.get('entry_price', 0) or 0
                stop = sig.get('stop_loss', 0) or 0
                with c1: st.markdown(f"**Вход:** {entry:.2f}")
                with c2: st.markdown(f"**Стоп:** <span style='color:#ff4444;'>{stop:.2f}</span>", unsafe_allow_html=True)


# ==========================================
# 💡 ГОТОВЫЕ ТОРГОВЫЕ ПЛАНЫ
# ==========================================
def render_trade_plans(trade_ideas):
    """Отображает готовые торговые планы с уровнями входа/стопа/тейк-профитов"""
    st.subheader("Готовые торговые планы")
    if not trade_ideas:
        st.info("Ожидание идей с R:R ≥ 1:2...")
    else:
        for idea in trade_ideas[:10]:
            direction = idea.get('direction', 'long')
            dir_emoji = "📈" if direction == 'long' else "📉"
            css = "trade-long" if direction == 'long' else "trade-short"
            
            ticker = idea.get('ticker', '')
            asset_info = get_all_assets().get(ticker, {'type': 'stock'})
            df = get_moex_data(ticker, asset_info.get('type', 'stock'))
            exit_sigs = []
            if df is not None:
                cp = df['close'].iloc[-1]
                rsi = calculate_rsi(df)
                exit_sigs = generate_exit_signals(
                    cp, idea.get('entry_price', 0), idea.get('stop_loss', 0),
                    idea.get('take_profit_1', 0), idea.get('take_profit_2', 0),
                    idea.get('take_profit_3', 0), direction, rsi)
            
            st.markdown(f'<div class="{css}">', unsafe_allow_html=True)
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                st.markdown(f"**{dir_emoji} {idea.get('name', '')} ({ticker})**")
                st.caption(f"**{direction.upper()}** | Уверенность: {idea.get('confidence', 0):.0f}%")
            with c2: st.metric("Вход", f"{idea.get('entry_price', 0):.2f}")
            with c3: st.metric("R:R", f"1:{idea.get('risk_reward', 0):.1f}")
            
            st.markdown("---")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown("**🛑 Стоп**")
                st.markdown(f"<span style='color:#ff4444; font-size:20px;'>{idea.get('stop_loss', 0):.2f}</span>", unsafe_allow_html=True)
            with c2:
                st.markdown("**🎯 Цель 1**")
                st.markdown(f"<span style='color:#ffaa00; font-size:20px;'>{idea.get('take_profit_1', 0):.2f}</span>", unsafe_allow_html=True)
            with c3:
                st.markdown("**🎯 Цель 2**")
                st.markdown(f"<span style='color:#00ff00; font-size:20px;'>{idea.get('take_profit_2', 0):.2f}</span>", unsafe_allow_html=True)
            with c4:
                st.markdown("**🎯 Цель 3**")
                st.markdown(f"<span style='color:#00ffff; font-size:20px;'>{idea.get('take_profit_3', 0):.2f}</span>", unsafe_allow_html=True)
            
            if exit_sigs:
                st.markdown("**⚠️ Выходы:**")
                for s in exit_sigs:
                    st.markdown(f'<div class="exit-signal">{s}</div>', unsafe_allow_html=True)
            
            st.markdown('</div>', unsafe_allow_html=True)
            st.divider()


# ==========================================
# 🚨 АКТИВНЫЕ ПОЗИЦИИ
# ==========================================
def render_active_positions(trade_ideas):
    """Отображает активные позиции с текущей прибылью/убытком"""
    st.subheader("Активные позиции")
    if not trade_ideas:
        st.info("Нет позиций")
    else:
        for idea in trade_ideas:
            ticker = idea.get('ticker', '')
            asset_info = get_all_assets().get(ticker, {'type': 'stock'})
            df = get_moex_data(ticker, asset_info.get('type', 'stock'))
            if df is not None:
                cp = df['close'].iloc[-1]
                entry = idea.get('entry_price', 0) or 1
                direction = idea.get('direction', 'long')
                if direction == 'long':
                    pnl = (cp - entry) / entry * 100
                else:
                    pnl = (entry - cp) / entry * 100
                color = "green" if pnl >= 0 else "red"
                css_class = "outcome-win" if pnl >= 0 else "outcome-loss"
                st.markdown(f'<div class="{css_class}">', unsafe_allow_html=True)
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    st.markdown(f"**{idea.get('name', '')}** ({ticker})")
                    st.caption(f"Вход: {entry:.2f}")
                with c2:
                    st.markdown(f"<span style='color:{color}; font-size:18px;'>{cp:.2f}</span>", unsafe_allow_html=True)
                with c3:
                    st.markdown(f"<span style='color:{color}; font-size:18px;'>{pnl:+.2f}%</span>", unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
                st.divider()


# ==========================================
# 💡 СИГНАЛЫ НА ВЫХОД
# ==========================================
def generate_exit_signals(price, entry, stop, tp1, tp2, tp3, direction, rsi):
    """Генерирует сигналы для выхода из позиции"""
    signals = []
    try:
        if direction == 'long':
            if stop > 0 and price <= stop:
                signals.append("🔴 СТОП-ЛОСС")
            if tp1 > 0 and price >= tp1:
                signals.append(f"🟡 Цель 1 ({tp1:.2f})")
            if tp2 > 0 and price >= tp2:
                signals.append(f"🟢 Цель 2 ({tp2:.2f})")
            if tp3 > 0 and price >= tp3:
                signals.append(f"🎯 Цель 3 ({tp3:.2f})")
            if entry > 0 and rsi > CONFIG['RSI_OVERBOUGHT'] and price > entry * 1.05:
                signals.append(f"⚠️ RSI перекуплен ({rsi:.1f})")
        elif direction == 'short':
            if stop > 0 and price >= stop:
                signals.append("🔴 СТОП-ЛОСС")
            if tp1 > 0 and price <= tp1:
                signals.append(f"🟡 Цель 1 ({tp1:.2f})")
            if tp2 > 0 and price <= tp2:
                signals.append(f"🟢 Цель 2 ({tp2:.2f})")
            if tp3 > 0 and price <= tp3:
                signals.append(f"🎯 Цель 3 ({tp3:.2f})")
            if entry > 0 and rsi < CONFIG['RSI_OVERSOLD'] and price < entry * 0.95:
                signals.append(f"⚠️ RSI перепродан ({rsi:.1f})")
    except Exception:
        pass
    return signals
