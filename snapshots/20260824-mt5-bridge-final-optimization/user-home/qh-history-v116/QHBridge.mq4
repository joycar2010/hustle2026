//+------------------------------------------------------------------+
//|  QHBridge.mq4 鈥?QH 鑷缓 MT4 妗?EA(缁堢鍐?                        |
//|                                                                  |
//|  ?岃矗:鎶?MT4 璐︽埛/鎸?浠?鎶ヤ环/鍝?绉?淇℃?鍑哄埌鏂囦欢妗?渚涙湰鍦?Python |
//|  Agent 澶?鍒?mt5-bridge 鐨?/mt5/* ??璁€傛枃浠舵ˉ鏍?= MQL4\Files\    |
//|  qhbridge\銆侾hase B = ?鐘舵€?瀵煎嚭(鏃犱笅??;Phase D 鍔犲懡浠ゅ?嗐€倈
//|                                                                  |
//|  鏃堕挓:ts 鐢?TimeLocal()(缁堢鏈満鏃?;閮ㄧ讲鏈?GMT+0 鈮?UTC,      |
//|  Agent 浠?time.time() 姣斿鏂伴矞搴︺€倀ick.time 鐢ㄥ埜鍟嗘?鍔″櫒鏃?      |
//|  (GMT+3),娑堣垂绔部鐢?MT5 妗?+10800000ms 鏍℃銆?                  |
//+------------------------------------------------------------------+
#property strict
#property version   "1.16"
#property description "QH self-hosted MT4 bridge - command-first subsecond scheduler"

input int    TimerMs      = 25;           // command pickup cadence
input string BridgeSubdir = "qhbridge";   // MQL4\Files\ 涓嬬殑妗ョ洰褰?
input int    TickEveryMs  = 100;
input int    PositionEveryMs = 250;
input int    AccountEveryMs  = 1000;
input int    WatchEveryMs    = 1000;
input int    HistoryEveryMs  = 10000;         // low-priority broker history refresh
input int    HistoryLookbackDays = 30;
input int    HistoryMaxOrders = 3000;
input int    HistoryBatchOrders = 20;         // bound each idle timer slice
input int    RequoteRetries  = 1;          // Retry only MT4 error 138 after refreshing quotes
input int    RequoteRetryMs  = 25;

string  g_watch[];      // 瑕?瀵煎嚭鐨勭???ヨ嚜 watch.json + 鍥捐〃绗﹀??
uint    g_last_tick_ms = 0;
uint    g_last_position_ms = 0;
uint    g_last_account_ms = 0;
uint    g_last_watch_ms = 0;
uint    g_last_history_ms = 0;
ulong   g_perf_command_ms = 0;
ulong   g_perf_positions_ms = 0;
ulong   g_perf_ticks_ms = 0;
ulong   g_perf_heartbeat_ms = 0;
ulong   g_perf_meta_ms = 0;
ulong   g_perf_account_ms = 0;
ulong   g_perf_watch_ms = 0;
ulong   g_perf_history_ms = 0;
ulong   g_perf_loop_ms = 0;
long    g_snapshot_boot = 0;
long    g_position_seq = 0;
bool    g_history_dirty = true;
bool    g_history_scan_active = false;
int     g_history_cursor = -1;
int     g_history_scanned = 0;
int     g_history_total = 0;
int     g_history_deal_count = 0;
int     g_history_order_count = 0;
long    g_history_cutoff = 0;
string  g_history_deals = "";
string  g_history_orders = "";

