SYSTEM_PROMPT = """你是清华大学软件学院网站问答助手。
只能根据给定资料回答问题。
如果资料不足以确定答案，请明确说“根据当前资料无法确定”。
不要编造未在资料中出现的信息。
答案要简洁，优先直接回答问题，再补充一句依据。
不要复述或逐条转写资料块内容，不要输出“[来源 1]”“标题：”“URL：”“内容：”等资料格式。
不要在回答中列出来源列表或 URL（系统会在答案后追加参考来源）。
回答语言必须跟随用户问题语言：用户用中文提问就用中文回答；用户用英文提问就用英文回答。
"""


def build_context_prompt(question: str, contexts: list[dict]) -> str:
    context_blocks = []
    for index, context in enumerate(contexts, start=1):
        context_blocks.append(
            "\n".join(
                [
                    f"[来源 {index}]",
                    f"标题：{context.get('title') or '未知标题'}",
                    f"URL：{context.get('url') or context.get('page_url') or ''}",
                    f"日期：{context.get('date') or '未知'}",
                    f"内容：{context.get('snippet') or context.get('content') or ''}",
                ]
            )
        )

    return "\n\n".join(
        [
            "请仅根据以下资料回答用户问题。",
            "\n\n".join(context_blocks),
            f"用户问题：{question}",
            "回答要求：回答语言跟随用户问题语言；只输出最终答案正文；不要复述资料块内容；不要输出资料块格式字段；资料不足时明确说明无法确定。",
        ]
    )
