import streamlit as st
import threading
import logging
from datetime import datetime

from config import CONFIG, get_all_assets
from database import init_db, execute_db_query
from moex_api import load_dynamic_stocks
from monitor import background_monitor

from ui.heatmap import render_heatmap_correlation
from ui.sectors import render_sector_comparison
from ui.ideas import render_best_ideas_dashboard, render_trade_plans, render_active_positions
from ui.quotes import render_quotes_tab
from ui.catalog import render_stock_catalog_tab
from ui.news import render_news_tab
from ui.signals import render_signals_tab
from ui.performance import render_performance_tab
from ui.history import render_history_tab

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    # Настройка страницы
    st.set_page_config(page_title="Макро-Радар МОЕХ v7.2", page_icon="📈", layout="wide")
    
    # Кастомные стили
    st.markdown("""
    <style>
        .main { background-color: #0e1117; }
        .trade-long { border-left: 4px solid #00ff00; padding: 15px; background: rgba(0,255,0,0.05); border-radius: 5px; }
        .trade-short { border-left: 4px solid #ff4444; padding: 15px; background: rgba(255,68,68,0.05); border-radius: 5px; }
        .exit-signal { background: #262730; padding: 10px; margin: 5px 0; border-radius: 5px; }
        .outcome-win { background: rgba(0,255,0,0.1); padding: 10px; border-radius: 3px; }
        .outcome-loss { background: rgba(255,68,68,0.1); padding: 10px; border-radius: 3px; }
    </style>
    """, unsafe_allow_html=True)
    
    # 1. Инициализация БД
    init_db()
    
    # 2. Загрузка динамических акций (если ещё не загружены)
    if not CONFIG.get('DYNAMIC_STOCKS'):
        try:
            load_dynamic_stocks()
            logger.info(f"✅ Динамические акции загружены: {len(CONFIG['DYNAMIC_STOCKS'])}")
        except Exception as e:
            logger.error(f"Ошибка загрузки акций: {e}")
    
    # 3. Запуск фонового мониторинга (один раз за сессию)
    if 'monitor_running' not in st.session_state:
        st.session_state.monitor_running = True
        threading.Thread(target=background_monitor, daemon=True).start()
    
    # Заголовок и статус
    st.title("📈 Макро-Радар МОЕХ v7.2")
    st.caption("**Профессиональный трейдинг-терминал с 200+ акциями**")
    st.warning("⚠️ Аналитический инструмент. Все решения принимаете самостоятельно.")
    
    now = datetime.now(CONFIG['MSK_TZ'])
    is_open = now.weekday() < 5 and 10 <= now.hour < 24
    st.caption(f"**Статус:** {'🟢 Торги' if is_open else '🔴 Закрыт'} | **Время:** {now.strftime('%H:%M:%S')}")
    
    # Загрузка данных из БД
    signals_rows = execute_db_query('SELECT * FROM signals ORDER BY timestamp DESC LIMIT 200', fetch=True) or []
    sig_cols = ['id', 'timestamp', 'ticker', 'name', 'type', 'sector', 'price', 'change_pct',
              'volume', 'avg_volume', 'rsi', 'atr', 'strength', 'news_sentiment', 'forecast_score',
              'entry_price', 'stop_loss', 'take_profit_1', 'take_profit_2', 'take_profit_3',
              'risk_reward', 'position_size', 'trade_direction', 'support_level', 'resistance_level',
              'outcome', 'pnl_pct', 'max_price', 'min_price', 'hours_elapsed', 'checked', 'exit_reason']
    signals = [dict(zip(sig_cols, r)) for r in signals_rows if len(r) >= len(sig_cols)]
    
    ideas_rows = execute_db_query('SELECT * FROM trade_ideas WHERE status="active" ORDER BY timestamp DESC', fetch=True) or []
    idea_cols = ['id', 'timestamp', 'ticker', 'name', 'direction', 'entry_price', 'stop_loss',
                 'take_profit_1', 'take_profit_2', 'take_profit_3', 'risk_reward', 'position_size',
                 'confidence', 'status', 'exit_signal', 'exit_timestamp']
    trade_ideas = [dict(zip(idea_cols, r)) for r in ideas_rows if len(r) >= len(idea_cols)]
    
    # Статистика
    checked = [s for s in signals if s.get('checked') == 1]
    wins = [s for s in checked if s.get('outcome') == 'win']
    losses = [s for s in checked if s.get('outcome') == 'loss']
    
    # Верхние метрики
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.metric("Сигналов", len(signals))
    with c2: st.metric("Проверено", len(checked))
    with c3:
        wr = len(wins) / max(len(checked), 1) * 100
        st.metric("Win Rate", f"{wr:.1f}%")
    with c4: st.metric("Идей", len(trade_ideas))
    with c5: st.metric("Активов", len(get_all_assets()))
    
    st.markdown("---")
    
    # Автообновление
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=30000, key="auto_refresh")
    except ImportError:
        if st.button("🔄 Обновить"):
            st.rerun()
    
    # Вкладки
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11 = st.tabs([
        "⭐ Лучшие идеи", "🇷🇺 Каталог", "🔥 Корреляции", "📊 Секторы",
        "📈 Котировки", "💡 Идеи", "🎯 Сигналы",
        "🚨 Позиции", "📊 Эффективность", "📰 Новости", "📜 История"
    ])
    
    with tab1: render_best_ideas_dashboard()
    with tab2: render_stock_catalog_tab()
    with tab3: render_heatmap_correlation()
    with tab4: render_sector_comparison()
    with tab5: render_quotes_tab()
    with tab6: render_trade_plans(trade_ideas)
    with tab7: render_signals_tab(signals)
    with tab8: render_active_positions(trade_ideas)
    with tab9: render_performance_tab(checked, wins, losses)
    with tab10: render_news_tab()
    with tab11: render_history_tab(signals)


if __name__ == "__main__":
    main()
