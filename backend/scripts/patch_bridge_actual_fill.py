# -*- coding: utf-8 -*-
"""20260716 V1.1 §7.1 桥补丁: /mt5/order 接受 DONE_PARTIAL + 返回实际成交四量字段。
用法: python patch_bridge_actual_fill.py D:\\hustle-mt5-mt5-ic02-0 [更多桥目录...]
幂等: 已打过补丁(检测到 filled_volume)则跳过。自动备份 main.py.bak_actualfill_<ts>。
"""
import sys, os, shutil, time

OLD = '''        if result.retcode == mt5.TRADE_RETCODE_DONE:
            mgr.ping()
            logger.info(f"Order OK | sym={req.symbol} side={req.order_type} vol={volume} "
                        f"price={request.get('price')} order={result.order}")
            return {
                "success":  True,
                "retcode":  result.retcode,
                "order":    result.order,
                "deal":     result.deal,
                "volume":   result.volume,
                "price":    result.price,
                "comment":  result.comment,
            }'''

NEW = '''        # 20260716 实际成交口径(V1.1 §7.1): 同时接受 DONE 和 DONE_PARTIAL(10010)。
        # 旧行为把部分成交抛400 → 后端当整单失败按全量重试, 已成交部分成双重敞口。
        # volume 字段语义升级为"实际成交量"(DONE时=请求量, 向后兼容), 并补
        # requested/normalized/filled/remaining 四量与 partial 标志。
        if result.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
            mgr.ping()
            _filled = float(result.volume or 0.0)
            _partial = (result.retcode == mt5.TRADE_RETCODE_DONE_PARTIAL)
            logger.info(f"Order OK{' (PARTIAL)' if _partial else ''} | sym={req.symbol} side={req.order_type} "
                        f"req_vol={volume} filled={_filled} price={result.price} order={result.order}")
            return {
                "success":  True,
                "retcode":  result.retcode,
                "order":    result.order,
                "deal":     result.deal,
                "volume":   _filled,
                "price":    result.price,
                "comment":  result.comment,
                "requested_volume": req.volume,
                "normalized_volume": volume,
                "filled_volume": _filled,
                "remaining_volume": max(0.0, round(volume - _filled, 8)),
                "partial": _partial,
            }'''


def patch(bridge_dir):
    p = os.path.join(bridge_dir, 'app', 'main.py')
    src = open(p, encoding='utf-8').read()
    if 'filled_volume' in src:
        print('SKIP(already patched): ' + p)
        return True
    n = src.count(OLD)
    if n != 1:
        print('ABORT: match=%d (expect 1) in %s' % (n, p))
        return False
    bak = p + '.bak_actualfill_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(p, bak)
    open(p, 'w', encoding='utf-8').write(src.replace(OLD, NEW))
    import py_compile
    py_compile.compile(p, doraise=True)
    print('PATCHED+COMPILED: %s (backup=%s)' % (p, os.path.basename(bak)))
    return True


if __name__ == '__main__':
    ok = all(patch(d) for d in sys.argv[1:])
    sys.exit(0 if ok else 1)
