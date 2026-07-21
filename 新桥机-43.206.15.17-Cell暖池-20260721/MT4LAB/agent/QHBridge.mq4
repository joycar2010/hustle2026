//+------------------------------------------------------------------+
//|  QHBridge.mq4 — QH 自建 MT4 桥 EA(终端内)                        |
//|                                                                  |
//|  职责:把 MT4 账户/持仓/报价/品种信息导出到文件桥,供本地 Python |
//|  Agent 复刻 mt5-bridge 的 /mt5/* 协议。文件桥根 = MQL4\Files\    |
//|  qhbridge\。Phase B = 只读状态导出(无下单);Phase D 加命令处理。|
//|                                                                  |
//|  时钟:ts 用 TimeLocal()(终端本机时);部署机 GMT+0 ≈ UTC,      |
//|  Agent 以 time.time() 比对新鲜度。tick.time 用券商服务器时       |
//|  (GMT+3),消费端沿用 MT5 桥 +10800000ms 校正。                   |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "QH self-hosted MT4 bridge — state exporter (Phase B, read-only)"

input int    TimerMs      = 100;          // OnTimer 周期(ms)
input string BridgeSubdir = "qhbridge";   // MQL4\Files\ 下的桥目录
input int    SymbolsEveryN= 10;           // 每 N 次 OnTimer 刷一次 symbols(低频)

string  g_watch[];      // 要导出的符号(来自 watch.json + 图表符号)
int     g_tick_count = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   EventSetMillisecondTimer(TimerMs);
   LoadWatch();
   ExportMeta();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   LoadWatch();
   ExportMeta();
   ExportAccount();
   ExportPositions();
   ExportTicks();
   g_tick_count++;
   if(g_tick_count % SymbolsEveryN == 0)
      ExportSymbols();
   ProcessCommands();   // Phase D:处理 Agent 投递的下单/平仓命令
}

void OnTick()
{
   // 图表符号来 tick 时顺手刷一次报价,降低该符号延迟
   ExportTicks();
}

//====================== 状态导出 ======================

void ExportMeta()
{
   bool connected = IsConnected() && (AccountNumber() > 0);
   string j = "{";
   j += "\"connected\":"      + (connected ? "true" : "false");
   j += ",\"account\":"       + IntegerToString(AccountNumber());
   j += ",\"server\":"        + JStr(AccountServer());
   j += ",\"company\":"       + JStr(AccountCompany());
   j += ",\"last_ok_at\":"    + JStr(TimeToString(TimeLocal(), TIME_DATE|TIME_SECONDS));
   j += ",\"ts\":"            + IntegerToString((long)TimeLocal());
   j += ",\"ea\":\"QHBridge/0.10\"";
   j += "}";
   WriteState("meta", j);
}

void ExportAccount()
{
   double mlevel = (AccountMargin() > 0.0) ? (AccountEquity() / AccountMargin() * 100.0) : 0.0;

   // 累计 swap = 持仓 swap + 近30日历史 swap(复刻 mt5-bridge account_info)
   double total_swap = 0.0;
   for(int i = 0; i < OrdersTotal(); i++)
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && OrderType() <= OP_SELL)
         total_swap += OrderSwap();
   datetime from30 = TimeCurrent() - 30*24*3600;
   for(int h = 0; h < OrdersHistoryTotal(); h++)
      if(OrderSelect(h, SELECT_BY_POS, MODE_HISTORY) && OrderOpenTime() >= from30)
         total_swap += OrderSwap();

   string j = "{";
   j += "\"login\":"          + IntegerToString(AccountNumber());
   j += ",\"balance\":"       + DoubleToString(AccountBalance(), 2);
   j += ",\"equity\":"        + DoubleToString(AccountEquity(), 2);
   j += ",\"margin\":"        + DoubleToString(AccountMargin(), 2);
   j += ",\"margin_free\":"   + DoubleToString(AccountFreeMargin(), 2);
   j += ",\"margin_level\":"  + DoubleToString(mlevel, 2);
   j += ",\"margin_so_call\":null";                                  // MT4 不单列预警线
   j += ",\"margin_so_so\":"  + DoubleToString(AccountStopoutLevel(), 2);  // 止损平仓线
   j += ",\"margin_so_mode\":" + IntegerToString(AccountStopoutMode());    // 0=% 1=货币
   j += ",\"profit\":"        + DoubleToString(AccountProfit(), 2);
   j += ",\"swap\":"          + DoubleToString(total_swap, 2);
   j += ",\"currency\":"      + JStr(AccountCurrency());
   j += ",\"leverage\":"      + IntegerToString(AccountLeverage());
   j += ",\"server\":"        + JStr(AccountServer());
   j += ",\"name\":"          + JStr(AccountName());
   j += ",\"company\":"       + JStr(AccountCompany());
   j += ",\"ts\":"            + IntegerToString((long)TimeLocal());
   j += "}";
   WriteState("account", j);
}

