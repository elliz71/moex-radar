import streamlit as st
import feedparser
import time
import logging
import pandas as pd
from datetime import datetime
from config import CONFIG, HEADERS, get_all_assets
from database import init_db, execute_db_query
from moex_api import fetch_moex_data_raw, load_dynamic_stocks
from technical_analysis import (
    calculate_rsi, calculate_atr, find_support_resistance,
    calculate_trade_levels, calculate_position_size, determine_trade_direction
)
from news_analysis import analyze_news_sentiment, calculate_forecast_score

logger = logging.getLogger(__name__)


# ==========================================
# 🤖 АВТОРАЗМЕТКА СИГНАЛОВ
# ==========================================
def auto_label_signals():
    """
    Автоматическая проверка старых сигналов
    Проверяет, сработал ли стоп-лосс или тейк-профит
    """
    unchecked = execute_db_query(
        'SELECT * FROM signals WHERE checked = 0 AND trade_direction != "neutral" ORDER BY timestamp ASC LIMIT 10',
        fetch=True)
    if not unchecked:
        return
    
    columns = ['id', 'timestamp', 'ticker', 'name', 'type', 'sector', 'price', 'change_pct',
               'volume', 'avg_volume', 'rsi', 'atr', 'strength', 'news_sentiment', 'forecast_score',
               'entry_price', 'stop_loss', 'take_profit_1', 'take_profit_2', 'take_profit_3',
               'risk_reward', 'position_size', 'trade_direction', 'support_level', 'resistance_level',
               'outcome', 'pnl_pct', 'max_price', 'min_price', 'hours_elapsed', 'checked', 'exit_reason']
    
    now = datetime.now(CONFIG['MSK_TZ'])
    
    for row in unchecked:
        if len(row) < len(columns):
            continue
        signal = dict(zip(columns, row))
        try:
            try:
                signal_time = datetime.fromisoformat(signal['timestamp'])
                if signal_time.tzinfo is None:
                    signal_time = CONFIG['MSK_TZ'].localize(signal_time)
            except (ValueError, TypeError):
                continue
            
            hours_elapsed = (now - signal_time).total_seconds() / 3600
            if hours_elapsed < CONFIG['AUTO_LABEL_HOURS']:
                continue
            
            df = fetch_moex_data_raw(signal['ticker'], signal['type'])
            if df is None or len(df) < 5:
                continue
            
            df['time'] = pd.to_datetime(df['begin'])
            try:
                df['time'] = df['time'].dt.tz_localize(CONFIG['MSK_TZ'])
            except Exception:
                pass
            
            df_after = df[df['time'] > signal_time]
            if len(df_after) == 0:
                df_after = df.tail(20)
            
            entry_price = signal.get('entry_price') or signal['price']
            stop_loss = signal.get('stop_loss') or 0
            tp1 = signal.get('take_profit_1') or 0
            tp2 = signal.get('take_profit_2') or 0
            tp3 = signal.get('take_profit_3') or 0
            direction = signal.get('trade_direction', 'neutral')
            
            if entry_price <= 0:
                continue
            
            max_price = df_after['high'].max()
            min_price = df_after['low'].min()
            final_price = df_after['close'].iloc[-1]
            
            outcome, exit_reason, pnl_pct = 'neutral', '', 0.0
            
            if direction == 'long':
                if stop_loss > 0 and min_price <= stop_loss:
                    outcome, exit_reason = 'loss', 'stop_loss'
                    pnl_pct = (stop_loss - entry_price) / entry_price * 100
                elif tp3 > 0 and max_price >= tp3:
                    outcome, exit_reason = 'win', 'target_3'
                    pnl_pct = (tp3 - entry_price) / entry_price * 100
                elif tp2 > 0 and max_price >= tp2:
                    outcome, exit_reason = 'win', 'target_2'
                    pnl_pct = (tp2 - entry_price) / entry_price * 100
                elif tp1 > 0 and max_price >= tp1:
                    outcome, exit_reason = 'win', 'target_1'
                    pnl_pct = (tp1 - entry_price) / entry_price * 100
                else:
                    pnl_pct = (final_price - entry_price) / entry_price * 100
                    if pnl_pct > 1.0:
                        outcome, exit_reason = 'partial_win', 'in_profit'
                    elif pnl_pct < -1.0:
                        outcome, exit_reason = 'partial_loss', 'in_loss'
                    else:
                        outcome, exit_reason = 'neutral', 'sideways'
            elif direction == 'short':
                if stop_loss > 0 and max_price >= stop_loss:
                    outcome, exit_reason = 'loss', 'stop_loss'
                    pnl_pct = (entry_price - stop_loss) / entry_price * 100
                elif tp3 > 0 and min_price <= tp3:
                    outcome, exit_reason = 'win', 'target_3'
                    pnl_pct = (entry_price - tp3) / entry_price * 100
                elif tp2 > 0 and min_price <= tp2:
                    outcome, exit_reason = 'win', 'target_2'
                    pnl_pct = (entry_price - tp2) / entry_price * 100
                elif tp1 > 0 and min_price <= tp1:
                    outcome, exit_reason = 'win', 'target_1'
                    pnl_pct = (entry_price - tp1) / entry_price * 100
                else:
                    pnl_pct = (entry_price - final_price) / entry_price * 100
                    if pnl_pct > 1.0:
                        outcome, exit_reason = 'partial_win', 'in_profit'
                    elif pnl_pct < -1.0:
                        outcome, exit_reason = 'partial_loss', 'in_loss'
                    else:
                        outcome, exit_reason = 'neutral', 'sideways'
            
            execute_db_query(
                '''UPDATE signals SET outcome=?, pnl_pct=?, max_price=?, min_price=?,
                   hours_elapsed=?, checked=1, exit_reason=? WHERE id=?''',
                (outcome, round(pnl_pct, 2), float(max_price), float(min_price),
                 round(hours_elapsed, 1), exit_reason, signal['id']))
            logger.info(f"✅ Размечен {signal['ticker']}: {outcome} ({pnl_pct:+.2f}%)")
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка разметки {signal.get('ticker', '?')}: {e}")
            continue


