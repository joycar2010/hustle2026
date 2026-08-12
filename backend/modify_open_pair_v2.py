#!/usr/bin/env python3
"""
修改cmd_open_pair添加P0追踪 - 修正版
正确处理跨行的return语句
"""

def modify_cmd_open_pair():
    # 读取原始文件
    with open('/opt/quanthedge/app.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 找到cmd_open_pair函数定义
    func_line = None
    for i, line in enumerate(lines):
        if 'async def cmd_open_pair(r:OpenPairReq):' in line:
            func_line = i
            break

    if func_line is None:
        print("错误: 找不到cmd_open_pair")
        return False

    print(f"✓ 找到cmd_open_pair在第{func_line + 1}行")

    # 在函数定义后插入追踪代码
    tracer_code = '''    # === P0.1: 创建command追踪 ===
    tracer = get_tracer()
    command_id = tracer.create_command(
        cmd_type=CommandType.OPEN_PAIR,
        username=r.username,
        symbol=r.symbol,
        direction=r.direction,
        metadata={"slots": r.slots, "slot": r.slot}
    )

'''

    lines.insert(func_line + 1, tracer_code)
    print("✓ 添加追踪入口代码")

    # 找到主return语句(第6604行: return {"ok":True,"demo":False,...)
    # 注意插入后行号会偏移
    main_return_line = None
    for i in range(func_line, min(func_line + 200, len(lines))):
        if 'return {"ok":True,"demo":False,"direction":r.direction,"mode":mode,"opened":opened,"skipped":skipped' in lines[i]:
            main_return_line = i
            print(f"✓ 找到主return语句在第{i + 1}行")
            break

    if main_return_line is None:
        print("错误: 找不到主return语句")
        return False

    # 在return语句前插入状态更新和command_id
    indent = '    '

    # 保存原return语句(可能跨两行)
    return_line1 = lines[main_return_line]
    return_line2 = lines[main_return_line + 1] if main_return_line + 1 < len(lines) else ''

    # 插入状态更新代码
    status_update = f'{indent}# P0.1: 更新状态\n'
    status_update += f'{indent}tracer.update_status(command_id, CommandStatus.COMPLETED)\n'

    lines.insert(main_return_line, status_update)

    # 现在main_return_line指向status_update,原return语句向后移了2行
    actual_return_line = main_return_line + 2

    # 修改return语句,在字典中添加command_id
    # 原: return {"ok":True,"demo":False,...
    # 改: return {"ok":True,"command_id":command_id,"demo":False,...

    lines[actual_return_line] = lines[actual_return_line].replace(
        '{"ok":True,"demo":False,',
        '{"ok":True,"command_id":command_id,"demo":False,',
        1
    )

    print("✓ 修改return语句添加command_id")

    # 保存修改后的文件
    output_file = '/opt/quanthedge/app.py.p0_final'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    print(f"✓ 修改完成,保存到 {output_file}")
    return True

if __name__ == '__main__':
    success = modify_cmd_open_pair()
    exit(0 if success else 1)