//+------------------------------------------------------------------+
int OnInit()
{
   g_snapshot_boot = (long)TimeLocal() * 1000000 + (long)(GetMicrosecondCount() % 1000000);
   EventSetMillisecondTimer(MathMax(10, MathMin(TimerMs, 25)));
   LoadWatch();
   ExportMeta();
   ExportAccountFast();
   ExportPositions();
   ExportTicks();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   // MQL4 events are serial, so trading commands always run before snapshots.
   ulong loop_start_us = GetMicrosecondCount();
   ulong stage_start_us = loop_start_us;
   bool traded = ProcessOneCommand();
   if(traded) g_history_dirty = true;
   TrackMax(g_perf_command_ms, ElapsedMs(stage_start_us));
   uint now_ms = GetTickCount();

   if(traded || now_ms - g_last_position_ms >= (uint)PositionEveryMs)
   {
      stage_start_us = GetMicrosecondCount();
      ExportPositions();
      TrackMax(g_perf_positions_ms, ElapsedMs(stage_start_us));
      g_last_position_ms = now_ms;
   }
   if(now_ms - g_last_tick_ms >= (uint)TickEveryMs)
   {
      stage_start_us = GetMicrosecondCount();
      ExportTicks();
      TrackMax(g_perf_ticks_ms, ElapsedMs(stage_start_us));
      g_last_tick_ms = now_ms;
   }
   bool account_due = traded || now_ms - g_last_account_ms >= (uint)AccountEveryMs;
   if(account_due)
   {
      stage_start_us = GetMicrosecondCount();
      ExportHeartbeat();
      TrackMax(g_perf_heartbeat_ms, ElapsedMs(stage_start_us));
      stage_start_us = GetMicrosecondCount();
      ExportMeta();
      TrackMax(g_perf_meta_ms, ElapsedMs(stage_start_us));
      stage_start_us = GetMicrosecondCount();
      ExportAccountFast();
      TrackMax(g_perf_account_ms, ElapsedMs(stage_start_us));
      g_last_account_ms = now_ms;
   }
   if(now_ms - g_last_watch_ms >= (uint)WatchEveryMs)
   {
      stage_start_us = GetMicrosecondCount();
      LoadWatch();
      TrackMax(g_perf_watch_ms, ElapsedMs(stage_start_us));
      g_last_watch_ms = now_ms;
   }
   if(!traded && (g_history_scan_active || g_history_dirty ||
      now_ms - g_last_history_ms >= (uint)MathMax(1000, HistoryEveryMs)))
   {
      stage_start_us = GetMicrosecondCount();
      ExportHistoryStep();
      TrackMax(g_perf_history_ms, ElapsedMs(stage_start_us));
   }
   TrackMax(g_perf_loop_ms, ElapsedMs(loop_start_us));
   if(account_due) ExportSchedulerPerf();
}

void OnTick()
{
   // Some MT4 terminals delay Timer delivery while quote events remain active.
   // Commands are idempotent and events are serialized, so ticks provide a safe
   // second wake-up path without restoring any state-file writes to OnTick.
   if(ProcessOneCommand()) g_history_dirty = true;
}

//====================== 鐘舵€?瀵煎嚭 ======================


//+------------------------------------------------------------------+
//| P0-B: ????? ??? IsConnected()==false ???              |
//| ?? EA ???? vs MT4 Broker ????                           |
//+------------------------------------------------------------------+
void ExportHeartbeat()
{
   string j = "{";
   j += "\"ea_alive\":true";
   j += ",\"ts\":" + IntegerToString(TimeCurrent());
   j += ",\"ea\":\"QHBridge/1.16\"";
   j += ",\"account\":" + IntegerToString(AccountNumber());
   j += ",\"connected\":" + (IsConnected() ? "true" : "false");
   j += "}";
   WriteState("heartbeat", j);
}

void ExportMeta()
{
   bool connected = IsConnected() && (AccountNumber() > 0);
   string j = "{";
   j += "\"connected\":"      + (connected ? "true" : "false");
   j += ",\"account\":"       + IntegerToString(AccountNumber());
   j += ",\"server\":"        + JStr(AccountServer());
   j += ",\"company\":"       + JStr(AccountCompany());
   j += ",\"trade_allowed\":" + (IsTradeAllowed() ? "true" : "false");
   j += ",\"last_ok_at\":"    + JStr(TimeToString(TimeLocal(), TIME_DATE|TIME_SECONDS));
   j += ",\"ts\":"            + IntegerToString((long)TimeLocal());
   j += ",\"ea\":\"QHBridge/1.16\"";
   j += "}";
   WriteState("meta", j);
}

