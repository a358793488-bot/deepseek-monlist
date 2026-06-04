#!/usr/bin/env python3
import configparser
import json
import math
import os
import sys
from datetime import datetime

import requests
from PyQt5.QtCore import QTimer, Qt, QSize, QRectF
from PyQt5.QtGui import (
    QIcon, QFont, QPixmap, QFontDatabase, QPainter, QColor,
    QPen, QBrush, QPainterPath, QLinearGradient, QFontMetrics
)
from PyQt5.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea,
    QMessageBox, QAction, QSizePolicy
)

CONFIG_DIR = os.path.expanduser("~/.deepseek-monitor")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.ini")
ICON_FILE = os.path.join(CONFIG_DIR, "icon.png")
CACHE_FILE = os.path.join(CONFIG_DIR, "cache.json")

SUMMARY_URL = "https://platform.deepseek.com/api/v0/users/get_user_summary"

def cost_url():
    now = datetime.now()
    return f"https://platform.deepseek.com/api/v0/usage/cost?month={now.month}&year={now.year}"

def amount_url():
    now = datetime.now()
    return f"https://platform.deepseek.com/api/v0/usage/amount?month={now.month}&year={now.year}"

# ── Palette ──
BG = "#0f0f15"
CARD = "#1a1a24"
CARD_HOVER = "#22222e"
BORDER = "#2a2a3a"
TEXT = "#e2e2ea"
TEXT_SECONDARY = "#7a7a8a"
TEXT_MUTED = "#555566"
ACCENT_BLUE = "#7aa2f7"
ACCENT_PEACH = "#f5a97f"
ACCENT_PINK = "#f5b7d0"
ACCENT_GREEN = "#a6da95"
ACCENT_MAUVE = "#c0a6e3"


class Config:
    def __init__(self):
        self.config = configparser.ConfigParser(interpolation=None)
        if os.path.exists(CONFIG_FILE):
            self.config.read(CONFIG_FILE)
        self._ensure()

    def _ensure(self):
        if "credential" not in self.config:
            self.config["credential"] = {"cookie": "YOUR_COOKIE_HERE", "token": "Bearer YOUR_TOKEN_HERE"}
        if "monitor" not in self.config:
            self.config["monitor"] = {"refresh_interval": "3600", "alert_threshold": "10.0"}
        self.save()

    @property
    def cookie(self): return self.config["credential"]["cookie"]

    @property
    def token(self): return self.config["credential"]["token"]

    @property
    def refresh_interval(self): return int(self.config["monitor"]["refresh_interval"])

    @property
    def alert_threshold(self): return float(self.config["monitor"]["alert_threshold"])

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            self.config.write(f)

conf = Config()


class TrayIcon(QSystemTrayIcon):
    def __init__(self, parent):
        super().__init__(parent)
        icon = QIcon(ICON_FILE) if os.path.exists(ICON_FILE) else QIcon.fromTheme("dialog-information")
        self.setIcon(icon)
        self.setToolTip("DeepSeek Monitor")
        menu = QMenu()
        menu.addAction("显示面板", parent.show)
        menu.addAction("立即刷新", parent.fetch_data)
        menu.addSeparator()
        menu.addAction("编辑配置", self.edit_config)
        menu.addAction("退出", QApplication.quit)
        self.setContextMenu(menu)
        self.activated.connect(lambda r: self.toggle(parent) if r == QSystemTrayIcon.ActivationReason.Trigger else None)

    def toggle(self, w):
        if w.isVisible(): w.hide()
        else: w.show(); w.raise_(); w.activateWindow()

    def edit_config(self):
        os.system(f'xdg-open "{CONFIG_FILE}"' if os.path.exists(CONFIG_FILE) else
                  f'mkdir -p "{CONFIG_DIR}" && echo "[credential]\ncookie = YOUR_COOKIE_HERE\ntoken = Bearer YOUR_TOKEN_HERE\n\n[monitor]\nrefresh_interval = 3600\nalert_threshold = 10.0" > "{CONFIG_FILE}" && xdg-open "{CONFIG_FILE}"')


class ChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.days = []
        self.values = []
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, days, values):
        self.days = days
        self.values = values
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 50, 16, 16, 28
        chart_w = w - pad_l - pad_r
        chart_h = h - pad_t - pad_b

        if not self.values or max(self.values) == 0:
            p.setPen(QColor(TEXT_MUTED))
            fm = QFontMetrics(p.font())
            text = "暂无数据"
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, text)
            p.end()
            return

        max_v = max(self.values)
        min_v = 0

        # Y-axis labels + grid
        n_labels = 4
        p.setFont(QFont("sans-serif", 8))
        for i in range(n_labels + 1):
            y_val = min_v + (max_v - min_v) * (1 - i / n_labels)
            y_pos = pad_t + chart_h * (i / n_labels)
            label = ""
            if y_val >= 1_000_000:
                label = f"{y_val/1_000_000:.1f}M"
            elif y_val >= 1_000:
                label = f"{y_val/1_000:.0f}K"
            else:
                label = f"{y_val:.0f}"
            p.setPen(QColor(TEXT_MUTED))
            fm = QFontMetrics(p.font())
            p.drawText(QRectF(2, y_pos - 7, pad_l - 8, 14), Qt.AlignRight | Qt.AlignVCenter, label)
            if i > 0:
                p.setPen(QPen(QColor(BORDER), 1))
                p.drawLine(int(pad_l), int(y_pos), int(w - pad_r), int(y_pos))

        # Bars
        bar_count = len(self.values)
        if bar_count == 0:
            p.end()
            return
        total_gap = chart_w * 0.25
        gap = total_gap / (bar_count + 1)
        bar_w = (chart_w - total_gap) / bar_count

        for i, v in enumerate(self.values):
            if max_v == min_v:
                bar_h = 0.5 * chart_h
            else:
                bar_h = (v - min_v) / (max_v - min_v) * chart_h
            x = pad_l + gap + i * (bar_w + gap)
            y = pad_t + chart_h - bar_h

            # Rounded rect
            path = QPainterPath()
            radius = min(4, bar_w / 3)
            path.addRoundedRect(QRectF(x, y, bar_w, bar_h), radius, radius)
            grad = QLinearGradient(x, y, x + bar_w, y)
            grad.setColorAt(0, QColor(ACCENT_BLUE))
            grad.setColorAt(1, QColor("#b4befe"))
            p.fillPath(path, QBrush(grad))

            # Value label above bar
            p.setPen(QPen(QColor(ACCENT_BLUE), 1.5))
            p.setFont(QFont("sans-serif", 9, QFont.Bold))
            fm = QFontMetrics(p.font())
            vlabel = ""
            if v >= 1_000_000:
                vlabel = f"{v/1_000_000:.1f}M"
            elif v >= 1_000:
                vlabel = f"{v/1_000:.1f}K"
            else:
                vlabel = f"{v:.0f}"
            vl_w = fm.width(vlabel)
            p.drawText(QRectF(x + bar_w/2 - vl_w/2, y - 18, vl_w, 16), Qt.AlignCenter, vlabel)

            # Day label
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(QFont("sans-serif", 8, QFont.Bold))
            fm = QFontMetrics(p.font())
            label = self.days[i] if i < len(self.days) else ""
            label_w = fm.width(label)
            p.drawText(QRectF(x + bar_w/2 - label_w/2, pad_t + chart_h + 4, label_w, 20), Qt.AlignCenter, label)

        p.end()


