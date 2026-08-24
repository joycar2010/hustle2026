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
#property version   "1.10"
#property description "QH self-hosted MT4 bridge - command-first subsecond scheduler"

input int    TimerMs      = 25;           // command pickup cadence
input string BridgeSubdir = "qhbridge";   // MQL4\Files\ 涓嬬殑妗ョ洰褰?
input int    TickEveryMs  = 100;
input int    PositionEveryMs = 250;
input int    AccountEveryMs  = 1000;
input int    WatchEveryMs    = 1000;
input int    SymbolsEveryMs  = 60000;
input int    HistoryEveryMs  = 60000;
input int    HistoryBatchSize = 1;

string  g_watch[];      // 瑕?瀵煎嚭鐨勭???ヨ嚜 watch.json + 鍥捐〃绗﹀??
uint    g_last_tick_ms = 0;
uint    g_last_position_ms = 0;
uint    g_last_account_ms = 0;
uint    g_last_watch_ms = 0;
uint    g_last_symbols_ms = 0;
uint    g_last_history_ms = 0;
bool    g_history_scanning = false;
int     g_history_cursor = 0;
double  g_history_swap_acc = 0.0;
double  g_closed_swap_cache = 0.0;
datetime g_history_from = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   EventSetMillisecondTimer(MathMax(10, MathMin(TimerMs, 25)));
   LoadWatch();
   ExportMeta();
   ExportAccountFast();
   ExportPositions();
   ExportTicks();
   BeginHistoryRefresh();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   // MQL4 events are serial, so trading commands always run before snapshots.
   bool traded = ProcessOneCommand();
   uint now_ms = GetTickCount();

   if(traded || now_ms - g_last_position_ms >= (uint)PositionEveryMs)
   {
      ExportPositions();
      g_last_position_ms = now_ms;
   }
   if(now_ms - g_last_tick_ms >= (uint)TickEveryMs)
   {
      ExportTicks();
      g_last_tick_ms = now_ms;
   }
   if(traded || now_ms - g_last_account_ms >= (uint)AccountEveryMs)
   {
      ExportHeartbeat();
      ExportMeta();
      ExportAccountFast();
      g_last_account_ms = now_ms;
   }
   if(now_ms - g_last_watch_ms >= (uint)WatchEveryMs)
   {
      LoadWatch();
      g_last_watch_ms = now_ms;
   }
   if(now_ms - g_last_symbols_ms >= (uint)SymbolsEveryMs)
   {
      ExportSymbols();
      g_last_symbols_ms = now_ms;
   }
   if(!g_history_scanning && now_ms - g_last_history_ms >= (uint)HistoryEveryMs)
      BeginHistoryRefresh();
   HistoryRefreshStep();
}

void OnTick()
{
   // Timer coalesces the latest quotes to one bounded write.
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
   j += ",\"ea\":\"QHBridge/1.10\"";
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
   j += ",\"ea\":\"QHBridge/1.10\"";
   j += "}";
   WriteState("meta", j);
}