void ExportAccountFast()
{
   double mlevel = (AccountMargin() > 0.0) ? (AccountEquity() / AccountMargin() * 100.0) : 0.0;

   // Keep broker history out of the trading EA event loop. This is open-position swap only.
   double total_swap = 0.0;
   for(int i = 0; i < OrdersTotal(); i++)
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && OrderType() <= OP_SELL)
         total_swap += OrderSwap();
   string j = "{";
   j += "\"login\":"          + IntegerToString(AccountNumber());
   j += ",\"balance\":"       + DoubleToString(AccountBalance(), 2);
   j += ",\"equity\":"        + DoubleToString(AccountEquity(), 2);
   j += ",\"margin\":"        + DoubleToString(AccountMargin(), 2);
   j += ",\"margin_free\":"   + DoubleToString(AccountFreeMargin(), 2);
   j += ",\"margin_level\":"  + DoubleToString(mlevel, 2);
   j += ",\"margin_so_call\":null";                                  // MT4 涓??曞垪棰勮绾?
   j += ",\"margin_so_so\":"  + DoubleToString(AccountStopoutLevel(), 2);  // 姝㈡?熷钩浠撶嚎
   j += ",\"margin_so_mode\":" + IntegerToString(AccountStopoutMode());    // 0=% 1=璐у?
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

ulong ElapsedMs(ulong started_us)
{
   ulong now_us = GetMicrosecondCount();
   return (now_us >= started_us) ? (now_us - started_us) / 1000 : 0;
}

void TrackMax(ulong &target, ulong value)
{
   if(value > target) target = value;
}

void ExportSchedulerPerf()
{
   string j = "{";
   j += "\"command_max_ms\":" + IntegerToString((long)g_perf_command_ms);
   j += ",\"positions_max_ms\":" + IntegerToString((long)g_perf_positions_ms);
   j += ",\"ticks_max_ms\":" + IntegerToString((long)g_perf_ticks_ms);
   j += ",\"heartbeat_max_ms\":" + IntegerToString((long)g_perf_heartbeat_ms);
   j += ",\"meta_max_ms\":" + IntegerToString((long)g_perf_meta_ms);
   j += ",\"account_max_ms\":" + IntegerToString((long)g_perf_account_ms);
   j += ",\"watch_max_ms\":" + IntegerToString((long)g_perf_watch_ms);
   j += ",\"history_max_ms\":" + IntegerToString((long)g_perf_history_ms);
   j += ",\"loop_max_ms\":" + IntegerToString((long)g_perf_loop_ms);
   j += ",\"ts\":" + IntegerToString((long)TimeLocal()) + "}";
   WriteState("scheduler_perf", j);
   g_perf_command_ms = 0;
   g_perf_positions_ms = 0;
   g_perf_ticks_ms = 0;
   g_perf_heartbeat_ms = 0;
   g_perf_meta_ms = 0;
   g_perf_account_ms = 0;
   g_perf_watch_ms = 0;
   g_perf_history_ms = 0;
   g_perf_loop_ms = 0;
}

void ExportPositions()
{
   g_position_seq++;
   string arr = "";
   int n = 0;
   for(int i = 0; i < OrdersTotal(); i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderType() > OP_SELL) continue;   // ?甯備环鎸?浠?鎺掗櫎鎸傚??
      if(n > 0) arr += ",";
      arr += "{";
      arr += "\"ticket\":"        + IntegerToString(OrderTicket());
      arr += ",\"symbol\":"       + JStr(OrderSymbol());
      arr += ",\"type\":"         + IntegerToString(OrderType());       // 0=BUY 1=SELL(涓?MT5 涓€鑷?
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
   string j = "{\"positions\":[" + arr + "]";
   j += ",\"snapshot_boot\":" + IntegerToString(g_snapshot_boot);
   j += ",\"snapshot_seq\":" + IntegerToString(g_position_seq);
   j += ",\"snapshot_ts\":" + IntegerToString((long)TimeLocal());
   j += ",\"ts\":" + IntegerToString((long)TimeLocal()) + "}";
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
      double bid = MarketInfo(sym, MODE_BID);
      double ask = MarketInfo(sym, MODE_ASK);
      if(bid <= 0.0 && ask <= 0.0) continue;
      long   tt  = (long)MarketInfo(sym, MODE_TIME);   // 鍒稿晢鏈?鍔″櫒鏃?绉?
      if(n > 0) body += ",";
      body += JStr(sym) + ":{";
      body += "\"bid\":"    + DoubleToString(bid, 5);
      body += ",\"ask\":"   + DoubleToString(ask, 5);
      body += ",\"last\":0.0";
      // iVolume() can synchronously load remote history for every watched symbol.
      // Volume is not used for execution, so keep the trading scheduler bounded.
      body += ",\"volume\":0";
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
      body += ",\"swap_rollover3days\":3";                 // MT4 涓夊€?闅斿璐瑰浐瀹氬懆涓?缁欑害瀹氬€?
      body += ",\"currency_base\":\"\"";                   // MT4 MarketInfo 涓?鏆撮湶,鐣欑┖
      body += ",\"currency_profit\":\"\"";
      body += ",\"currency_margin\":\"\"";
      body += ",\"visible\":true";
      body += ",\"trade_mode\":"         + (tradeok ? "4" : "0");  // 4=FULL 澶?鍒?MT5 鏋氫妇
      body += ",\"trade_allowed\":"      + (tradeok ? "true" : "false");
      body += "}";
      n++;
   }
   string j = "{\"symbols\":{" + body + "},\"ts\":" + IntegerToString((long)TimeLocal()) + "}";
   WriteState("symbols", j);
}