void ExportPositions()
{
   string arr = "";
   int n = 0;
   for(int i = 0; i < OrdersTotal(); i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderType() > OP_SELL) continue;   // 只导市价持仓(排除挂单)
      if(n > 0) arr += ",";
      arr += "{";
      arr += "\"ticket\":"        + IntegerToString(OrderTicket());
      arr += ",\"symbol\":"       + JStr(OrderSymbol());
      arr += ",\"type\":"         + IntegerToString(OrderType());       // 0=BUY 1=SELL(与 MT5 一致)
      arr += ",\"volume\":"       + DoubleToString(OrderLots(), 2);
      arr += ",\"price_open\":"   + DoubleToString(OrderOpenPrice(), 5);
      arr += ",\"price_current\":" + DoubleToString(OrderClosePrice(), 5);
      arr += ",\"profit\":"       + DoubleToString(OrderProfit(), 2);
      arr += ",\"swap\":"         + DoubleToString(OrderSwap(), 2);
      arr += ",\"sl\":"           + DoubleToString(OrderStopLoss(), 5);
      arr += ",\"tp\":"           + DoubleToString(OrderTakeProfit(), 5);
      arr += ",\"margin\":0.0";
      arr += ",\"price_liquidation\":0.0";
      arr += ",\"time\":"         + IntegerToString((long)OrderOpenTime());
      arr += ",\"comment\":"      + JStr(OrderComment());
      arr += "}";
      n++;
   }
   string j = "{\"positions\":[" + arr + "],\"ts\":" + IntegerToString((long)TimeLocal()) + "}";
   WriteState("positions", j);
}

void ExportTicks()
{
   string body = "";
   int n = 0;
   for(int i = 0; i < ArraySize(g_watch); i++)
   {
      string sym = g_watch[i];
      if(sym == "") continue;
      SymbolSelect(sym, true);   // 确保在 Market Watch,MarketInfo 才有数
      double bid = MarketInfo(sym, MODE_BID);
      double ask = MarketInfo(sym, MODE_ASK);
      if(bid <= 0.0 && ask <= 0.0) continue;
      long   tt  = (long)MarketInfo(sym, MODE_TIME);   // 券商服务器时(秒)
      long   vol = iVolume(sym, PERIOD_M1, 0);          // MT4 无 tick 量 MarketInfo,取 M1 tick 数作代理
      if(n > 0) body += ",";
      body += JStr(sym) + ":{";
      body += "\"bid\":"    + DoubleToString(bid, 5);
      body += ",\"ask\":"   + DoubleToString(ask, 5);
      body += ",\"last\":0.0";
      body += ",\"volume\":" + IntegerToString(vol);
      body += ",\"time\":"  + IntegerToString(tt);
      body += "}";
      n++;
   }
   string j = "{\"ticks\":{" + body + "},\"ts\":" + IntegerToString((long)TimeLocal()) + "}";
   WriteState("ticks", j);
}

