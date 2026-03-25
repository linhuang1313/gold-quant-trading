"""
黄金量化交易系统 — 配置文件
============================
所有参数集中管理，修改这里即可
"""
from pathlib import Path

# ============================================================
# MT4 连接配置
# ============================================================
# MT4 数据文件夹路径 (在MT4中 File → Open Data Folder 获取)
# 例如: C:\Users\hlin2\AppData\Roaming\MetaQuotes\Terminal\XXXXXXXX
METATRADER_DIR_PATH = r"C:\Users\hlin2\AppData\Roaming\MetaQuotes\Terminal\YOUR_TERMINAL_ID"

# MT4 文件桥接目录 (EA和Python通过这个目录通信)
BRIDGE_DIR = Path(METATRADER_DIR_PATH) / "MQL4" / "Files" / "DWX"

# ============================================================
# 交易账户参数
# ============================================================
SYMBOL = "XAUUSD"         # 交易品种 (你的经纪商可能用 GOLD 或 XAUUSDm)
CAPITAL = 3000            # 本金 (USD)
MAX_TOTAL_LOSS = 1500     # 最大总亏损 (USD)，达到后停止交易
LOT_SIZE = 0.01           # 手数 (0.01手 = 1盎司 = $1/点)
MAX_POSITIONS = 2         # 最大同时持仓数
STOP_LOSS_PIPS = 50       # 止损距离 (点/$)
MAGIC_NUMBER = 20260325   # EA魔术号 (区分手动单和策略单)
SLIPPAGE = 5              # 最大滑点 (点)

# ============================================================
# 策略参数
# ============================================================
STRATEGIES = {
    "bollinger": {
        "enabled": True,
        "name": "布林带均值回归",
        "bb_period": 20,
        "bb_std": 2.0,
        "ma_trend": 200,        # 趋势过滤均线
        "exit_target": "bb_mid", # 出场目标: 布林带中轨
        "stop_loss": 50,         # 止损 (点)
        "max_hold_bars": 15,     # 最大持仓K线数 (日线=15天)
    },
    "rsi_aggressive": {
        "enabled": True,
        "name": "RSI<5 激进均值回归",
        "rsi_period": 2,
        "rsi_entry": 5,         # RSI < 5 才入场
        "ma_trend": 200,
        "ma_exit": 10,           # MA10 出场
        "stop_loss": 50,
        "max_hold_bars": 15,
    },
    "range_breakout": {
        "enabled": True,
        "name": "窄幅突破",
        "range_pct": 0.6,       # 日内波幅 < 平均的60%
        "lookback": 5,           # 前N日高点突破
        "ma_trend": 200,
        "ma_exit": 10,
        "stop_loss": 50,
        "max_hold_bars": 15,
    },
}

# ============================================================
# 扫描频率
# ============================================================
SCAN_INTERVAL_SECONDS = 60    # 每60秒扫描一次 (盘中)
SIGNAL_CHECK_TIMEFRAME = "D1"  # 日线级别信号

# ============================================================
# 通知
# ============================================================
NOTIFY_METHOD = "console"      # "console" | "telegram"
# TELEGRAM_BOT_TOKEN = ""
# TELEGRAM_CHAT_ID = ""

# ============================================================
# 路径
# ============================================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