//====================== watch.json 璇诲??======================

string HistoryDealJson(int entry)
{
   bool closing = (entry == 1);
   string j = "{";
   j += "\"ticket\":" + IntegerToString(OrderTicket());
   j += ",\"order\":" + IntegerToString(OrderTicket());
   j += ",\"symbol\":" + JStr(OrderSymbol());
   j += ",\"type\":" + IntegerToString(OrderType());
   j += ",\"entry\":" + IntegerToString(entry);
   j += ",\"volume\":" + DoubleToString(OrderLots(), 2);
   j += ",\"price\":" + DoubleToString(closing ? OrderClosePrice() : OrderOpenPrice(), 5);
   j += ",\"profit\":" + DoubleToString(closing ? OrderProfit() : 0.0, 2);
   j += ",\"swap\":" + DoubleToString(closing ? OrderSwap() : 0.0, 2);
   j += ",\"commission\":" + DoubleToString(closing ? OrderCommission() : 0.0, 2);
   j += ",\"time\":" + IntegerToString((long)(closing ? OrderCloseTime() : OrderOpenTime()));
   j += ",\"comment\":" + JStr(OrderComment());
   j += ",\"magic\":" + IntegerToString(OrderMagicNumber());
   j += "}";
   return j;
}

string HistoryOrderJson()
{
   string j = "{";
   j += "\"ticket\":" + IntegerToString(OrderTicket());
   j += ",\"order\":" + IntegerToString(OrderTicket());
   j += ",\"symbol\":" + JStr(OrderSymbol());
   j += ",\"type\":" + IntegerToString(OrderType());
   j += ",\"entry\":1";
   j += ",\"volume\":" + DoubleToString(OrderLots(), 2);
   j += ",\"volume_initial\":" + DoubleToString(OrderLots(), 2);
   j += ",\"volume_current\":0.0";
   j += ",\"price\":" + DoubleToString(OrderClosePrice(), 5);
   j += ",\"price_open\":" + DoubleToString(OrderOpenPrice(), 5);
   j += ",\"profit\":" + DoubleToString(OrderProfit(), 2);
   j += ",\"swap\":" + DoubleToString(OrderSwap(), 2);
   j += ",\"commission\":" + DoubleToString(OrderCommission(), 2);
   j += ",\"time\":" + IntegerToString((long)OrderCloseTime());
   j += ",\"time_setup\":" + IntegerToString((long)OrderOpenTime());
   j += ",\"time_done\":" + IntegerToString((long)OrderCloseTime());
   j += ",\"sl\":" + DoubleToString(OrderStopLoss(), 5);
   j += ",\"tp\":" + DoubleToString(OrderTakeProfit(), 5);
   j += ",\"comment\":" + JStr(OrderComment());
   j += ",\"magic\":" + IntegerToString(OrderMagicNumber());
   j += "}";
   return j;
}

void StartHistoryExport()
{
   g_history_total = OrdersHistoryTotal();
   g_history_cursor = g_history_total - 1;
   g_history_scanned = 0;
   g_history_deal_count = 0;
   g_history_order_count = 0;
   g_history_deals = "";
   g_history_orders = "";
   long broker_now = (long)TimeCurrent();
   if(broker_now <= 0) broker_now = (long)TimeLocal();
   g_history_cutoff = broker_now - (long)MathMax(1, HistoryLookbackDays) * 86400;
   g_history_scan_active = true;
}

