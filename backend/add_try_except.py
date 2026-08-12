#!/usr/bin/env python3
"""
为cmd_open_pair添加try-except包裹 - 最终版本
"""

def add_try_except_wrapper():
    print("=== 读取app.py ===")
    with open('/opt/quanthedge/app.py', 'r') as f:
        lines = f.readlines()

    print(f"总行数: {len(lines)}")

    # 1. 找到metadata行,在其后插入try:
    metadata_line = None
    for i, line in enumerate(lines):
        if 'metadata={"slots": r.slots, "slot": r.slot}' in line:
            metadata_line = i
            print(f"找到metadata行: {i + 1}")
            break

    if metadata_line is None:
        print("错误: 找不到metadata行")
        return False

    # 在metadata行的闭合括号后插入空行和try:
    lines.insert(metadata_line + 2, '\n    try:\n')
    print(f"✓ 在第{metadata_line + 3}行插入 try:")

    # 2. 缩进后续代码
    # 找到 actor=_actor 开始
    actor_line = None
    for i in range(metadata_line, metadata_line + 20):
        if i < len(lines) and 'actor=_actor(r.license_key)' in lines[i]:
            actor_line = i
            print(f"找到actor行: {i + 1}")
            break

    # 找到主return语句结束(包含"已顺序开")
    return_end = None
    for i in range(actor_line, actor_line + 200):
        if i < len(lines) and '"msg":"已顺序开' in lines[i]:
            return_end = i + 1  # 跨两行,+1到第二行
            print(f"找到return结束行: {i + 1}")
            break

    if actor_line is None or return_end is None:
        print("错误: 找不到缩进范围")
        return False

    # 缩进这个范围内的所有非空行
    print(f"缩进范围: {actor_line + 1} 到 {return_end + 1}")
    indent_count = 0
    for i in range(actor_line, return_end + 1):
        if i < len(lines):
            line = lines[i]
            if line.strip():  # 非空行
                lines[i] = '    ' + line
                indent_count += 1

    print(f"✓ 缩进了 {indent_count} 行")

    # 3. 在return语句后添加except块
    insert_pos = return_end + 1

    exception_code = '''    except HTTPException as he:
        tracer.update_status(command_id, CommandStatus.FAILED)
        tracer.update_field(command_id, "failure_reason", str(he.detail))
        tracer.record_timestamp(command_id, TraceTimestamp.HTTP_SENT)
        raise
    except Exception as e:
        tracer.update_status(command_id, CommandStatus.FAILED)
        tracer.update_field(command_id, "error", str(e))
        tracer.record_timestamp(command_id, TraceTimestamp.HTTP_SENT)
        raise

'''

    lines.insert(insert_pos, exception_code)
    print(f"✓ 在第{insert_pos + 1}行插入异常处理")

    # 保存
    with open('/opt/quanthedge/app.py', 'w') as f:
        f.writelines(lines)

    print("✓ 修改完成,已保存")
    return True

if __name__ == '__main__':
    import sys
    success = add_try_except_wrapper()
    sys.exit(0 if success else 1)
