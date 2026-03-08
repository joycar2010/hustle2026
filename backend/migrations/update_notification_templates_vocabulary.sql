-- 更新通知模板：将金融词汇替换为生鲜配送行业词汇
-- 执行时间: 2026-03-06

-- 词汇映射：
-- Binance/币安 -> 供应商A/仓库A
-- Bybit -> 供应商B/仓库B
-- 交易/订单 -> 配送单/订单
-- 套利 -> 调配
-- 开仓 -> 发货
-- 平仓 -> 收货
-- 点差/价差 -> 价格差异
-- 持仓 -> 在途货物
-- 爆仓 -> 库存告急
-- 阈值 -> 标准值
-- 净资产 -> 库存总值
-- 保证金 -> 备用金
-- 杠杆 -> 周转率
-- 盈亏 -> 损益

-- 更新所有模板的标题和内容
UPDATE notification_templates
SET
    title_template = REPLACE(
        REPLACE(
            REPLACE(
                REPLACE(
                    REPLACE(
                        REPLACE(
                            REPLACE(
                                REPLACE(
                                    REPLACE(
                                        REPLACE(
                                            REPLACE(
                                                REPLACE(title_template, 'Binance', '供应商A'),
                                                'binance', '供应商A'
                                            ),
                                            'Bybit', '供应商B'
                                        ),
                                        'bybit', '供应商B'
                                    ),
                                    '币安', '供应商A'
                                ),
                                '套利', '调配'
                            ),
                            '开仓', '发货'
                        ),
                        '平仓', '收货'
                    ),
                    '点差', '价格差异'
                ),
                '价差', '价格差异'
            ),
            '阈值', '标准值'
        ),
        '爆仓', '库存告急'
    ),
    content_template = REPLACE(
        REPLACE(
            REPLACE(
                REPLACE(
                    REPLACE(
                        REPLACE(
                            REPLACE(
                                REPLACE(
                                    REPLACE(
                                        REPLACE(
                                            REPLACE(
                                                REPLACE(
                                                    REPLACE(
                                                        REPLACE(
                                                            REPLACE(
                                                                REPLACE(
                                                                    REPLACE(
                                                                        REPLACE(
                                                                            REPLACE(
                                                                                REPLACE(content_template, 'Binance', '供应商A'),
                                                                                'binance', '供应商A'
                                                                            ),
                                                                            'Bybit', '供应商B'
                                                                        ),
                                                                        'bybit', '供应商B'
                                                                    ),
                                                                    '币安', '供应商A'
                                                                ),
                                                                '套利', '调配'
                                                            ),
                                                            '开仓', '发货'
                                                        ),
                                                        '平仓', '收货'
                                                    ),
                                                    '点差', '价格差异'
                                                ),
                                                '价差', '价格差异'
                                            ),
                                            '持仓', '在途货物'
                                        ),
                                        '爆仓', '库存告急'
                                    ),
                                    '阈值', '标准值'
                                ),
                                '净资产', '库存总值'
                            ),
                            '保证金', '备用金'
                        ),
                        '杠杆', '周转率'
                    ),
                    '盈亏', '损益'
                ),
                '交易', '配送'
            ),
            '订单', '配送单'
        ),
        '仓位', '货位'
    ),
    updated_at = NOW()
WHERE
    title_template LIKE '%Binance%' OR
    title_template LIKE '%binance%' OR
    title_template LIKE '%Bybit%' OR
    title_template LIKE '%bybit%' OR
    title_template LIKE '%币安%' OR
    title_template LIKE '%套利%' OR
    title_template LIKE '%开仓%' OR
    title_template LIKE '%平仓%' OR
    title_template LIKE '%点差%' OR
    title_template LIKE '%价差%' OR
    title_template LIKE '%阈值%' OR
    title_template LIKE '%爆仓%' OR
    content_template LIKE '%Binance%' OR
    content_template LIKE '%binance%' OR
    content_template LIKE '%Bybit%' OR
    content_template LIKE '%bybit%' OR
    content_template LIKE '%币安%' OR
    content_template LIKE '%套利%' OR
    content_template LIKE '%开仓%' OR
    content_template LIKE '%平仓%' OR
    content_template LIKE '%点差%' OR
    content_template LIKE '%价差%' OR
    content_template LIKE '%持仓%' OR
    content_template LIKE '%爆仓%' OR
    content_template LIKE '%阈值%' OR
    content_template LIKE '%净资产%' OR
    content_template LIKE '%保证金%' OR
    content_template LIKE '%杠杆%' OR
    content_template LIKE '%盈亏%' OR
    content_template LIKE '%交易%' OR
    content_template LIKE '%订单%' OR
    content_template LIKE '%仓位%';

-- 显示更新结果
SELECT
    template_key,
    template_name,
    title_template,
    LEFT(content_template, 100) as content_preview
FROM notification_templates
ORDER BY category, template_key;
