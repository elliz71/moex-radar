import streamlit as st
import requests
import feedparser
import logging

logger = logging.getLogger(__name__)


# ==========================================
# 📰 ВКЛАДКА НОВОСТЕЙ
# ==========================================
def render_news_tab():
    """Загружает новости из разных источников, анализирует их и показывает с фильтрами"""
    from news_analysis import analyze_news_sentiment
    
    st.subheader("📰 Новости с аналитикой")
    
    # Список источников RSS-лент
    NEWS_SOURCES = [
        {'name': 'Прайм', 'url': 'https://1prime.ru/export/rss2/'},
        {'name': 'Финанз.ру', 'url': 'https://www.finanz.ru/rss'},
        {'name': 'Investing.com RU', 'url': 'https://ru.investing.com/rss/news.rss'},
        {'name': 'РБК', 'url': 'https://rssexport.rbc.ru/rbcnews/news/20/full'},
        {'name': 'Ведомости', 'url': 'https://www.vedomosti.ru/rss/rubric/finance'},
    ]
    
    # Фильтры управления
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        news_filter = st.selectbox("Фильтр",
            ["Все новости", "Только с тикерами", "Только позитивные", "Только негативные"], 
            key="news_filter")
    with c2:
        source_names = ["🤖 Авто (все источники)"] + [s['name'] for s in NEWS_SOURCES]
        selected_source = st.selectbox("Источник", source_names, key="news_source")
    with c3:
        if st.button("🔄 Обновить", key="refresh_news"):
            st.cache_data.clear()
            st.rerun()
    
    st.markdown("---")
    news_list = []
    
    # Функция загрузки из конкретного источника
    def load_from_source(source):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/rss+xml, application/xml, text/xml, */*',
                'Accept-Language': 'ru-RU,ru;q=0.9'
            }
            response = requests.get(source['url'], headers=headers, timeout=10)
            if response.status_code != 200:
                return [], f"❌ HTTP {response.status_code}"
            
            feed = feedparser.parse(response.content)
            if not hasattr(feed, 'entries') or not feed.entries:
                return [], "❌ Пустой фид"
            
            results = []
            macro_keywords = ['цб', 'ставк', 'нефть', 'brent', 'золото', 'gold',
                            'доллар', 'рубль', 'санкц', 'инфляц', 'ввп', 'бирж',
                            'moex', 'мосбир', 'газпром', 'лукойл', 'сбер', 'яндекс',
                            'роснефть', 'полюс', 'opec', 'фрс', 'fed']
            
            for entry in feed.entries[:20]:
                title = entry.get('title', '')
                desc = entry.get('summary', entry.get('description', ''))
                url = entry.get('link', '#')
                published = entry.get('published', '')
                sentiment, tickers, sector, keywords = analyze_news_sentiment(title, desc)
                is_macro = any(kw in (title + ' ' + desc).lower() for kw in macro_keywords)
                
                # Сохраняем только важные новости (макро, с тикерами или сильным сентиментом)
                if is_macro or tickers or abs(sentiment) > 0.2:
                    results.append({
                        'title': title, 'url': url, 'published': published,
                        'sentiment': sentiment, 'tickers': tickers,
                        'sector': sector, 'keywords': keywords, 'source': source['name']
                    })
            return results, f"✅ {len(results)}"
        except Exception as e:
            return [], f"❌ {str(e)[:30]}"
    
    # Загрузка новостей
    with st.spinner("Загрузка..."):
        if selected_source == "🤖 Авто (все источники)":
            for source in NEWS_SOURCES:
                results, _ = load_from_source(source)
                news_list.extend(results)
        else:
            source = next((s for s in NEWS_SOURCES if s['name'] == selected_source), None)
            if source:
                results, _ = load_from_source(source)
                news_list.extend(results)
    
    # Убираем дубликаты по заголовку
    seen_titles = set()
    unique_news = []
    for n in news_list:
        if n['title'] not in seen_titles:
            seen_titles.add(n['title'])
            unique_news.append(n)
    news_list = unique_news
    
    # Применяем фильтр пользователя
    if news_filter == "Только с тикерами":
        news_list = [n for n in news_list if n.get('tickers')]
    elif news_filter == "Только позитивные":
        news_list = [n for n in news_list if (n.get('sentiment', 0) or 0) > 0.2]
    elif news_filter == "Только негативные":
        news_list = [n for n in news_list if (n.get('sentiment', 0) or 0) < -0.2]
    
    # Отображение статистики и списка
    st.markdown("---")
    if not news_list:
        st.warning("📭 Новости не удалось загрузить или ничего не найдено по фильтру")
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric("Всего", len(news_list))
        with c2: st.metric("🟢 Позитив", len([n for n in news_list if (n.get('sentiment', 0) or 0) > 0.2]))
        with c3: st.metric("🔴 Негатив", len([n for n in news_list if (n.get('sentiment', 0) or 0) < -0.2]))
        with c4: st.metric("Источников", len(set(n.get('source', '') for n in news_list)))
        
        # Общее настроение рынка
        avg_sent = sum(n.get('sentiment', 0) or 0 for n in news_list) / max(len(news_list), 1)
        mood = "🟢 ПОЗИТИВНО" if avg_sent > 0.2 else "🔴 НЕГАТИВНО" if avg_sent < -0.2 else "🟡 НЕЙТРАЛЬНО"
        mood_color = "green" if avg_sent > 0.2 else "red" if avg_sent < -0.2 else "orange"
        st.markdown(f"**Настроение:** <span style='color:{mood_color}; font-size:18px;'>{mood} ({avg_sent:+.2f})</span>", unsafe_allow_html=True)
        st.markdown("---")
        
        # Вывод списка новостей
        for n in news_list:
            sent = n.get('sentiment', 0) or 0
            if sent > 0.2:
                sent_emoji, sent_text = "🟢", f"Позитив ({sent:+.2f})"
            elif sent < -0.2:
                sent_emoji, sent_text = "🔴", f"Негатив ({sent:+.2f})"
            else:
                sent_emoji, sent_text = "🟡", f"Нейтрально ({sent:+.2f})"
            
            with st.container():
                source_badge = f"`{n.get('source', '')}`" if n.get('source') else ""
                st.markdown(f"### {sent_emoji} [{n.get('title', '')}]({n.get('url', '#')}) {source_badge}")
                meta = [f"**Сентимент:** {sent_text}"]
                tickers = n.get('tickers', [])
                if tickers:
                    meta.append(f"**Тикеры:** {' '.join(['`'+t+'`' for t in tickers])}")
                st.caption(" • ".join(meta))
                st.divider()