void FinishHistoryExport()
{
   bool truncated = (g_history_cursor >= 0);
   string deals = "{\"deals\":[" + g_history_deals + "]";
   deals += ",\"count\":" + IntegerToString(g_history_deal_count);
   deals += ",\"lookback_days\":" + IntegerToString(MathMax(1, HistoryLookbackDays));
   deals += ",\"truncated\":" + (truncated ? "true" : "false");
   deals += ",\"ts\":" + IntegerToString((long)TimeLocal()) + "}";
   WriteState("history_deals", deals);

   string orders = "{\"orders\":[" + g_history_orders + "]";
   orders += ",\"count\":" + IntegerToString(g_history_order_count);
   orders += ",\"lookback_days\":" + IntegerToString(MathMax(1, HistoryLookbackDays));
   orders += ",\"truncated\":" + (truncated ? "true" : "false");
   orders += ",\"ts\":" + IntegerToString((long)TimeLocal()) + "}";
   WriteState("history_orders", orders);

   g_history_scan_active = false;
   g_history_dirty = false;
   g_last_history_ms = GetTickCount();
}

void ExportHistoryStep()
{
   if(!g_history_scan_active) StartHistoryExport();
   int batch = MathMax(1, MathMin(HistoryBatchOrders, 100));
   int max_orders = MathMax(1, HistoryMaxOrders);
   int done = 0;
   while(g_history_cursor >= 0 && g_history_scanned < max_orders && done < batch)
   {
      int index = g_history_cursor--;
      g_history_scanned++;
      done++;
      if(!OrderSelect(index, SELECT_BY_POS, MODE_HISTORY)) continue;
      if(OrderType() > OP_SELL || OrderCloseTime() <= 0) continue;
      if((long)OrderCloseTime() < g_history_cutoff) continue;
      if(g_history_order_count > 0) g_history_orders += ",";
      g_history_orders += HistoryOrderJson();
      g_history_order_count++;
      if(g_history_deal_count > 0) g_history_deals += ",";
      g_history_deals += HistoryDealJson(0) + "," + HistoryDealJson(1);
      g_history_deal_count += 2;
   }
   if(g_history_cursor < 0 || g_history_scanned >= max_orders) FinishHistoryExport();
}

void LoadWatch()
{
   // 濮嬬粓?浘琛ㄧ??
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
      // 鏋?绠€????鏀堕泦鎵€鏈夊?屽紩??token,涓㈡帀瀛楅?㈤? "symbols"
      ExtractQuoted(content, syms);
   }
   // 鍘婚?璧嬬粰 g_watch
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

// 鎶?content 閲屾墍鏈?"xxx" 杩藉姞杩?out[]
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

//====================== 鏂囦欢妗ュ啓(鍘熷?)======================

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

// JSON 瀛楃涓插瓧?㈤?(杞箟 " 涓?\)
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
      // ??ASCII 涓㈠純(broker 瀛楁鍩烘湰 ASCII;淇? JSON UTF-8 鏈夋晥)
   }
   o += "\"";
   return o;
}

//====================== 鍛戒护澶勭??Phase D)======================
// Agent 鎶?commands\{id}.json,EA 鎵ц?庡啓 results\{id}.json(tombstone)鍒犲懡浠ゃ€?
// 骞傜瓑瀵硅处:OrderSend 鎵?magic=login + comment=otoken;宕╂簝/瓒呮椂?庢寜 comment ??otoken 璁ら,闃查?寮€銆?