void ExportSymbols()
{
   string body = "";
   int n = 0;
   for(int i = 0; i < ArraySize(g_watch); i++)
   {
      string sym = g_watch[i];
      if(sym == "") continue;
      SymbolSelect(sym, true);
      double digits = MarketInfo(sym, MODE_DIGITS);
      if(digits <= 0.0 && MarketInfo(sym, MODE_BID) <= 0.0) continue;
      bool tradeok = (MarketInfo(sym, MODE_TRADEALLOWED) != 0.0);
      if(n > 0) body += ",";
      body += JStr(sym) + ":{";
      body += "\"symbol\":"              + JStr(sym);
      body += ",\"description\":\"\"";
      body += ",\"digits\":"             + IntegerToString((int)digits);
      body += ",\"point\":"              + DoubleToString(MarketInfo(sym, MODE_POINT), 8);
      body += ",\"volume_min\":"         + DoubleToString(MarketInfo(sym, MODE_MINLOT), 2);
      body += ",\"volume_max\":"         + DoubleToString(MarketInfo(sym, MODE_MAXLOT), 2);
      body += ",\"volume_step\":"        + DoubleToString(MarketInfo(sym, MODE_LOTSTEP), 2);
      body += ",\"trade_contract_size\":" + DoubleToString(MarketInfo(sym, MODE_LOTSIZE), 2);
      body += ",\"swap_long\":"          + DoubleToString(MarketInfo(sym, MODE_SWAPLONG), 4);
      body += ",\"swap_short\":"         + DoubleToString(MarketInfo(sym, MODE_SWAPSHORT), 4);
      body += ",\"swap_mode\":"          + IntegerToString((int)MarketInfo(sym, MODE_SWAPTYPE));
      body += ",\"swap_rollover3days\":3";                 // MT4 三倍隔夜费固定周三,给约定值
      body += ",\"currency_base\":\"\"";                   // MT4 MarketInfo 不暴露,留空
      body += ",\"currency_profit\":\"\"";
      body += ",\"currency_margin\":\"\"";
      body += ",\"visible\":true";
      body += ",\"trade_mode\":"         + (tradeok ? "4" : "0");  // 4=FULL 复刻 MT5 枚举
      body += ",\"trade_allowed\":"      + (tradeok ? "true" : "false");
      body += "}";
      n++;
   }
   string j = "{\"symbols\":{" + body + "},\"ts\":" + IntegerToString((long)TimeLocal()) + "}";
   WriteState("symbols", j);
}

//====================== watch.json 读取 ======================

void LoadWatch()
{
   // 始终含图表符号
   string syms[];
   ArrayResize(syms, 1);
   syms[0] = Symbol();

   string path = BridgeSubdir + "\\watch.json";
   int h = FileOpen(path, FILE_READ|FILE_TXT|FILE_ANSI);
   if(h != INVALID_HANDLE)
   {
      string content = "";
      while(!FileIsEnding(h)) content += FileReadString(h);
      FileClose(h);
      // 极简提取:收集所有双引号 token,丢掉字面量 "symbols"
      ExtractQuoted(content, syms);
   }
   // 去重赋给 g_watch
   ArrayResize(g_watch, 0);
   for(int i = 0; i < ArraySize(syms); i++)
   {
      if(syms[i] == "" || syms[i] == "symbols") continue;
      bool dup = false;
      for(int k = 0; k < ArraySize(g_watch); k++)
         if(g_watch[k] == syms[i]) { dup = true; break; }
      if(!dup)
      {
         int sz = ArraySize(g_watch);
         ArrayResize(g_watch, sz+1);
         g_watch[sz] = syms[i];
      }
   }
}

// 把 content 里所有 "xxx" 追加进 out[]
void ExtractQuoted(string content, string &out[])
{
   int len = StringLen(content);
   int i = 0;
   while(i < len)
   {
      if(StringGetCharacter(content, i) == '"')
      {
         int j = i + 1;
         string tok = "";
         while(j < len && StringGetCharacter(content, j) != '"')
         {
            tok += CharToString((uchar)StringGetCharacter(content, j));
            j++;
         }
         int sz = ArraySize(out);
         ArrayResize(out, sz+1);
         out[sz] = tok;
         i = j + 1;
      }
      else i++;
   }
}

