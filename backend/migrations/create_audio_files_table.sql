-- 创建音频文件表
CREATE TABLE IF NOT EXISTS audio_files (
    file_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name VARCHAR(255) NOT NULL UNIQUE,
    file_path VARCHAR(500) NOT NULL,
    file_key VARCHAR(255),
    file_size VARCHAR(50),
    is_synced BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    synced_at TIMESTAMP
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_audio_files_file_name ON audio_files(file_name);
CREATE INDEX IF NOT EXISTS idx_audio_files_is_synced ON audio_files(is_synced);

-- 插入现有的音频文件（如果存在）
-- 注意：这需要手动运行或通过脚本扫描文件系统