void ExportAccountFast()
{
   double mlevel = (AccountMargin() > 0.0) ? (AccountEquity() / AccountMargin() * 100.0) : 0.0;

   // 绱 swap = 鎸?浠?swap + 杩?0鏃ュ巻??swap(澶?鍒?mt5-bridge account_info)
   double total_swap = g_closed_swap_cache;
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

void BeginHistoryRefresh()
{
   g_history_scanning = true;
   g_history_cursor = 0;
   g_history_swap_acc = 0.0;
   g_history_from = TimeCurrent() - 30*24*3600;
   g_last_history_ms = GetTickCount();
}

void HistoryRefreshStep()
{
   if(!g_history_scanning) return;
   int total = OrdersHistoryTotal();
   int stop = MathMin(total, g_history_cursor + MathMax(1, HistoryBatchSize));
   for(int h = g_history_cursor; h < stop; h++)
      if(OrderSelect(h, SELECT_BY_POS, MODE_HISTORY) && OrderOpenTime() >= g_history_from)
         g_history_swap_acc += OrderSwap();
   g_history_cursor = stop;
   if(g_history_cursor >= total)
   {
      g_closed_swap_cache = g_history_swap_acc;
      g_history_scanning = false;
   }
}

void ExportPositions()
{
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
      SymbolSelect(sym, true);   // 纭?鍦?Market Watch,MarketInfo 鎵?鏈夋暟
      double bid = MarketInfo(sym, MODE_BID);
      double ask = MarketInfo(sym, MODE_ASK);
      if(bid <= 0.0 && ask <= 0.0) continue;
      long   tt  = (long)MarketInfo(sym, MODE_TIME);   // 鍒稿晢鏈?鍔″櫒鏃?绉?
      long   vol = iVolume(sym, PERIOD_M1, 0);          // MT4 鏃?tick 閲? MarketInfo,??M1 tick 鏁颁綔浠ｇ??
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
   for(int h = 0; h < OrdersHistoryTotal(); h++)
      if(OrderSelect(h, SELECT_BY_POS, MODE_HISTORY) && StringFind(OrderComment(), otoken) >= 0)
         return OrderTicket();
   return -1;
}

string ExecOrder(string j, string otoken, ulong observed_us)
{
   string sym  = JGetStr(j, "symbol");
   string side = JGetStr(j, "side");
   double vol  = JGetNum(j, "volume");
   SymbolSelect(sym, true);
   int    cmd  = (side == "sell") ? OP_SELL : OP_BUY;
   double price = (cmd == OP_BUY) ? MarketInfo(sym, MODE_ASK) : MarketInfo(sym, MODE_BID);
   double sl = JGetNum(j, "sl");
   double tp = JGetNum(j, "tp");
   int    slip = SlipFor(sym);
   ulong broker_start_us = GetMicrosecondCount();
   int    ticket = OrderSend(sym, cmd, vol, price, slip, sl, tp, otoken, (int)AccountNumber(), 0, clrNONE);
   ulong broker_end_us = GetMicrosecondCount();
   if(ticket < 0)
   {
      int err = GetLastError();
      return WithTrace("{\"ok\":false,\"op\":\"order\",\"retcode\":" + IntegerToString(err) +
             ",\"error\":\"OrderSend err " + IntegerToString(err) + "\"}", observed_us, broker_start_us, broker_end_us);
   }
   double oprice = price, ovol = vol;
   if(OrderSelect(ticket, SELECT_BY_TICKET)) { oprice = OrderOpenPrice(); ovol = OrderLots(); }
   return WithTrace("{\"ok\":true,\"op\":\"order\",\"ticket\":" + IntegerToString(ticket) +
           ",\"price\":" + DoubleToString(oprice, 5) +
           ",\"volume\":" + DoubleToString(ovol, 2) +
           ",\"requested_volume\":" + DoubleToString(vol, 2) +
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
      double cprice = (OrderType() == OP_BUY) ? MarketInfo(sym, MODE_BID) : MarketInfo(sym, MODE_ASK);
      double lots = OrderLots();
      ulong broker_start_us = GetMicrosecondCount();
      bool closed = OrderClose(tk, lots, cprice, SlipFor(sym), clrNONE);
      ulong broker_end_us = GetMicrosecondCount();
      if(closed)
         return WithTrace("{\"ok\":true,\"op\":\"close\",\"ticket\":" + IntegerToString(tk) + ",\"price\":" + DoubleToString(cprice,5) + ",\"volume\":" + DoubleToString(lots,2) + ",\"retcode\":10009}", observed_us, broker_start_us, broker_end_us);
      return WithTrace("{\"ok\":false,\"op\":\"close\",\"retcode\":" + IntegerToString(GetLastError()) + "}", observed_us, broker_start_us, broker_end_us);
   }
   return WithTrace("{\"ok\":false,\"op\":\"close\",\"error\":\"EXACT_TICKET_REQUIRED\"}", observed_us, 0, GetMicrosecondCount());
}

string ExecCloseAll(string j)
{
   string sym = JGetStr(j, "symbol");   // "" = 鍏ㄩ儴
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