//====================== 文件桥写(原子)======================

void WriteState(string name, string json)
{
   string rel = BridgeSubdir + "\\state\\" + name + ".json";
   string tmp = rel + ".tmp";
   int h = FileOpen(tmp, FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h == INVALID_HANDLE) return;
   FileWriteString(h, json);
   FileClose(h);
   FileDelete(rel);
   FileMove(tmp, 0, rel, FILE_REWRITE);
}

// JSON 字符串字面量(转义 " 与 \)
string JStr(string s)
{
   string o = "\"";
   int len = StringLen(s);
   for(int i = 0; i < len; i++)
   {
      ushort c = StringGetCharacter(s, i);
      if(c == '"')       o += "\\\"";
      else if(c == '\\') o += "\\\\";
      else if(c >= 32 && c < 127) o += CharToString((uchar)c);
      // 非 ASCII 丢弃(broker 字段基本 ASCII;保 JSON UTF-8 有效)
   }
   o += "\"";
   return o;
}

//====================== 命令处理(Phase D)======================
// Agent 投 commands\{id}.json,EA 执行后写 results\{id}.json(tombstone)删命令。
// 幂等对账:OrderSend 打 magic=login + comment=otoken;崩溃/超时后按 comment 含 otoken 认领,防重开。

void ProcessCommands()
{
   string fn;
   long h = FileFindFirst(BridgeSubdir + "\\commands\\*.json", fn);
   if(h == INVALID_HANDLE) return;
   string files[]; int n = 0;
   do {
      if(StringFind(fn, ".tmp") < 0) { ArrayResize(files, n+1); files[n] = fn; n++; }
   } while(FileFindNext(h, fn));
   FileFindClose(h);
   for(int i = 0; i < n; i++) HandleCommand(files[i]);
}

void HandleCommand(string fname)
{
   string cmd_id = fname;
   int dot = StringFind(fname, ".json");
   if(dot >= 0) cmd_id = StringSubstr(fname, 0, dot);
   string path = BridgeSubdir + "\\commands\\" + fname;
   int fh = FileOpen(path, FILE_READ|FILE_TXT|FILE_ANSI);
   if(fh == INVALID_HANDLE) return;
   string j = "";
   while(!FileIsEnding(fh)) j += FileReadString(fh);
   FileClose(fh);
   if(StringLen(j) < 2) return;   // 半写,下轮再处理

   string op = JGetStr(j, "op");
   string otoken = JGetStr(j, "otoken");
   string result;
   if(op == "order")           result = ExecOrder(j, otoken);
   else if(op == "close")      result = ExecClose(j);
   else if(op == "close_all")  result = ExecCloseAll(j);
   else if(op == "cancel_all") result = ExecCancelAll(j);
   else result = "{\"ok\":false,\"error\":\"unknown op\"}";

   WriteResult(cmd_id, result);
   FileDelete(path);
}

int SlipFor(string sym)
{
   int digits = (int)MarketInfo(sym, MODE_DIGITS);
   int e = digits - 2; if(e < 0) e = 0;
   return (int)(50 * MathPow(10, e));   // 2位=50 / 3位=500 点(防REQUOTE,见记忆)
}

int FindByToken(string otoken)
{
   if(otoken == "") return -1;
   for(int i = 0; i < OrdersTotal(); i++)
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && StringFind(OrderComment(), otoken) >= 0)
         return OrderTicket();
   for(int h = 0; h < OrdersHistoryTotal(); h++)
      if(OrderSelect(h, SELECT_BY_POS, MODE_HISTORY) && StringFind(OrderComment(), otoken) >= 0)
         return OrderTicket();
   return -1;
}

