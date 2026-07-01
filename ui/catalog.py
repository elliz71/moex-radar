import streamlit as st
import pandas as pd
import logging
from datetime import datetime
from config import CONFIG
from moex_api import get_all_stocks_catalog, load_dynamic_stocks

logger = logging.getLogger(__name__)


# ==========================================
# 🇷🇺 КАТАЛОГ ВСЕХ АКЦИЙ МОСБИРЖИ
# ==========================================
def render_stock_catalog_tab():
    """
    Отображает полный каталог всех акций Мосбиржи
    С фильтрами, поиском и возможностью скачать CSV
    """
    st.subheader("🇷🇺 Каталог всех акций Мосбиржи")
    st.caption("Все акции, доступные для покупки на Московской Бирже (секция TQBR)")
    
    with st.spinner("Загрузка полного списка акций..."):
        all_stocks = get_all_stocks_catalog()
    
    if not all_stocks:
        st.error("❌ Не удалось загрузить список акций.")
        return
    
    # Фильтры в одну строку
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    
    with col1:
        search_query = st.text_input("🔍 Поиск", placeholder="Сбер, LKOH, Магнит...", key="stock_search")
    with col2:
        sectors = sorted(list(set(s['sector'] for s in all_stocks)))
        selected_sector = st.selectbox("Сектор", ["Все"] + sectors, key="cat_sector")
    with col3:
        sort_option = st.selectbox("Сортировка", 
                                   ["По объёму торгов", "По названию", "По тикеру"], 
                                   key="cat_sort")
    with col4:
        show_count = st.selectbox("Показать", [50, 100, 200, "Все"], key="cat_count")
    
    # Общая статистика
    total_stocks = len(all_stocks)
    core_count = len(CONFIG['CORE_ASSETS'])
    dynamic_count = len(CONFIG.get('DYNAMIC_STOCKS', {}))
    futures_count = len(CONFIG['FUTURES'])
    
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("📊 Всего акций", total_stocks)
    with c2: st.metric("⭐ Core", core_count)
    with c3: st.metric("🔄 Отслеживается", dynamic_count)
    with c4: st.metric("🌍 Фьючерсы", futures_count)
    
    st.markdown("---")
    
    # Применяем фильтры
    filtered = all_stocks
    if search_query:
        query = search_query.lower()
        filtered = [s for s in filtered if query in s['ticker'].lower() or query in s['name'].lower()]
    if selected_sector != "Все":
        filtered = [s for s in filtered if s['sector'] == selected_sector]
    
    # Применяем сортировку
    if sort_option == "По названию":
        filtered.sort(key=lambda x: x['name'])
    elif sort_option == "По тикеру":
        filtered.sort(key=lambda x: x['ticker'])
    else:
        filtered.sort(key=lambda x: x.get('volume_today', 0), reverse=True)
    
    # Ограничиваем количество
    if show_count != "Все":
        filtered = filtered[:show_count]
    
    st.markdown(f"**Найдено:** {len(filtered)} акций")
    
    # Распределение по секторам (в свёрнутом блоке)
    sector_counts = {}
    for s in all_stocks:
        sec = s['sector']
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
    
    with st.expander("📊 Распределение по секторам", expanded=False):
        cols = st.columns(4)
        for i, (sector, count) in enumerate(sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)):
            with cols[i % 4]:
                st.markdown(f"**{sector}:** {count}")
    
    st.markdown("---")
    
    # Формируем таблицу
    table_data = []
    for stock in filtered:
        ticker = stock['ticker']
        is_core = ticker in CONFIG['CORE_ASSETS']
        is_dynamic = ticker in CONFIG.get('DYNAMIC_STOCKS', {})
        
        if is_core:
            status = "⭐ Core"
        elif is_dynamic:
            status = "🔄 Отслеживается"
        else:
            status = "⏸ Не отслеживается"
        
        vol_today = stock.get('volume_today', 0)
        vol_str = f"{vol_today:,.0f} ₽" if vol_today > 0 else "-"
        
        price = stock.get('last_price', 0)
        price_str = f"{price:.2f}" if price > 0 else "-"
        
        table_data.append({
            'Статус': status,
            'Тикер': ticker,
            'Название': stock['name'],
            'Сектор': stock['sector'],
            'Цена': price_str,
            'Объём сегодня': vol_str,
        })
    
    if table_data:
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True, height=600)
    else:
        st.info("📭 Нет акций по фильтрам")
    
    st.markdown("---")
    
    # Блок управления отслеживанием
    st.markdown("### ⚙️ Управление отслеживанием")
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Текущее количество:** {core_count + dynamic_count} акций")
        new_max = st.slider("Максимум динамических акций", 
                           min_value=10, max_value=50, 
                           value=CONFIG.get('MAX_TRACKED_STOCKS', 30),
                           key="max_stocks_slider")
        
        if new_max != CONFIG.get('MAX_TRACKED_STOCKS', 30):
            CONFIG['MAX_TRACKED_STOCKS'] = new_max
            if st.button("🔄 Применить", key="apply_max"):
                st.cache_data.clear()
                load_dynamic_stocks(new_max)
                st.rerun()
    
    with c2:
        st.markdown("**⚠️ Рекомендации:**")
        st.markdown("- **10-20**: Быстро, минимум запросов")
        st.markdown("- **30**: Оптимально (по умолчанию)")
        st.markdown("- **50**: Полный охват, медленнее")
    
    # Кнопка скачивания CSV
    if table_data:
        csv_data = pd.DataFrame(table_data).to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Скачать каталог (CSV)",
            data=csv_data,
            file_name=f"moex_stocks_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
  )
