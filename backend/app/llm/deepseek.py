"""
DeepSeek LLM 实现（真实调用 DeepSeek API）

实现了 LLMProvider 接口。
由于 DeepSeek 提供 OpenAI 兼容接口，可以直接用 langchain-openai 的 ChatOpenAI。

关键点（依赖倒置的体现）：
- Text2SqlEngine 只依赖 LLMProvider 接口
- 之前用 MockLLM，现在换成 DeepSeekLLM
- 引擎代码完全不用改，这就是「面向接口编程」的好处
"""
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from app.llm.provider import LLMProvider

# 加载 .env 文件中的环境变量
load_dotenv()


class DeepSeekLLM(LLMProvider):
    """真实的 DeepSeek 大模型"""

    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        if not api_key:
            raise ValueError(
                "未找到 DEEPSEEK_API_KEY，请在 backend/.env 文件中配置"
            )

        # 用 ChatOpenAI 连接 DeepSeek（OpenAI 兼容）
        self._client = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0,  # 0 = 更确定、更稳定，适合生成 SQL
        )

    def chat(self, prompt: str) -> str:
        """通用对话：给一段提示词，返回模型的文本回答"""
        response = self._client.invoke(prompt)
        return response.content

    def generate_sql(self, prompt: str) -> str:
        """调用 DeepSeek 生成 SQL"""
        # 复用 chat（生成 SQL 本质也是一次对话）
        return self.chat(prompt)
