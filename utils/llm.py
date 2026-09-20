"""
LLM 调用封装模块。

设计目标：
- 使用 .env 中的 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 配置一个 OpenAI 兼容的
  Chat Completions 接口（兼容 OpenAI / DeepSeek / Moonshot / 智谱 GLM-4 / 硅基流动
  / Ollama 的 OpenAI 兼容端点等主流服务，无需为每个厂商单独接入 SDK）。
- 任何异常（未配置 Key、网络失败、超时、返回格式异常）都不会让程序崩溃，
  而是返回结构化的 {"success": False, "error": "..."}，由上层决定如何降级。
"""

import os
from dataclasses import dataclass
from typing import List, Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_TIMEOUT = 30


@dataclass
class LLMResult:
    success: bool
    content: str = ""
    error: Optional[str] = None


def get_config():
    """读取当前 LLM 配置（每次调用都重新读取环境变量，方便测试 / 动态修改 .env）。"""
    return {
        "api_key": os.getenv("LLM_API_KEY", "").strip(),
        "base_url": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
        "model": os.getenv("LLM_MODEL", "gpt-4o-mini").strip(),
    }


def is_configured() -> bool:
    """判断是否已经配置了可用的 API Key。"""
    return bool(get_config()["api_key"])


def chat(messages: List[Dict[str, str]], temperature: float = 0.5, max_tokens: int = 1800) -> LLMResult:
    """
    调用 LLM 的 Chat Completions 接口。

    参数：
        messages: 形如 [{"role": "user", "content": "..."}] 的对话列表
        temperature: 采样温度
        max_tokens: 最大生成 token 数

    返回：
        LLMResult，success 为 False 时 error 中包含可读的失败原因，
        UI 层可以据此展示错误信息，而不是让整个程序崩溃。
    """
    config = get_config()

    if not config["api_key"]:
        return LLMResult(success=False, error="未配置 LLM_API_KEY，请在 .env 中设置后重试。")

    url = f"{config['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    except requests.exceptions.Timeout:
        return LLMResult(success=False, error="调用大模型超时，请检查网络或稍后重试。")
    except requests.exceptions.ConnectionError:
        return LLMResult(success=False, error="无法连接到大模型服务，请检查 LLM_BASE_URL 配置或网络连接。")
    except requests.exceptions.RequestException as e:
        return LLMResult(success=False, error=f"请求大模型时发生错误：{e}")

    if resp.status_code != 200:
        # 尽量把服务端返回的错误信息透出来，方便现场排查
        detail = resp.text[:300] if resp.text else ""
        return LLMResult(success=False, error=f"大模型接口返回错误（状态码 {resp.status_code}）：{detail}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return LLMResult(success=False, error="大模型返回格式异常，无法解析结果。")

    if not content or not content.strip():
        return LLMResult(success=False, error="大模型返回了空内容。")

    return LLMResult(success=True, content=content.strip())
