"""
更新通知模板词汇：将金融词汇替换为生鲜配送行业词汇
"""
import asyncio
import sys
import os
import io

# 设置UTF-8编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def update_templates():
    """更新通知模板中的词汇"""

    # 词汇映射
    replacements = [
        ('Binance', '供应商A'),
        ('binance', '供应商A'),
        ('Bybit', '供应商B'),
        ('bybit', '供应商B'),
        ('币安', '供应商A'),
        ('套利', '调配'),
        ('开仓', '发货'),
        ('平仓', '收货'),
        ('点差', '价格差异'),
        ('价差', '价格差异'),
        ('持仓', '在途货物'),
        ('爆仓', '库存告急'),
        ('阈值', '标准值'),
        ('净资产', '库存总值'),
        ('保证金', '备用金'),
        ('杠杆', '周转率'),
        ('盈亏', '损益'),
        ('交易', '配送'),
        ('仓位', '货位'),
    ]

    async with AsyncSessionLocal() as db:
        try:
            # 获取所有模板
            result = await db.execute(
                text("SELECT template_id, template_key, template_name, title_template, content_template FROM notification_templates")
            )
            templates = result.fetchall()

            print(f"找到 {len(templates)} 个模板")

            updated_count = 0
            for template in templates:
                template_id, template_key, template_name, title_template, content_template = template

                # 应用替换
                new_title = title_template
                new_content = content_template

                for old_word, new_word in replacements:
                    new_title = new_title.replace(old_word, new_word)
                    new_content = new_content.replace(old_word, new_word)

                # 如果有变化，更新数据库
                if new_title != title_template or new_content != content_template:
                    await db.execute(
                        text("""
                            UPDATE notification_templates
                            SET title_template = :title,
                                content_template = :content,
                                updated_at = NOW()
                            WHERE template_id = :id
                        """),
                        {
                            "title": new_title,
                            "content": new_content,
                            "id": template_id
                        }
                    )
                    updated_count += 1
                    print(f"✓ 更新模板: {template_key} - {template_name}")
                    print(f"  标题: {title_template[:50]}... -> {new_title[:50]}...")

            await db.commit()
            print(f"\n成功更新 {updated_count} 个模板")

            # 显示更新后的模板
            print("\n更新后的模板列表:")
            result = await db.execute(
                text("""
                    SELECT template_key, template_name, title_template,
                           LEFT(content_template, 80) as content_preview
                    FROM notification_templates
                    ORDER BY category, template_key
                """)
            )
            templates = result.fetchall()

            for template in templates:
                print(f"\n{template[0]} - {template[1]}")
                print(f"  标题: {template[2]}")
                print(f"  内容: {template[3]}...")

        except Exception as e:
            print(f"错误: {e}")
            await db.rollback()
            raise

if __name__ == "__main__":
    asyncio.run(update_templates())
