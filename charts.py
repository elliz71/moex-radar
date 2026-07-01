import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
from matplotlib.lines import Line2D
import logging

logger = logging.getLogger(__name__)


# ==========================================
# 🎨 ГРАФИКИ
# ==========================================

def generate_candlestick_chart(df, ticker, name, trade_levels=None):
    """
    Генерация свечного графика с уровнями входа/стопа/тейк-профитов
    
    Параметры:
    - df: DataFrame со свечами (open, high, low, close, volume)
    - ticker: тикер акции
    - name: название компании
    - trade_levels: словарь с уровнями торговли (entry, stop_loss, tp1, tp2, tp3)
    """
    try:
        df_plot = df.copy()
        df_plot['begin'] = pd.to_datetime(df_plot['begin'])
        df_plot = df_plot.set_index('begin')
        df_plot = df_plot.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'volume': 'Volume'
        })
        df_plot = df_plot.tail(50)  # Показываем последние 50 свечей
        
        # Настройка цветов свечей (зелёный вверх, красный вниз)
        mc = mpf.make_marketcolors(
            up='#26a69a', down='#ef5350',
            edge='inherit', wick='inherit', volume='in'
        )
        
        # Стиль графика (тёмная тема)
        s = mpf.make_mpf_style(
            marketcolors=mc,
            base_mpf_style='nightclouds',
            gridstyle='-', gridcolor='#2a2a2a',
            facecolor='#0e1117', edgecolor='#0e1117',
            figcolor='#0e1117'
        )
        
        hlines_config = None
        add_plots = []
        
        # Добавляем горизонтальные линии уровней торговли
        if trade_levels and trade_levels.get('risk_reward', 0) > 0:
            entry = trade_levels.get('entry', 0)
            stop = trade_levels.get('stop_loss', 0)
            tp1 = trade_levels.get('tp1', 0)
            tp2 = trade_levels.get('tp2', 0)
            tp3 = trade_levels.get('tp3', 0)
            
            if all(v > 0 for v in [entry, stop, tp1, tp2, tp3]):
                hlines_config = {
                    'hlines': [entry, stop, tp1, tp2, tp3],
                    'colors': ['#00ffcc', '#ff4444', '#ffaa00', '#00ff00', '#00ffff'],
                    'linestyle': ['-', '--', '-', '-', '-'],
                    'linewidths': [1.5, 1.5, 1, 1, 1]
                }
        
        # Добавляем скользящую среднюю SMA(20)
        if len(df_plot) >= 20:
            sma20 = df_plot['Close'].rolling(window=20).mean()
            add_plots.append(mpf.make_addplot(sma20, color='#ffaa00', width=1, linestyle='--'))
        
        # Рисуем график
        fig, axes = mpf.plot(
            df_plot,
            type='candle',
            style=s,
            volume=True,
            figsize=(12, 6),
            returnfig=True,
            hlines=hlines_config,
            addplot=add_plots if add_plots else None,
            tight_layout=True
        )
        
        axes[0].set_title(f'{name} ({ticker}) - 10min', color='white', fontsize=14, pad=10)
        
        # Добавляем легенду с уровнями
        if hlines_config and trade_levels:
            legend_elements = [
                Line2D([0], [0], color='#00ffcc', linewidth=2, label=f'Entry: {trade_levels["entry"]:.2f}'),
                Line2D([0], [0], color='#ff4444', linewidth=2, linestyle='--', label=f'Stop: {trade_levels["stop_loss"]:.2f}'),
                Line2D([0], [0], color='#ffaa00', linewidth=1.5, label=f'TP1: {trade_levels["tp1"]:.2f}'),
                Line2D([0], [0], color='#00ff00', linewidth=1.5, label=f'TP2: {trade_levels["tp2"]:.2f}'),
                Line2D([0], [0], color='#00ffff', linewidth=1.5, label=f'TP3: {trade_levels["tp3"]:.2f}')
            ]
            axes[0].legend(handles=legend_elements, loc='upper left',
                          fontsize=8, facecolor='#262730',
                          edgecolor='#262730', labelcolor='white')
        
        return fig
    
    except Exception as e:
        logger.error(f"Ошибка графика {ticker}: {e}")
        # Если свечной график не получился - рисуем простой
        return generate_simple_chart(df, ticker, name)


def generate_simple_chart(df, ticker, name):
    """Простой линейный график (используется как запасной вариант)"""
    try:
        with plt.style.context('dark_background'):
            fig, ax = plt.subplots(figsize=(12, 5))
            fig.patch.set_facecolor('#0e1117')
            ax.set_facecolor('#0e1117')
            ax.plot(range(len(df)), df['close'], color='#00ffcc', linewidth=2)
            ax.set_title(f'{name} ({ticker})', color='white', fontsize=14)
            ax.grid(True, alpha=0.2)
            plt.tight_layout()
            return fig
    except Exception:
        # Если вообще ничего не работает - показываем заглушку
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.text(0.5, 0.5, 'Ошибка графика', ha='center', va='center')
        return fig
