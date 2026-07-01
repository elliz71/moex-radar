import streamlit as st
import pandas as pd
import logging

logger = logging.getLogger(__name__)


# ==========================================
# 📈 ПОЛУЧЕНИЕ ДАННЫХ ПО ВСЕМ АКТИВАМ
# ==========================================
@st.cache_data(ttl=60)
def get_all_assets_data(assets_count):
    """Получение данных по всем активам с кэшированием"""
    from moex_api import get_moex_data
    from config import get_all_assets
    
    assets = []
    for ticker, info in get_all_assets().items():
        df = get_moex_data(ticker, info['type'])
        if df is not None and len(df) > 0:
            try:
                current = df['close'].iloc[-1]
                prev = df['close'].iloc[-2] if len(df) > 1 else current
                change = ((current - prev) / prev) * 100 if prev > 0 else 0
                assets.append({
                    'ticker': ticker, 'name': info['name'], 'type': info['type'],
                    'sector': info.get('sector', 'unknown'), 'price': current,
                    'change_pct': change, 'volume': df['volume'].iloc[-1], 'df': df
                })
            except Exception:
                continue
    return assets


def get_latest_trade_levels(ticker):
    """Получить последние уровни торговли для тикера"""
    from database import execute_db_query
    
    try:
        row = execute_db_query(
            'SELECT entry_price, stop_loss, take_profit_1, take_profit_2, take_profit_3, risk_reward FROM signals WHERE ticker=? ORDER BY timestamp DESC LIMIT 1',
            (ticker,),
            fetch=True
        )
        if row and row[0] and row[0][0] is not None:
            return {
                'entry': row[0][0] or 0, 'stop_loss': row[0][1] or 0,
                'tp1': row[0][2] or 0, 'tp2': row[0][3] or 0,
                'tp3': row[0][4] or 0, 'risk_reward': row[0][5] or 0
            }
    except Exception:
        pass
    return None


# ==========================================
# 📈 ВКЛАДКА КОТИРОВОК
# ==========================================
def render_quotes_tab():
    """Отображает котировки всех отслеживаемых активов с графиками"""
    from charts import generate_candlestick_chart
    from technical_analysis import calculate_rsi
    from config import CONFIG, get_all_assets
    
    st.subheader("📈 Котировки и графики")
    
    # Фильтры
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        show_type = st.selectbox("Показать", ["Все", "Только акции", "Только фьючерсы"], key="qt_type")
    with c2:
        sort_by = st.selectbox("Сортировка", ["По имени", "По изменению %", "По объему"], key="qt_sort")
    with c3:
        if st.button("🔄 Обновить", key="refresh_quotes"):
            st.cache_data.clear()
            st.rerun()
    
    st.markdown("---")
    
    # Загрузка данных
    assets_count = len(get_all_assets())
    with st.spinner("Загрузка..."):
        assets = get_all_assets_data(assets_count)
    
    # Фильтрация по типу
    if show_type == "Только акции":
        assets = [a for a in assets if a['type'] == 'stock']
    elif show_type == "Только фьючерсы":
        assets = [a for a in assets if a['type'] == 'futures']
    
    # Сортировка
    if sort_by == "По изменению %":
        assets.sort(key=lambda x: x.get('change_pct', 0), reverse=True)
    elif sort_by == "По объему":
        assets.sort(key=lambda x: x.get('volume', 0), reverse=True)
    else:
        assets.sort(key=lambda x: x.get('name', ''))
    
    # Общая статистика
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("Активов", len(assets))
    with c2: st.metric("Растущих", f"{len([a for a in assets if a.get('change_pct', 0) > 0])} 🚀")
    with c3: st.metric("Падающих", f"{len([a for a in assets if a.get('change_pct', 0) < 0])} 🩸")
    with c4:
        avg = sum(a.get('change_pct', 0) for a in assets) / max(len(assets), 1)
        color = "green" if avg >= 0 else "red"
        st.markdown(f"**Среднее:** <span style='color:{color}; font-size:20px;'>{avg:+.2f}%</span>", unsafe_allow_html=True)
    
    st.markdown("---")
    st.caption("💡 Показаны только отслеживаемые активы. Полный каталог — во вкладке **🇷🇺 Каталог**")
    
    # Разделяем акции и фьючерсы
    stocks = [a for a in assets if a['type'] == 'stock']
    futures = [a for a in assets if a['type'] == 'futures']
    
    def render_asset_block(asset_list, title):
        """Рендерит блок активов (акции или фьючерсы)"""
        if not asset_list:
            return
        st.markdown(f"### {title}")
        for asset in asset_list:
            with st.container():
                c1, c2, c3 = st.columns([1, 2, 1])
                
                # Колонка 1: Информация об активе
                with c1:
                    change = asset.get('change_pct', 0)
                    emoji = "🚀" if change > 0 else "🩸" if change < 0 else "⚖️"
                    st.markdown(f"## {emoji} {asset.get('name', '')}")
                    st.markdown(f"**{asset.get('ticker', '')}** | {asset.get('sector', '')}")
                    color = "green" if change >= 0 else "red"
                    st.markdown(f"<span style='color:{color}; font-size:28px; font-weight:bold;'>{asset.get('price', 0):.2f}</span>", unsafe_allow_html=True)
                    st.markdown(f"<span style='color:{color}; font-size:20px;'>{change:+.2f}%</span>", unsafe_allow_html=True)
                    st.markdown(f"**Объем:** {asset.get('volume', 0):,.0f}")
                
                # Колонка 2: График
                with c2:
                    try:
                        trade_levels = get_latest_trade_levels(asset.get('ticker', ''))
                        fig = generate_candlestick_chart(asset.get('df'), asset.get('ticker', ''), asset.get('name', ''), trade_levels)
                        st.pyplot(fig)
                        plt.close(fig)
                    except Exception as e:
                        st.error(f"Ошибка: {e}")
                
                # Колонка 3: RSI
                with c3:
                    df = asset.get('df')
                    if df is not None:
                        rsi = calculate_rsi(df)
                        if rsi < CONFIG['RSI_OVERSOLD']:
                            st.success(f"📉 **RSI: {rsi:.1f}**\nПерепроданность")
                        elif rsi > CONFIG['RSI_OVERBOUGHT']:
                            st.error(f"📈 **RSI: {rsi:.1f}**\nПерекупленность")
                        else:
                            st.info(f"⚖️ **RSI: {rsi:.1f}**")
                
                st.markdown("---")
    
    # Рендерим блоки
    if show_type != "Только фьючерсы":
        render_asset_block(stocks, "🏭 Акции РФ")
    if show_type != "Только акции":
        render_asset_block(futures, "🌍 Сырье и Валюта")
    
    if not assets:
        st.warning("⚠️ Нет данных.")