bool ProcessOneCommand()
{
   string fn;
   long h = FileFindFirst(BridgeSubdir + "\\commands\\*.json", fn);
   if(h == INVALID_HANDLE) return false;
   FileFindClose(h);
   HandleCommand(fn);
   return true;
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
   if(StringLen(j) < 2) return;   // ?婂啓,涓嬭疆鍐?澶勭??

   string op = JGetStr(j, "op");
   string otoken = JGetStr(j, "otoken");
   ulong observed_us = GetMicrosecondCount();
   string result;
   if(DispatchExists(cmd_id))
      result = RecoverDispatched(j, op, otoken, observed_us);
   else
   {
      WriteDispatchTombstone(cmd_id, op, otoken, observed_us);
      if(op == "order")           result = ExecOrder(j, otoken, observed_us);
      else if(op == "close")      result = ExecClose(j, observed_us);
      else if(op == "close_all")  result = ExecCloseAll(j);
      else if(op == "cancel_all") result = ExecCancelAll(j);
      else result = "{\"ok\":false,\"error\":\"unknown op\"}";
   }

   WriteResult(cmd_id, result);
   FileDelete(path);
}

bool DispatchExists(string cmd_id)
{
   return FileIsExist(BridgeSubdir + "\\dispatch\\" + cmd_id + ".json");
}

void WriteDispatchTombstone(string cmd_id, string op, string otoken, ulong observed_us)
{
   string rel = BridgeSubdir + "\\dispatch\\" + cmd_id + ".json";
   string tmp = rel + ".tmp";
   int h = FileOpen(tmp, FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h == INVALID_HANDLE) return;
   string j = "{\"command_id\":" + JStr(cmd_id) + ",\"op\":" + JStr(op) +
              ",\"otoken\":" + JStr(otoken) + ",\"observed_us\":" + IntegerToString((long)observed_us) + "}";
   FileWriteString(h, j);
   FileFlush(h);
   FileClose(h);
   FileDelete(rel);
   FileMove(tmp, 0, rel, FILE_REWRITE);
}

string WithTrace(string result, ulong observed_us, ulong broker_start_us, ulong broker_end_us)
{
   if(StringLen(result) < 1) result = "{\"ok\":false,\"error\":\"empty result\"}";
   if(StringGetCharacter(result, StringLen(result)-1) == '}')
      result = StringSubstr(result, 0, StringLen(result)-1);
   ulong broker_ms = (broker_end_us >= broker_start_us && broker_start_us > 0)
                     ? (broker_end_us - broker_start_us) / 1000 : 0;
   return result + ",\"ea_command_observed_us\":" + IntegerToString((long)observed_us) +
          ",\"broker_call_started_us\":" + IntegerToString((long)broker_start_us) +
          ",\"broker_call_returned_us\":" + IntegerToString((long)broker_end_us) +
          ",\"broker_call_ms\":" + IntegerToString((long)broker_ms) + "}";
}

string RecoverDispatched(string j, string op, string otoken, ulong observed_us)
{
   if(op == "order")
   {
      int existing = FindByToken(otoken);
      if(existing >= 0 && OrderSelect(existing, SELECT_BY_TICKET))
         return WithTrace("{\"ok\":true,\"op\":\"order\",\"ticket\":" + IntegerToString(existing) +
                ",\"price\":" + DoubleToString(OrderOpenPrice(), 5) +
                ",\"volume\":" + DoubleToString(OrderLots(), 2) +
                ",\"retcode\":10009,\"partial\":false,\"reconciled\":true}", observed_us, 0, GetMicrosecondCount());
   }
   else if(op == "close")
   {
      int tk = (int)JGetNum(j, "ticket");
      if(tk > 0 && (!OrderSelect(tk, SELECT_BY_TICKET) || OrderCloseTime() != 0))
         return WithTrace("{\"ok\":true,\"op\":\"close\",\"ticket\":" + IntegerToString(tk) +
                ",\"reconciled\":true,\"retcode\":10009}", observed_us, 0, GetMicrosecondCount());
   }
   return WithTrace("{\"ok\":false,\"unknown\":true,\"op\":" + JStr(op) +
          ",\"error\":\"durable dispatch exists but broker outcome is not provable; refused redispatch\"}",
          observed_us, 0, GetMicrosecondCount());
}

int SlipFor(string sym)
{
   int digits = (int)MarketInfo(sym, MODE_DIGITS);
   int e = digits - 2; if(e < 0) e = 0;
   return (int)(50 * MathPow(10, e));   // 2浣?=50 / 3浣?=500 鐐?闃睷EQUOTE,瑙?璁板繂)
}

