"""骰子插件：/roll 2d6、/draw 抽签。"""

from __future__ import annotations

import random


def register(ctx) -> None:
    max_dice = int(ctx.config.get("max_dice", 10))
    max_faces = int(ctx.config.get("max_faces", 100))

    async def roll(message):
        expr = (message.args[0] if message.args else "1d6").lower()
        count, _, faces = expr.partition("d")
        try:
            dice = max(1, min(int(count or 1), max_dice))
            sides = max(2, min(int(faces or 6), max_faces))
        except ValueError:
            return "格式错误，示例：/roll 2d6"
        results = [random.randint(1, sides) for _ in range(dice)]
        return f"🎲 {dice}d{sides}：{' + '.join(map(str, results))} = {sum(results)}"

    async def draw(message):
        options = ctx.config.get("lots") or ["上上签", "上签", "中签", "下签"]
        return f"📜 抽签结果：{random.choice(options)}"

    ctx.add_command("roll", roll, description="掷骰子，例如 /roll 2d6", aliases=["骰子"])
    ctx.add_command("draw", draw, description="随机抽签", aliases=["抽签"])