string ExecOrder(string j, string otoken)
{
   // 幂等对账:已有单(comment 含 otoken)直接认领,绝不重开
   int existing = FindByToken(otoken);
   if(existing >= 0 && OrderSelect(existing, SELECT_BY_TICKET))
      return "{\"ok\":true,\"op\":\"order\",\"ticket\":" + IntegerToString(existing) +
             ",\"price\":" + DoubleToString(OrderOpenPrice(), 5) +
             ",\"volume\":" + DoubleToString(OrderLots(), 2) +
             ",\"retcode\":10009,\"partial\":false,\"reconciled\":true}";

   string sym  = JGetStr(j, "symbol");
   string side = JGetStr(j, "side");
   double vol  = JGetNum(j, "volume");
   SymbolSelect(sym, true);
   int    cmd  = (side == "sell") ? OP_SELL : OP_BUY;
   double price = (cmd == OP_BUY) ? MarketInfo(sym, MODE_ASK) : MarketInfo(sym, MODE_BID);
   double sl = JGetNum(j, "sl");
   double tp = JGetNum(j, "tp");
   int    slip = SlipFor(sym);
   int    ticket = OrderSend(sym, cmd, vol, price, slip, sl, tp, otoken, (int)AccountNumber(), 0, clrNONE);
   if(ticket < 0)
   {
      int err = GetLastError();
      return "{\"ok\":false,\"op\":\"order\",\"retcode\":" + IntegerToString(err) +
             ",\"error\":\"OrderSend err " + IntegerToString(err) + "\"}";
   }
   double oprice = price, ovol = vol;
   if(OrderSelect(ticket, SELECT_BY_TICKET)) { oprice = OrderOpenPrice(); ovol = OrderLots(); }
   return "{\"ok\":true,\"op\":\"order\",\"ticket\":" + IntegerToString(ticket) +
          ",\"price\":" + DoubleToString(oprice, 5) +
          ",\"volume\":" + DoubleToString(ovol, 2) +
          ",\"requested_volume\":" + DoubleToString(vol, 2) +
          ",\"retcode\":10009,\"partial\":false,\"reconciled\":false}";
}

string ExecClose(string j)
{
   int tk = (int)JGetNum(j, "ticket");
   if(tk > 0)
   {
      if(!OrderSelect(tk, SELECT_BY_TICKET))
         return "{\"ok\":true,\"op\":\"close\",\"ticket\":" + IntegerToString(tk) + ",\"reconciled\":true,\"note\":\"not found=closed\",\"retcode\":10009}";
      if(OrderCloseTime() != 0)
         return "{\"ok\":true,\"op\":\"close\",\"ticket\":" + IntegerToString(tk) + ",\"reconciled\":true,\"note\":\"already closed\",\"retcode\":10009}";
      string sym = OrderSymbol();
      double cprice = (OrderType() == OP_BUY) ? MarketInfo(sym, MODE_BID) : MarketInfo(sym, MODE_ASK);
      double lots = OrderLots();
      if(OrderClose(tk, lots, cprice, SlipFor(sym), clrNONE))
         return "{\"ok\":true,\"op\":\"close\",\"ticket\":" + IntegerToString(tk) + ",\"price\":" + DoubleToString(cprice,5) + ",\"volume\":" + DoubleToString(lots,2) + ",\"retcode\":10009}";
      return "{\"ok\":false,\"op\":\"close\",\"retcode\":" + IntegerToString(GetLastError()) + "}";
   }
   string sym2 = JGetStr(j, "symbol");
   string side = JGetStr(j, "side");
   int    target = (side == "sell") ? OP_BUY : OP_SELL;   // side=sell 平多(OP_BUY)
   for(int i = OrdersTotal()-1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderSymbol() != sym2 || OrderType() != target) continue;
      int tkt = OrderTicket(); double lots = OrderLots();
      double cprice = (OrderType() == OP_BUY) ? MarketInfo(sym2, MODE_BID) : MarketInfo(sym2, MODE_ASK);
      if(OrderClose(tkt, lots, cprice, SlipFor(sym2), clrNONE))
         return "{\"ok\":true,\"op\":\"close\",\"ticket\":" + IntegerToString(tkt) + ",\"price\":" + DoubleToString(cprice,5) + ",\"volume\":" + DoubleToString(lots,2) + ",\"retcode\":10009}";
      return "{\"ok\":false,\"op\":\"close\",\"retcode\":" + IntegerToString(GetLastError()) + "}";
   }
   return "{\"ok\":false,\"op\":\"close\",\"error\":\"no matching position\"}";
}