int FindByToken(string otoken)
{
   if(otoken == "") return -1;
   for(int i = 0; i < OrdersTotal(); i++)
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && StringFind(OrderComment(), otoken) >= 0)
         return OrderTicket();
   // Closed-order recovery is handled by the background reconciler. A full history
   // scan here can stall MT4's single event thread and delay unrelated commands.
   return -1;
}

string ExecOrder(string j, string otoken, ulong observed_us)
{
   string sym  = JGetStr(j, "symbol");
   string side = JGetStr(j, "side");
   double vol  = JGetNum(j, "volume");
   SymbolSelect(sym, true);
   int    cmd  = (side == "sell") ? OP_SELL : OP_BUY;
   double price = 0.0;
   double sl = JGetNum(j, "sl");
   double tp = JGetNum(j, "tp");
   int    slip = SlipFor(sym);
   int    ticket = -1;
   int    err = 0;
   int    requote_retries = 0;
   int    max_requotes = MathMax(0, MathMin(RequoteRetries, 2));
   ulong broker_start_us = GetMicrosecondCount();
   while(true)
   {
      RefreshRates();
      price = (cmd == OP_BUY) ? MarketInfo(sym, MODE_ASK) : MarketInfo(sym, MODE_BID);
      ResetLastError();
      ticket = OrderSend(sym, cmd, vol, price, slip, sl, tp, otoken, (int)AccountNumber(), 0, clrNONE);
      if(ticket >= 0) break;
      err = GetLastError();
      if(err != 138 || requote_retries >= max_requotes) break;
      requote_retries++;
      if(RequoteRetryMs > 0) Sleep(MathMin(RequoteRetryMs, 100));
   }
   ulong broker_end_us = GetMicrosecondCount();
   if(ticket < 0)
   {
      return WithTrace("{\"ok\":false,\"op\":\"order\",\"retcode\":" + IntegerToString(err) +
             ",\"requote_retries\":" + IntegerToString(requote_retries) +
             ",\"error\":\"OrderSend err " + IntegerToString(err) + "\"}", observed_us, broker_start_us, broker_end_us);
   }
   double oprice = price, ovol = vol;
   if(OrderSelect(ticket, SELECT_BY_TICKET)) { oprice = OrderOpenPrice(); ovol = OrderLots(); }
   return WithTrace("{\"ok\":true,\"op\":\"order\",\"ticket\":" + IntegerToString(ticket) +
           ",\"price\":" + DoubleToString(oprice, 5) +
           ",\"volume\":" + DoubleToString(ovol, 2) +
           ",\"requested_volume\":" + DoubleToString(vol, 2) +
           ",\"requote_retries\":" + IntegerToString(requote_retries) +
           ",\"retcode\":10009,\"partial\":false,\"reconciled\":false}", observed_us, broker_start_us, broker_end_us);
}

string ExecClose(string j, ulong observed_us)
{
   int tk = (int)JGetNum(j, "ticket");
   if(tk <= 0)
      return WithTrace("{\"ok\":false,\"op\":\"close\",\"error\":\"EXACT_TICKET_REQUIRED\"}", observed_us, 0, GetMicrosecondCount());
   if(tk > 0)
   {
      if(!OrderSelect(tk, SELECT_BY_TICKET))
         return WithTrace("{\"ok\":true,\"op\":\"close\",\"ticket\":" + IntegerToString(tk) + ",\"reconciled\":true,\"note\":\"not found=closed\",\"retcode\":10009}", observed_us, 0, GetMicrosecondCount());
      if(OrderCloseTime() != 0)
         return WithTrace("{\"ok\":true,\"op\":\"close\",\"ticket\":" + IntegerToString(tk) + ",\"reconciled\":true,\"note\":\"already closed\",\"retcode\":10009}", observed_us, 0, GetMicrosecondCount());
      string sym = OrderSymbol();
      int order_type = OrderType();
      double cprice = 0.0;
      double lots = OrderLots();
      int requote_retries = 0;
      int max_requotes = MathMax(0, MathMin(RequoteRetries, 2));
      int err = 0;
      ulong broker_start_us = GetMicrosecondCount();
      bool closed = false;
      while(true)
      {
         RefreshRates();
         cprice = (order_type == OP_BUY) ? MarketInfo(sym, MODE_BID) : MarketInfo(sym, MODE_ASK);
         ResetLastError();
         closed = OrderClose(tk, lots, cprice, SlipFor(sym), clrNONE);
         if(closed) break;
         err = GetLastError();
         if(err != 138 || requote_retries >= max_requotes) break;
         requote_retries++;
         if(RequoteRetryMs > 0) Sleep(MathMin(RequoteRetryMs, 100));
      }
      ulong broker_end_us = GetMicrosecondCount();
      if(closed)
         return WithTrace("{\"ok\":true,\"op\":\"close\",\"ticket\":" + IntegerToString(tk) + ",\"price\":" + DoubleToString(cprice,5) + ",\"volume\":" + DoubleToString(lots,2) + ",\"requote_retries\":" + IntegerToString(requote_retries) + ",\"retcode\":10009}", observed_us, broker_start_us, broker_end_us);
      return WithTrace("{\"ok\":false,\"op\":\"close\",\"retcode\":" + IntegerToString(err) + ",\"requote_retries\":" + IntegerToString(requote_retries) + "}", observed_us, broker_start_us, broker_end_us);
   }
   return WithTrace("{\"ok\":false,\"op\":\"close\",\"error\":\"EXACT_TICKET_REQUIRED\"}", observed_us, 0, GetMicrosecondCount());
}

