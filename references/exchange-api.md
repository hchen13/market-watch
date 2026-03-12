# Exchange WebSocket API Reference

## Binance — 现货 bookTicker

**Endpoint:** `wss://stream.binance.com:9443/stream?streams=btcusdt@bookTicker/ethusdt@bookTicker/...`  
**Auth:** 无需（公开频道）  
**格式:** Combined stream wrapper

```json
{
  "stream": "btcusdt@bookTicker",
  "data": {
    "u": 400900217,
    "s": "BTCUSDT",
    "b": "84000.00",   // best bid (用作 current price)
    "B": "0.001",      // bid qty
    "a": "84001.00",   // best ask
    "A": "0.002"
  }
}
```

**支持资产:** BTC, ETH, SOL, BNB, HYPE (HYPEUSDT)  
**更新频率:** 实时（每次 order book 变化）  
**备注:** 
- 单连接最多 1024 streams
- 连接24小时后断开，需重连
- WS ping frame 每20秒，websockets 库自动处理

---

## OKX — 现货 tickers

**Endpoint:** `wss://ws.okx.com:8443/ws/v5/public`  
**Auth:** 无需（公开频道）

**订阅:**
```json
{
  "op": "subscribe",
  "args": [{"channel": "tickers", "instId": "BTC-USDT"}]
}
```

**推送数据:**
```json
{
  "arg": {"channel": "tickers", "instId": "BTC-USDT"},
  "data": [{
    "instId": "BTC-USDT",
    "last": "84000.1",    // last trade price
    "bidPx": "84000.0",
    "askPx": "84001.0",
    "ts": "1672926468073"
  }]
}
```

**支持资产:** BTC, ETH, SOL, XAUT (XAUT-USDT), HYPE  
**心跳:** Server → `"ping"` text，client 回 `"pong"` text（30s 间隔）

---

## Bitget — 现货 ticker (v2)

**Endpoint:** `wss://ws.bitget.com/v2/ws/public`  
**Auth:** 无需（公开频道）

**订阅:**
```json
{
  "op": "subscribe",
  "args": [{"instType": "SPOT", "channel": "ticker", "instId": "BTCUSDT"}]
}
```

**推送数据:**
```json
{
  "action": "snapshot",
  "arg": {"instType": "SPOT", "channel": "ticker", "instId": "BTCUSDT"},
  "data": [{
    "instId": "BTCUSDT",
    "lastPr": "84000.0",   // last price (v2 字段名)
    "bidPr": "83999.9",
    "askPr": "84001.1",
    "ts": "1695702438018"
  }],
  "ts": 1695702438029
}
```

**支持资产:** BTC, ETH, SOL, HYPE (HYPEUSDT)  
**心跳:** `{"op": "ping"}` → 回 `{"op": "pong"}`

---

## Hyperliquid — allMids (perp + spot)

**Endpoint:** `wss://api.hyperliquid.xyz/ws`  
**Auth:** 无需（公开频道）

**订阅:**
```json
{"method": "subscribe", "subscription": {"type": "allMids"}}
```

**推送数据:**
```json
{
  "channel": "allMids",
  "data": {
    "mids": {
      "BTC":  "84000.0",
      "ETH":  "2100.0",
      "SOL":  "120.0",
      "HYPE": "15.5",
      ...
    }
  }
}
```

**确认消息:**
```json
{"channel": "subscriptionResponse", "data": {"method": "subscribe", ...}}
```

**支持资产:** HYPE 和所有 Hyperliquid 上市资产（perp + spot mids）  
**备注:** allMids 是全市场 mid price 快照，每次有成交/挂单变化就推送

---

## CoinGecko — HTTP Fallback

**Endpoint:** `https://api.coingecko.com/api/v3/simple/price`  
**Auth:** 无需（免费公开 API）  
**格式:** `?ids=bitcoin,ethereum&vs_currencies=usd`  
**返回:**
```json
{"bitcoin": {"usd": 84000}, "ethereum": {"usd": 2100}}
```

**限制:** 免费 tier 约 30req/min，30s 轮询间隔安全  
**覆盖:** BTC, ETH, SOL, BNB, HYPE, XAUT 等（通过 coin ID）

---

## pytdx — A股行情 (TCP 请求-响应)

**协议:** TCP request-response (非 WebSocket，非推送)  
**Python:** `from pytdx.hq import TdxHq_API`  
**API:**
```python
api = TdxHq_API()
with api.connect("115.238.90.165", 7709):
    data = api.get_security_quotes([(1, "600519"), (0, "000001")])
    # market: 1=沪A(6开头/5开头), 0=深A
    # data[i]["price"] = 当前价格
```

**轮询间隔:** 盘中 3-5 秒（可支持，pytdx 延迟约 50-200ms）  
**交易时段:** 周一-五 9:30-11:30, 13:00-15:00 (北京时间)  
**备用服务器列表:**
- `115.238.90.165:7709`
- `115.238.56.198:7709`
- `180.153.18.170:7709`
- `101.227.73.20:7709`

---

## Asset → Exchange Priority

| 资产 | 优先级 |
|------|--------|
| BTC  | Binance → OKX → Bitget → CoinGecko |
| ETH  | Binance → OKX → Bitget → CoinGecko |
| SOL  | Binance → OKX → Bitget → CoinGecko |
| BNB  | Binance → CoinGecko |
| HYPE | Hyperliquid → Bitget → OKX → CoinGecko |
| XAUT | OKX → CoinGecko |
| A股  | pytdx (盘中) |
