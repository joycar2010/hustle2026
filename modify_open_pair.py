#!/usr/bin/env python3
"""
为cmd_open_pair添加P0追踪的精确修改脚本
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

    print(f"找到cmd_open_pair在第{func_line + 1}行")

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

    # 找到主要的return语句并修改
    for i in range(func_line, min(func_line + 200, len(lines))):
        line = lines[i]
        if 'return {"ok":True,"demo":False,"direction":r.direction,"mode":mode,"opened":opened,"skipped":skipped' in line:
            print(f"找到主return语句在第{i + 1}行")

            # 在return前插入状态更新
            indent = '    '
            status_code = f'{indent}# P0.1: 更新状态并添加command_id\n'
            status_code += f'{indent}tracer.update_status(command_id, CommandStatus.COMPLETED)\n'
            status_code += f'{indent}result = '

            # 修改return为result赋值
            lines[i] = lines[i].replace('return {', status_code + '{', 1)

            # 找到这个return语句的结束(可能跨多行)
            # 在其后添加 result["command_id"] = command_id 和 return result
            lines.insert(i + 1, f'{indent}result["command_id"] = command_id\n')
            lines.insert(i + 2, f'{indent}return result\n')

            print("✓ 修改return语句")
            break

    # 保存修改后的文件
    output_file = '/opt/quanthedge/app.py.p0_traced'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    print(f"✓ 修改完成,保存到 {output_file}")
    return True

if __name__ == '__main__':
    modify_cmd_open_pair()
