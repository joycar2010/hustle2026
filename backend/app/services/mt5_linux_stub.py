"""
Linux MT5 stub — MetaTrader5 SDK is Windows-only.
On Linux, MT5 operations are proxied to the Windows MT5 bridge service.
This stub satisfies imports and provides no-op fallbacks.
"""
import logging
logger = logging.getLogger(__name__)

class MT5Client:
    """Linux stub: all MT5 calls return safe defaults"""
    def __init__(self, login=0, password='', server='', path=None):
        self.login = login
        self.password = password
        self.server = server
        self.path = path
        self.connected = False
        self.last_error = 'MT5 not available on Linux'

    def connect(self): return False
    def disconnect(self): pass
    def get_account_info(self): return None
    def get_positions(self, symbol=None): return []
    def get_orders(self, symbol=None): return []
    def get_tick(self, symbol): return None
    def place_order(self, *a, **kw): return {'success': False, 'error': 'MT5 not available on Linux'}
    def close_position(self, *a, **kw): return {'success': False, 'error': 'MT5 not available on Linux'}
    def find_position_to_close(self, symbol, side, required_volume=0.0): return None

MT5ClientAdapter = MT5Client