string ExecCloseAll(string j)
{
   string sym = JGetStr(j, "symbol");   // "" = 鍏ㄩ儴
   int closed = 0, failed = 0, total_requote_retries = 0; string arr = "";
   for(int i = OrdersTotal()-1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderType() > OP_SELL) continue;
      if(sym != "" && OrderSymbol() != sym) continue;
      int tkt = OrderTicket(); double lots = OrderLots(); string s = OrderSymbol(); int order_type = OrderType();
      double cprice = 0.0; int err = 0; int requote_retries = 0;
      int max_requotes = MathMax(0, MathMin(RequoteRetries, 2)); bool did_close = false;
      while(true)
      {
         RefreshRates();
         cprice = (order_type == OP_BUY) ? MarketInfo(s, MODE_BID) : MarketInfo(s, MODE_ASK);
         ResetLastError();
         did_close = OrderClose(tkt, lots, cprice, SlipFor(s), clrNONE);
         if(did_close) break;
         err = GetLastError();
         if(err != 138 || requote_retries >= max_requotes) break;
         requote_retries++;
         total_requote_retries++;
         if(RequoteRetryMs > 0) Sleep(MathMin(RequoteRetryMs, 100));
      }
      if(arr != "") arr += ",";
      if(did_close) { closed++; arr += "{\"ticket\":" + IntegerToString(tkt) + ",\"success\":true,\"order\":" + IntegerToString(tkt) + ",\"requote_retries\":" + IntegerToString(requote_retries) + "}"; }
      else { failed++; arr += "{\"ticket\":" + IntegerToString(tkt) + ",\"success\":false,\"retcode\":" + IntegerToString(err) + ",\"requote_retries\":" + IntegerToString(requote_retries) + "}"; }
   }
   return "{\"ok\":true,\"op\":\"close_all\",\"closed\":" + IntegerToString(closed) + ",\"failed\":" + IntegerToString(failed) + ",\"requote_retries\":" + IntegerToString(total_requote_retries) + ",\"results\":[" + arr + "]}";
}

string ExecCancelAll(string j)
{
   string sym = JGetStr(j, "symbol");
   int cancelled = 0, failed = 0;
   for(int i = OrdersTotal()-1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderType() <= OP_SELL) continue;   // ?寕??
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
   FileFlush(h);
   FileClose(h);
   FileDelete(rel);
   FileMove(tmp, 0, rel, FILE_REWRITE);
}

// 鈹€鈹€ 鏋?绠€ JSON ?栧€?鍛戒护瀵硅薄鎵?骞?Agent 鐢熸?)鈹€鈹€
string JGetStr(string j, string key)
{
   string pat = "\"" + key + "\":";
   int p = StringFind(j, pat);
   if(p < 0) return "";
   p += StringLen(pat);
   int len = StringLen(j);
   while(p < len && StringGetCharacter(j, p) == ' ') p++;
   if(p >= len || StringGetCharacter(j, p) != '"') return "";   // null/?炰覆
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
