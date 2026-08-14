"""基于 LLM 的对话摘要器，用于 Context 压缩。

把"旧摘要 + 新增被截断的历史"合并成更短的新摘要。
带 [internal-summarizer] 标记，MockLLM 能识别并跳过工具决策规则。
"""

from __future__ import annotations

_INTERNAL_MARKER = "[internal-summarizer]"

SUMMARY_PROMPT = """{marker}
你是对话压缩器。把"旧摘要"和"新增对话片段"合并成一段更短的新摘要。

规则：
1. 保留：用户的意图与关键信息、已经确认的事实、未完成的任务/待办、用户偏好。
2. 丢弃：寒暄、重复、与主题无关的中间过程。
3. 不要虚构新增对话里没有出现的内容。
4. 输出为一段连贯的中文，不超过 300 字。

旧摘要：
{old}

新增对话片段：
{dropped}

新摘要："""


def make_summarizer(llm):
    """把 LLM 客户端包装成 ContextManager 需要的 summarizer 回调。"""

    def summarize(old: str, dropped_text: str) -> str:
        prompt = SUMMARY_PROMPT.format(
            marker=_INTERNAL_MARKER, old=old or "（无）", dropped=dropped_text[:4000]
        )
        resp = llm.chat([{"role": "user", "content": prompt}], tools=None, temperature=0.0, max_tokens=600)
        return (resp.content or "").strip()

    return summarize