class ModelCard(QFrame):
    def __init__(self, name, cost, tokens, progress):
        super().__init__()
        self.setStyleSheet(f"""
            ModelCard {{ background: {CARD}; border-radius: 10px; padding: 12px; }}
            ModelCard:hover {{ background: {CARD_HOVER}; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        row = QHBoxLayout()
        n = QLabel(name)
        n.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {TEXT};")
        row.addWidget(n)
        row.addStretch()
        c = QLabel(f"¥{cost}")
        c.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {ACCENT_PINK};")
        row.addWidget(c)
        layout.addLayout(row)

        bar_row = QHBoxLayout()
        bar_container = QWidget()
        bar_container.setFixedHeight(8)
        bar_container.setStyleSheet(f"background: {BORDER}; border-radius: 4px;")
        bar_layout = QHBoxLayout(bar_container)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        fill = QWidget()
        fill.setFixedWidth(int(max(0, min(progress, 1.0)) * 200))
        fill.setFixedHeight(8)
        fill.setStyleSheet(f"""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {ACCENT_BLUE}, stop:1 #b4befe);
            border-radius: 4px;
        """)
        bar_layout.addWidget(fill)
        bar_layout.addStretch()
        bar_row.addWidget(bar_container, 1)
        t = QLabel(tokens)
        t.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")
        bar_row.addWidget(t)
        layout.addLayout(bar_row)


class DeepSeekMonitor(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DeepSeek Monitor")
        self.setMinimumSize(400, 540)
        self.resize(420, 600)
        self.setStyleSheet(f"DeepSeekMonitor {{ background: {BG}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # ── Header ──
        header = QHBoxLayout()
        icon_l = QLabel()
        if os.path.exists(ICON_FILE):
            icon_l.setPixmap(QPixmap(ICON_FILE).scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        icon_l.setFixedSize(20, 20)
        t = QLabel("DeepSeek Monitor")
        t.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {TEXT};")
        header.addWidget(icon_l)
        header.addSpacing(8)
        header.addWidget(t)
        header.addStretch()
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setFixedSize(32, 32)
        self.refresh_btn.setStyleSheet(f"""
            QPushButton {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
                          font-size: 18px; font-weight: bold; color: {TEXT_SECONDARY}; }}
            QPushButton:hover {{ background: {CARD_HOVER}; color: {ACCENT_BLUE}; }}
        """)
        self.refresh_btn.clicked.connect(self.manual_refresh)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        # ── Balance Card ──
        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background: {CARD}; border-radius: 12px; padding: 6px; }}")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(20, 14, 20, 14)

        bal_v = QVBoxLayout()
        bal_v.setSpacing(2)
        bl = QLabel("当前余额")
        bl.setStyleSheet(f"font-size: 11px; color: {TEXT_MUTED}; font-weight: 500;")
        self.balance_val = QLabel("¥ 0.00")
        self.balance_val.setStyleSheet(f"font-size: 26px; font-weight: bold; color: {ACCENT_BLUE};")
        bal_v.addWidget(bl)
        bal_v.addWidget(self.balance_val)
        card_layout.addLayout(bal_v)
        card_layout.addStretch()

        cost_v = QVBoxLayout()
        cost_v.setSpacing(2)
        cl = QLabel("本月消费")
        cl.setStyleSheet(f"font-size: 11px; color: {TEXT_MUTED}; font-weight: 500;")
        cl.setAlignment(Qt.AlignRight)
        self.monthly_val = QLabel("¥ 0.00")
        self.monthly_val.setStyleSheet(f"font-size: 26px; font-weight: bold; color: {ACCENT_PEACH};")
        self.monthly_val.setAlignment(Qt.AlignRight)
        cost_v.addWidget(cl)
        cost_v.addWidget(self.monthly_val)
        card_layout.addLayout(cost_v)
        layout.addWidget(card)

        # ── Status ──
        status_row = QHBoxLayout()
        self.status_label = QLabel("加载中...")
        self.status_label.setStyleSheet(f"font-size: 11px; color: {TEXT_MUTED};")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        self.update_label = QLabel("")
        self.update_label.setStyleSheet(f"font-size: 11px; color: {TEXT_MUTED};")
        status_row.addWidget(self.update_label)
        layout.addLayout(status_row)

        # ── Section: 模型用量 ──
        sec1 = QLabel("模型用量")
        sec1.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {TEXT_MUTED}; padding-top: 4px; letter-spacing: 1px;")
        layout.addWidget(sec1)

        self.model_container = QVBoxLayout()
        self.model_container.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setMinimumHeight(100)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            f"QScrollBar:vertical {{ background: {BG}; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 3px; min-height: 20px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        sw = QWidget()
        sw.setStyleSheet("background: transparent;")
        sw.setLayout(self.model_container)
        scroll.setWidget(sw)
        layout.addWidget(scroll, 1)

        # ── Section: 消耗趋势 ──
        sec2 = QLabel("消耗趋势")
        sec2.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {TEXT_MUTED}; padding-top: 4px; letter-spacing: 1px;")
        layout.addWidget(sec2)

        self.chart = ChartWidget()
        layout.addWidget(self.chart)

        # ── Timer & init ──
        self.timer = QTimer()
        self.timer.timeout.connect(self.fetch_data)
        self.timer.start(conf.refresh_interval * 1000)

        self.tray = TrayIcon(self)
        self.tray.show()

        self.load_cache()
        QTimer.singleShot(500, self.fetch_data)

    # ── Cache ──

    def load_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE) as f:
                    d = json.load(f)
                self.update_ui(d["summary"], d["cost"], d["amount"])
                self.status_label.setText("✓ 缓存数据")
                self.status_label.setStyleSheet(f"font-size: 11px; color: {ACCENT_GREEN};")
            except Exception as e:
                print(f"[dsmon] cache error: {e}")

    def save_cache(self, s, c, a):
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump({"summary": s, "cost": c, "amount": a}, f)
        except Exception as e:
            print(f"[dsmon] cache save error: {e}")

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    # ── API ──

    def manual_refresh(self):
        self.retry_pending = False
        self.status_label.setText("⟳ 刷新中...")
        self.status_label.setStyleSheet(f"font-size: 11px; color: {ACCENT_BLUE};")
        QTimer.singleShot(200, self.fetch_data)

    def do_request(self, url):
        h = {"Cookie": conf.cookie, "Authorization": conf.token,
             "User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        r = requests.get(url, headers=h, timeout=30)
        r.raise_for_status()
        return r.json()

    def fetch_data(self):
        try:
            print("[dsmon] fetching...")
            s = self.do_request(SUMMARY_URL)
            c = self.do_request(cost_url())
            a = self.do_request(amount_url())
            self.update_ui(s, c, a)
            self.save_cache(s, c, a)
            self.status_label.setStyleSheet(f"font-size: 11px; color: {ACCENT_GREEN};")
            self.status_label.setText("✓ 服务正常")
            self.retry_pending = False
        except Exception as e:
            print(f"[dsmon] error: {e}")
            msg = str(e)
            if "429" in msg:
                msg = "请求太频繁，30秒后重试"
                if not getattr(self, 'retry_pending', False):
                    self.retry_pending = True
                    QTimer.singleShot(30000, self.fetch_data)
            elif "401" in msg or "40002" in msg:
                msg = "Token 无效，请重新配置"
            elif "ConnectionError" in msg or "timeout" in msg.lower():
                msg = "网络连接失败"
            self.status_label.setText(f"✗ {msg}")
            self.status_label.setStyleSheet(f"font-size: 11px; color: {ACCENT_PINK};")

    # ── UI Update ──

    def update_ui(self, summary, cost_data, amount_data):
        biz = summary.get("data", {}).get("biz_data", {})
        wallets = biz.get("normal_wallets", [])
        costs = biz.get("monthly_costs", [])
        cny_w = next((w for w in wallets if w.get("currency") == "CNY"), {})
        cny_c = next((c for c in costs if c.get("currency") == "CNY"), {})
        bal = math.floor(float(cny_w.get("balance", 0)) * 100) / 100
        mon = math.floor(float(cny_c.get("amount", 0)) * 100) / 100
        self.balance_val.setText(f"¥ {bal:.2f}")
        self.monthly_val.setText(f"¥ {mon:.2f}")

        if bal < conf.alert_threshold:
            self.tray.showMessage("DeepSeek Monitor", f"余额不足: ¥{bal:.2f}",
                                  QSystemTrayIcon.Warning, 5000)

        cb = cost_data.get("data", {}).get("biz_data", [{}])[0]
        ab = amount_data.get("data", {}).get("biz_data", {})
        ct = cb.get("total", [])
        at = ab.get("total", [])

        for i in reversed(range(self.model_container.count())):
            w = self.model_container.itemAt(i).widget()
            if w: w.setParent(None)

        cap = 100_000_000.0
        for item in ct:
            raw = item.get("model", "")
            cv = sum(float(u.get("amount", 0)) for u in item.get("usage", []))
            if cv <= 0: continue
            mt = next((x for x in at if x.get("model") == raw), {})
            ts = sum(float(u.get("amount", 0)) for u in mt.get("usage", [])
                     if "TOKEN" in u.get("type", "").upper())
            dn = raw.replace("deepseek-", "").title()
            if raw == "deepseek-v4-pro": dn = "DeepSeek-V4-Pro"
            elif raw == "deepseek-v4-flash": dn = "DeepSeek-V4-Flash"
            mc = ModelCard(dn, f"{cv:.2f}", f"{self.fmt(ts)}/100M", ts / cap)
            self.model_container.addWidget(mc)

        cd = cb.get("days", [])
        ad = ab.get("days", [])
        valid = [d for d in cd if sum(float(u.get("amount", 0))
                 for m in d.get("data", []) for u in m.get("usage", [])) > 0]
        valid = valid[-7:]
        if valid:
            days = [d.get("date", "")[-2:] for d in valid]
            vals = []
            for d in valid:
                am = next((x for x in ad if x.get("date") == d.get("date")), {})
                tv = sum(float(u.get("amount", 0)) for m in am.get("data", [])
                         for u in m.get("usage", []) if "TOKEN" in u.get("type", "").upper())
                vals.append(tv)
            self.chart.set_data(days, vals)

        self.update_label.setText(datetime.now().strftime("更新于 %H:%M"))

    def fmt(self, v):
        if v >= 1_000_000: return f"{v/1_000_000:.1f}M"
        if v >= 1_000: return f"{v/1_000:.1f}K"
        return f"{v:.0f}"


if __name__ == "__main__":
    if conf.cookie == "YOUR_COOKIE_HERE" or conf.token == "Bearer YOUR_TOKEN_HERE":
        print("请先编辑 ~/.deepseek-monitor/config.ini")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    f = app.font()
    f.setPointSize(10)
    f.setFamily(QFontDatabase.systemFont(QFontDatabase.GeneralFont).family())
    app.setFont(f)
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "错误", "未检测到系统托盘")
        sys.exit(1)
    w = DeepSeekMonitor(); w.show(); sys.exit(app.exec())