# ==========================================
# 🤖 ФОНОВЫЙ МОНИТОРИНГ
# ==========================================
def background_monitor():
    """
    Главный цикл мониторинга рынка
    Работает в фоне, постоянно проверяет акции и ищет сигналы
    """
    init_db()
    alerted_candles = {}
    last_label_check = 0
    last_news_check = 0
    
    # Ждём загрузки динамических акций
    wait_count = 0
    while wait_count < 10:
        current_count = len(CONFIG.get('DYNAMIC_STOCKS', {}))
        if current_count > 0:
            break
        time.sleep(3)
        wait_count += 1
        if wait_count % 3 == 0:
            logger.info(f"⏳ Ожидание акций... ({wait_count}/10, загружено: {current_count})")
    
    # Если главный поток не загрузил - загружаем сами
    if not CONFIG.get('DYNAMIC_STOCKS'):
        logger.warning("⚠️ Главный поток не загрузил акции. Загружаем из монитора...")
        try:
            load_dynamic_stocks()
        except Exception as e:
            logger.error(f"Ошибка загрузки в мониторе: {e}")
    
    # Отчёт о старте
    monitored_assets = get_all_assets()
    total_count = len(monitored_assets)
    core_count = len(CONFIG['CORE_ASSETS'])
    dynamic_count = len(CONFIG.get('DYNAMIC_STOCKS', {}))
    futures_count = len(CONFIG['FUTURES'])
    
    logger.info("=" * 60)
    logger.info("✅ МОНИТОР ЗАПУЩЕН")
    logger.info(f"📊 Активов для мониторинга: {total_count}")
    logger.info(f"   - Core акции: {core_count}")
    logger.info(f"   - Dynamic акции: {dynamic_count}")
    logger.info(f"   - Фьючерсы: {futures_count}")
    logger.info(f"🔍 Пороги: Volume × {CONFIG['VOLUME_MULTIPLIER']}, Price ≥ {CONFIG['PRICE_CHANGE_THRESHOLD']}%")
    logger.info("=" * 60)
    
    if total_count < 5:
        logger.error(f"🚨 Критически мало активов: {total_count}. Работаем только с core-активами")
    
    heartbeat_counter = 0
    
    while True:
        try:
            current_time = time.time()
            
            # === АВТОРАЗМЕТКА каждые 10 минут ===
            if current_time - last_label_check > 600:
                try:
                    auto_label_signals()
                    last_label_check = current_time
                except Exception as e:
                    logger.error(f"Ошибка авторазметки: {e}")
            
            # === ПАРСИНГ НОВОСТЕЙ каждые 5 минут ===
            if current_time - last_news_check > 300:
                try:
                    feed = feedparser.parse(CONFIG['NEWS_FEED_URL'], request_headers=HEADERS)
                    if hasattr(feed, 'entries') and feed.entries:
                        saved_count = 0
                        for entry in feed.entries[:10]:
                            title = entry.get('title', '')
                            desc = entry.get('summary', '')
                            url = entry.get('link', '')
                            sentiment, tickers, sector, keywords = analyze_news_sentiment(title, desc)
                            macro_words = ['цб', 'ставк', 'нефть', 'доллар', 'рубль', 'санкц', 'инфляц']
                            is_macro = any(w in (title + ' ' + desc).lower() for w in macro_words)
                            if tickers or (is_macro and abs(sentiment) > 0.1):
                                execute_db_query(
                                    '''INSERT INTO news_analysis (timestamp, title, url, sentiment_score,
                                       related_tickers, sector_impact, keywords_found) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                    (datetime.now(CONFIG['MSK_TZ']).isoformat(), title, url, sentiment,
                                     ','.join(tickers), sector, ','.join(keywords)))
                                saved_count += 1
                        last_news_check = current_time
                        logger.info(f"📰 Новости: сохранено {saved_count}")
                except Exception as e:
                    logger.error(f"Ошибка новостей: {e}")
            
            # === ТОРГОВЫЙ МОНИТОРИНГ ===
            now = datetime.now(CONFIG['MSK_TZ'])
            is_open = now.weekday() < 5 and 10 <= now.hour < 24
            
            if is_open:
                all_assets = get_all_assets()
                assets_count = len(all_assets)
                
                heartbeat_counter += 1
                if heartbeat_counter % 2 == 0:
                    logger.info(f"💓 Heartbeat | Активов: {assets_count} | Время: {now.strftime('%H:%M:%S')}")
                    
                    if assets_count < 10:
                        logger.warning(f"⚠️ Мало активов: {assets_count}. Попытка перезагрузить...")
                        try:
                            load_dynamic_stocks()
                        except Exception as e:
                            logger.error(f"Ошибка перезагрузки: {e}")
                    elif assets_count > 100:
                        logger.error(f"🚨 Слишком много активов: {assets_count}! Должно быть ~39")
                
                signals_found = 0
                
                for ticker, info in all_assets.items():
                    try:
                        df = fetch_moex_data_raw(ticker, info['type'])
                        if df is None or len(df) < 5:
                            continue
                        
                        current_volume = df['volume'].iloc[-1]
                        current_close = df['close'].iloc[-1]
                        prev_close = df['close'].iloc[-2]
                        candle_time = df['begin'].iloc[-1]
                        
                        if alerted_candles.get(ticker) == candle_time:
                            continue
                        
                        if prev_close <= 0:
                            continue
                        
                        avg_volume = df['volume'].iloc[:-1].mean()
                        price_change_pct = ((current_close - prev_close) / prev_close) * 100
                        
                        # Проверка условий сигнала
                        if avg_volume > 0 and current_volume > avg_volume * CONFIG['VOLUME_MULTIPLIER'] and abs(price_change_pct) >= CONFIG['PRICE_CHANGE_THRESHOLD']:
                            rsi = calculate_rsi(df)
                            atr = calculate_atr(df)
                            support, resistance = find_support_resistance(df)
                            strength = 'strong' if abs(price_change_pct) > 3.0 or rsi < CONFIG['RSI_OVERSOLD'] or rsi > CONFIG['RSI_OVERBOUGHT'] else 'medium'
                            
                            # Анализ новостей для этого тикера
                            recent_news = execute_db_query('SELECT sentiment_score, related_tickers FROM news_analysis ORDER BY timestamp DESC LIMIT 5', fetch=True) or []
                            ticker_sent, news_count = 0.0, 0
                            for row in recent_news:
                                if row and len(row) >= 2 and ticker in (row[1] or ''):
                                    ticker_sent += (row[0] or 0)
                                    news_count += 1
                            ticker_sent = ticker_sent / max(news_count, 1)
                            
                            # Историческая успешность
                            hist_rows = execute_db_query('SELECT ticker, change_pct FROM signals ORDER BY timestamp DESC LIMIT 50', fetch=True) or []
                            historical = [{'ticker': r[0], 'change_pct': r[1]} for r in hist_rows if r and len(r) >= 2]
                            
                            forecast = calculate_forecast_score(
                                {'ticker': ticker, 'change_pct': price_change_pct, 'volume': current_volume,
                                 'avg_volume': avg_volume, 'rsi': rsi}, ticker_sent, historical)
                            
                            direction = determine_trade_direction(rsi, price_change_pct, ticker_sent, support, resistance, current_close)
                            trade_levels = calculate_trade_levels(current_close, direction, atr, support, resistance, info.get('volatility', 'medium'))
                            position_size = calculate_position_size(100000, CONFIG['RISK_PER_TRADE'], trade_levels['entry'], trade_levels['stop_loss'])
                            
                            timestamp = datetime.now(CONFIG['MSK_TZ']).isoformat()
                            execute_db_query(
                                '''INSERT INTO signals (timestamp, ticker, name, asset_type, sector, price, change_pct,
                                   volume, avg_volume, rsi, atr, signal_strength, news_sentiment, forecast_score,
                                   entry_price, stop_loss, take_profit_1, take_profit_2, take_profit_3,
                                   risk_reward, position_size, trade_direction, support_level, resistance_level)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                (timestamp, ticker, info['name'], info['type'], info.get('sector', 'unknown'),
                                 float(current_close), float(price_change_pct), float(current_volume),
                                 float(avg_volume), rsi, atr, strength, ticker_sent, forecast,
                                 trade_levels['entry'], trade_levels['stop_loss'],
                                 trade_levels['tp1'], trade_levels['tp2'], trade_levels['tp3'],
                                 trade_levels['risk_reward'], position_size, direction, support, resistance))
                            
                            signals_found += 1
                            
                            # Создание торговой идеи если R:R хороший
                            if direction != 'neutral' and trade_levels['risk_reward'] >= CONFIG['MIN_RISK_REWARD']:
                                execute_db_query(
                                    '''INSERT INTO trade_ideas (timestamp, ticker, name, direction, entry_price,
                                       stop_loss, take_profit_1, take_profit_2, take_profit_3, risk_reward,
                                       position_size, confidence, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                    (timestamp, ticker, info['name'], direction, trade_levels['entry'],
                                     trade_levels['stop_loss'], trade_levels['tp1'], trade_levels['tp2'],
                                     trade_levels['tp3'], trade_levels['risk_reward'], position_size, forecast, 'active'))
                                logger.info(f"💡 Идея: {ticker} {direction} | R:R={trade_levels['risk_reward']:.2f}")
                            
                            alerted_candles[ticker] = candle_time
                            logger.info(f"🎯 Сигнал: {ticker} {price_change_pct:+.2f}%")
                    
                    except Exception as e:
                        logger.error(f"Ошибка мониторинга {ticker}: {e}")
                        continue
                    
                    time.sleep(0.2)
                
                if signals_found > 0:
                    logger.info(f"✅ За цикл найдено сигналов: {signals_found}")
                
                time.sleep(15)
            
            else:
                # Рынок закрыт
                if heartbeat_counter % 20 == 0:
                    logger.info(f"😴 Рынок закрыт. Спим... ({now.strftime('%H:%M')})")
                time.sleep(60)
        
        except Exception as e:
            logger.error(f"Критическая ошибка монитора: {e}")
            time.sleep(30)
