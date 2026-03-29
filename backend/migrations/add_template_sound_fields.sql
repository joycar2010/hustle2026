-- Add alert_sound and repeat_count fields to notification_templates table

ALTER TABLE notification_templates
ADD COLUMN IF NOT EXISTS alert_sound VARCHAR(500),
ADD COLUMN IF NOT EXISTS repeat_count INTEGER DEFAULT 3;

-- Add comment
COMMENT ON COLUMN notification_templates.alert_sound IS '提醒声音文件路径';
COMMENT ON COLUMN notification_templates.repeat_count IS '声音重复次数';
