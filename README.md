# DeepSeek Monitor

DeepSeek 账户余额与用量监控工具，系统托盘运行。

## 功能

- 实时显示余额（精度 ¥0.01）
- 本月消费总额
- 模型用量卡片（DeepSeek-V4-Pro / DeepSeek-V4-Flash）
  - 输入/输出 Token 消耗
  - 花费进度条（上限 ¥50，颜色分级）
- 近 7 日消耗趋势柱状图
- 余额低于阈值时桌面通知告警
- API 不可用时显示缓存数据
- 关闭窗口隐藏到托盘，不退出

## 安装

```bash
pip install pyqt5 requests
```

## 配置

编辑 `~/.deepseek-monitor/config.ini`：

```ini
[credential]
cookie = 从浏览器 DevTools 复制
token = Bearer 从浏览器 DevTools 复制

[monitor]
refresh_interval = 3600
alert_threshold = 10.0
```

从 [platform.deepseek.com](https://platform.deepseek.com) 登录后，从 DevTools（F12）Network 请求中复制 Cookie 和 Authorization Header。

## 使用

```bash
python3 deepseek_monitor.py
```

或通过 CLI 别名：

```bash
dsmon
```

## 开机自启

安装后自动配置，或手动添加：
`~/.config/autostart/deepseek-monitor.desktop`

## 技术栈

- Python 3 + PyQt5
- QPainter 原生绘制图表
- 深色 Fusion 主题
