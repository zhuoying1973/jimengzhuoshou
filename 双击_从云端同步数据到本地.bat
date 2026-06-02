@echo off
chcp 65001 >nul
echo 正在启动即梦助手云端数据拉取系统，请稍候...
python scratch/sync_from_aliyun.py
