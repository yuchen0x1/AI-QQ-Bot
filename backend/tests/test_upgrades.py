"""新增核心特性自动化测试：
1. 官方机器人 URL 自动转写脱敏（规避 40054010 拦截）
2. 历史过期数据清理任务 (clean_expired_data)
3. 第三方系统告警通道 (alerting) 测试
4. AI Playground 调试沙盒参数化调用测试
"""
from __future__ import annotations

import httpx
from app.adapters.qq_official import sanitize_official_text
from app.services.alerting import _build_payload, _detect_channel, validate_webhook_url
from app.services.scheduler import _task_clean_expired_data


def test_sanitize_official_text_urls():
    text = "请查看项目 https://github.com/foo/bar 以及 http://example.com/test?a=1"
    cleaned = sanitize_official_text(text)
    assert "https://" not in cleaned
    assert "http://" not in cleaned
    assert "github.com/foo/bar" in cleaned
    assert "[链接]" in cleaned


def test_alert_channel_detection_and_payload():
    feishu_url = "https://open.feishu.cn/open-apis/bot/v2/hook/xyz123"
    assert _detect_channel(feishu_url) == "feishu"
    feishu_payload = _build_payload("feishu", "测试标题", "错误详情")
    assert feishu_payload["msg_type"] == "post"

    dingtalk_url = "https://oapi.dingtalk.com/robot/send?access_token=xyz"
    assert _detect_channel(dingtalk_url) == "dingtalk"
    dingtalk_payload = _build_payload("dingtalk", "测试标题", "错误详情")
    assert dingtalk_payload["msgtype"] == "markdown"

    wechat_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xyz"
    assert _detect_channel(wechat_url) == "wechat"
    wechat_payload = _build_payload("wechat", "测试标题", "错误详情")
    assert wechat_payload["msgtype"] == "markdown"


def test_alert_webhook_url_blocks_ssrf_targets():
    assert validate_webhook_url("https://open.feishu.cn/open-apis/bot/v2/hook/xyz")[0] is True
    assert validate_webhook_url("file:///etc/passwd")[0] is False
    assert validate_webhook_url("http://127.0.0.1:8080/health")[0] is False
    assert validate_webhook_url("http://169.254.169.254/latest/meta-data")[0] is False
    assert validate_webhook_url("http://localhost:8080/hook")[0] is False
    assert validate_webhook_url("http://internal-service/hook")[0] is False
    assert validate_webhook_url("http://10.0.0.5/hook", allow_private=True)[0] is True


async def test_clean_expired_data_job(client: httpx.AsyncClient):
    # client fixture 会初始化 lifespan 并创建好数据库表结构
    result = await _task_clean_expired_data({"days": 30})
    assert "messages" in result
    assert "logs" in result
    assert result["days"] == 30


async def test_ai_playground_chat_endpoint(client: httpx.AsyncClient, admin_headers: dict):
    response = await client.post(
        "/api/ai/chat",
        headers=admin_headers,
        json={
            "messages": [{"role": "user", "content": "你好"}],
            "system_prompt": "你是单元测试助手",
            "temperature": 0.5,
            "max_tokens": 512,
        },
    )
    # 若本地无可用 Provider 返回 400，若有 Mock/真实 Provider 则返回 200，皆不抛 500
    assert response.status_code in (200, 400)
    if response.status_code == 200:
        data = response.json()
        assert "content" in data