string ExecCloseAll(string j)
{
   string sym = JGetStr(j, "symbol");   // "" = 全部
   int closed = 0, failed = 0; string arr = "";
   for(int i = OrdersTotal()-1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderType() > OP_SELL) continue;
      if(sym != "" && OrderSymbol() != sym) continue;
      int tkt = OrderTicket(); double lots = OrderLots(); string s = OrderSymbol();
      double cprice = (OrderType() == OP_BUY) ? MarketInfo(s, MODE_BID) : MarketInfo(s, MODE_ASK);
      if(arr != "") arr += ",";
      if(OrderClose(tkt, lots, cprice, SlipFor(s), clrNONE)) { closed++; arr += "{\"ticket\":" + IntegerToString(tkt) + ",\"success\":true,\"order\":" + IntegerToString(tkt) + "}"; }
      else { failed++; arr += "{\"ticket\":" + IntegerToString(tkt) + ",\"success\":false,\"retcode\":" + IntegerToString(GetLastError()) + "}"; }
   }
   return "{\"ok\":true,\"op\":\"close_all\",\"closed\":" + IntegerToString(closed) + ",\"failed\":" + IntegerToString(failed) + ",\"results\":[" + arr + "]}";
}

string ExecCancelAll(string j)
{
   string sym = JGetStr(j, "symbol");
   int cancelled = 0, failed = 0;
   for(int i = OrdersTotal()-1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderType() <= OP_SELL) continue;   // 只挂单
      if(sym != "" && OrderSymbol() != sym) continue;
      if(OrderDelete(OrderTicket())) cancelled++; else failed++;
   }
   return "{\"ok\":true,\"op\":\"cancel_all\",\"cancelled\":" + IntegerToString(cancelled) + ",\"failed\":" + IntegerToString(failed) + "}";
}

void WriteResult(string cmd_id, string json)
{
   string rel = BridgeSubdir + "\\results\\" + cmd_id + ".json";
   string tmp = rel + ".tmp";
   int h = FileOpen(tmp, FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h == INVALID_HANDLE) return;
   FileWriteString(h, json);
   FileClose(h);
   FileDelete(rel);
   FileMove(tmp, 0, rel, FILE_REWRITE);
}

// ── 极简 JSON 取值(命令对象扁平,Agent 生成)──
string JGetStr(string j, string key)
{
   string pat = "\"" + key + "\":";
   int p = StringFind(j, pat);
   if(p < 0) return "";
   p += StringLen(pat);
   int len = StringLen(j);
   while(p < len && StringGetCharacter(j, p) == ' ') p++;
   if(p >= len || StringGetCharacter(j, p) != '"') return "";   // null/非串
   p++;
   string o = "";
   while(p < len)
   {
      ushort ch = StringGetCharacter(j, p);
      if(ch == '"') break;
      if(ch == '\\') { p++; ch = StringGetCharacter(j, p); }
      o += CharToString((uchar)ch);
      p++;
   }
   return o;
}

double JGetNum(string j, string key)
{
   string pat = "\"" + key + "\":";
   int p = StringFind(j, pat);
   if(p < 0) return 0.0;
   p += StringLen(pat);
   int len = StringLen(j);
   while(p < len && StringGetCharacter(j, p) == ' ') p++;
   string num = "";
   while(p < len)
   {
      ushort ch = StringGetCharacter(j, p);
      if((ch >= '0' && ch <= '9') || ch == '.' || ch == '-' || ch == '+' || ch == 'e' || ch == 'E')
         num += CharToString((uchar)ch);
      else break;
      p++;
   }
   if(num == "") return 0.0;
   return StringToDouble(num);
}
//+------------------------------------------------------------------+
