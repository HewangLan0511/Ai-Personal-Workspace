-- 0007_life_device.sql · 阶段8：生活中心 + 设备中心（11 §交付物）

-- 预设的 usage_stats（0001 的 id/stat_date/foreground_s 结构）自阶段1 以来
-- **没有任何写入方**（前台采样是本阶段才有的功能），数据量为零。
-- 阶段8 真正实现时改用下方的三列聚合结构 —— 必须先 DROP 旧预设表，
-- 否则 CREATE TABLE IF NOT EXISTS 被旧结构挡住、索引建列失败（测试已复现）。
DROP TABLE IF EXISTS usage_stats;

-- A4 健康生活：前台应用使用时长聚合表。
-- 采样器每 tick 记录"当前前台进程"，按 天+应用 聚累加秒数；
-- 不存时间点明细（11 §A4 数据轻量化）。
CREATE TABLE IF NOT EXISTS usage_stats (
    day      TEXT    NOT NULL,             -- 本地日期 YYYY-MM-DD
    app_name TEXT    NOT NULL,             -- 前台进程名（小写，去 .exe 后缀）
    seconds  INTEGER NOT NULL DEFAULT 0,   -- 累计前台秒数
    PRIMARY KEY (day, app_name)
);

CREATE INDEX IF NOT EXISTS idx_usage_day ON usage_stats(day, seconds DESC);
